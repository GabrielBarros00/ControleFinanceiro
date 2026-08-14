import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { HandCoins, Loader2 } from 'lucide-react';
import { useTxDetailStore } from '@/stores';
import type { SettlementDraft } from '@/components/debts/SettlementDialog';
import { formatMoney } from '@/lib/money';

/**
 * O CORPO do retrato mensal de uma casa — sem hook nenhum.
 *
 * Extraído de `MonthlyDebtsSection` quando os acertos ganharam a camada global
 * (ADR 0027): a tela da casa monta um destes, a tela global monta um POR CASA. A
 * alternativa era copiar 150 linhas de tabela e deixar as duas divergirem no
 * primeiro ajuste — foi assim que o app acabou com dois "Acertos" que não
 * mostravam a mesma coisa.
 *
 * Tudo entra por prop porque as duas telas resolvem as mesmas coisas por caminhos
 * diferentes: a casa tem `useBaseCurrency`/`useMembers`/`useWorkspaceRole`, e a
 * global recebe moeda, pessoas e papel prontos do backend, um conjunto por casa.
 */
export interface MemberLike {
  user_id: number;
  user_name?: string;
}

/** `string | number` de propósito: `/{ws}/debts/monthly` é uma rota
 *  `Dict[str, Any]` e devolve NÚMERO; `/me/debts/monthly` tem `response_model`
 *  tipado e o Pydantic serializa `Decimal` como STRING. O mesmo componente
 *  desenha as duas, então a coerção é explícita aqui. */
type Money = string | number;

export interface LedgerLike {
  net_debts: { debtor_id: number; creditor_id: number; amount: Money }[];
  expenses: {
    id: number;
    title: string;
    total_amount: Money;
    is_paid: boolean;
    installment_no?: number | null;
    installments_of?: number | null;
    payers: { user_id: number; amount: Money }[];
    splits: { user_id: number; computed_amount: Money }[];
  }[];
  settled_total: Money;
  settlements: {
    id: number;
    from_user_id: number;
    to_user_id: number;
    amount: Money;
  }[];
  totals: { total: Money; paid: Money; open: Money };
}

interface Props {
  ledger: LedgerLike | null | undefined;
  members: MemberLike[];
  currentUserId?: number;
  canWrite: boolean;
  /** Moeda-base DESTA casa. Na tela global cada grupo tem a sua. */
  currency: string;
  /** Vai no draft para o acerto quitar o mês certo, não o saldo global. */
  month: string;
  isLoading?: boolean;
  onSettle: (draft: SettlementDraft) => void;
}

/** Os três totais do mês. Fica separado do corpo porque a tela da casa os
 *  desenha no cabeçalho do card, acima do navegador de mês. */
export function MonthlyLedgerTotals({
  ledger,
  currency,
}: {
  ledger: LedgerLike | null | undefined;
  currency: string;
}) {
  if (!ledger) return null;
  const fmt = (v: Money) => formatMoney(v, { currency });
  return (
    <div className="grid grid-cols-3 gap-2 text-center">
      <div className="rounded-lg bg-accent/20 p-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Total do mês</p>
        <p className="text-sm font-semibold text-foreground">{fmt(ledger.totals.total)}</p>
      </div>
      <div className="rounded-lg bg-emerald-500/10 p-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Pago</p>
        <p className="text-sm font-semibold text-emerald-500">{fmt(ledger.totals.paid)}</p>
      </div>
      <div className="rounded-lg bg-warning-subtle p-2">
        <p className="text-[10px] font-semibold uppercase text-muted-foreground">Em aberto</p>
        <p className="text-sm font-semibold text-warning">{fmt(ledger.totals.open)}</p>
      </div>
    </div>
  );
}

export function MonthlyLedgerBody({
  ledger,
  members,
  currentUserId,
  canWrite,
  currency,
  month,
  isLoading = false,
  onSettle,
}: Props) {
  const openDetail = useTxDetailStore((s) => s.open);
  const fmt = (v: Money) => formatMoney(v, { currency });

  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;
  const memberInitials = (id: number) => memberName(id).slice(0, 2).toUpperCase();

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!ledger || ledger.expenses.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Nenhuma despesa neste mês.
      </p>
    );
  }

  const acertado = Number(ledger.settled_total);

  return (
    <>
      {/* Quem deve quem NO MÊS */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Acertos do mês</p>
          {acertado > 0 && (
            <span className="shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase whitespace-nowrap text-emerald-500">
              {fmt(ledger.settled_total)} pago
            </span>
          )}
        </div>
        {ledger.net_debts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {acertado > 0 ? 'Tudo acertado neste mês. ✅' : 'Ninguém deve nada neste mês. 🎉'}
          </p>
        ) : (
          <div className="space-y-2">
            {ledger.net_debts.map((d) => (
              <div key={`${d.debtor_id}-${d.creditor_id}`} className="flex items-center justify-between rounded-xl bg-accent/30 border border-border p-3">
                <p className="text-sm">
                  <span className="font-bold">{memberName(d.debtor_id)}</span>
                  <span className="text-muted-foreground"> deve </span>
                  <span className="font-semibold text-destructive">{fmt(d.amount)}</span>
                  <span className="text-muted-foreground"> a </span>
                  <span className="font-bold">{memberName(d.creditor_id)}</span>
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!canWrite}
                  onClick={() => onSettle({ from_user_id: d.debtor_id, to_user_id: d.creditor_id, amount: Number(d.amount), billing_month: month })}
                  className="gap-1.5 font-bold"
                >
                  <HandCoins className="h-3.5 w-3.5" /> Registrar
                </Button>
              </div>
            ))}
          </div>
        )}
        {/* Acertos já registrados para este mês — deixa claro quem pagou */}
        {ledger.settlements.length > 0 && (
          <div className="space-y-1 pt-1">
            {ledger.settlements.map((s) => (
              <p key={s.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <HandCoins className="h-3 w-3 shrink-0 text-emerald-500" />
                <span className="font-bold text-foreground">{memberName(s.from_user_id)}</span> pagou{' '}
                <span className="font-semibold text-emerald-500">{fmt(s.amount)}</span> a{' '}
                <span className="font-bold text-foreground">{memberName(s.to_user_id)}</span>
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Detalhe das despesas do mês */}
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Despesas do mês</p>
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              {/* Larguras fixas nas duas últimas colunas. Sem elas o algoritmo de
                  tabela reparte o espaço pelo CONTEÚDO, e uma despesa de título
                  longo ("Matrícula e mensalidade anual da escola bilíngue das
                  crianças") espremia o status até "EM ABERTO" quebrar em duas
                  linhas e o valor em R$ 94.800,00 quebrar depois do ponto. */}
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Despesa</TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Quem pagou</TableHead>
              <TableHead className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Divisão</TableHead>
              <TableHead className="w-28 text-center text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap text-muted-foreground">Status</TableHead>
              <TableHead className="w-32 text-right text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap text-muted-foreground">Valor</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ledger.expenses.map((exp) => (
              <TableRow
                key={exp.id}
                onClick={() => openDetail(exp.id)}
                title="Ver detalhes do lançamento"
                className="cursor-pointer border-border hover:bg-accent/30"
              >
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <span className="text-sm font-bold text-foreground">{exp.title}</span>
                    {exp.installments_of && exp.installments_of > 1 && (
                      <span className="w-fit rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase whitespace-nowrap text-primary">
                        Parcela {exp.installment_no}/{exp.installments_of}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                    {exp.payers.map((p, i) => (
                      <span key={i}>
                        {memberName(p.user_id)} · {fmt(p.amount)}
                      </span>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {exp.splits.map((s, i) => {
                      const mine = s.user_id === currentUserId;
                      return (
                        <span
                          key={i}
                          title={`${memberName(s.user_id)} — ${fmt(s.computed_amount)}`}
                          className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-bold ${
                            mine
                              ? 'border-primary/40 bg-primary/15 text-primary'
                              : 'border-border bg-accent/40 text-muted-foreground'
                          }`}
                        >
                          {mine ? 'Você' : memberInitials(s.user_id)} · {fmt(s.computed_amount)}
                        </span>
                      );
                    })}
                  </div>
                </TableCell>
                <TableCell className="text-center">
                  {/* `inline-block` + `whitespace-nowrap`: o badge é um `span`
                      inline, então sem isto ele quebra DENTRO do próprio pill e
                      o fundo arredondado sai partido em duas metades. */}
                  {exp.is_paid ? (
                    <span className="inline-block rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase whitespace-nowrap text-emerald-500">Paga</span>
                  ) : (
                    <span className="inline-block rounded-full bg-warning-subtle px-2 py-0.5 text-[10px] font-semibold uppercase whitespace-nowrap text-warning">Em aberto</span>
                  )}
                </TableCell>
                <TableCell className="text-right font-semibold whitespace-nowrap text-foreground">{fmt(exp.total_amount)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
