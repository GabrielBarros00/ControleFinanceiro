import * as React from 'react';
import { AlertTriangle, CalendarClock, CheckCircle2, Repeat, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile } from '@/components/ui/stat-tile';
import { StatusPill } from '@/components/ui/status-pill';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { nativeSelectClass } from '@/components/ui/native-select';
import { useSettlePayables, type PayableEntry, type Payables } from '@/hooks/use-payables';
import { getApiErrorMessage } from '@/lib/api-error';
import { formatMoney } from '@/lib/money';
import { paymentMethodLabel } from '@/lib/payment-methods';
import { parseApiDay, todayLocalISO } from '@/lib/date';
import { toast } from '@/stores/toast';

/**
 * Contas a pagar (ADR 0029) — a lista, compartilhada pelas duas camadas.
 *
 * `/me/payables` responde "o que EU tenho a pagar, somando meus espaços" e
 * `/w/:id/payables` responde "o que ESTA casa tem em aberto". As duas desenham a
 * mesma coisa; o que muda é o recorte e se a coluna do espaço aparece. Um
 * componente só, porque duas cópias divergiriam — foi o que aconteceu com o
 * extrato antes de ele passar a sair da mesma consulta do total.
 *
 * **Três grupos, nesta ordem: vencidas, a vencer, e o resto.** Uma fila de
 * pagamento se lê por urgência, ao contrário do extrato (histórico, do mais
 * recente para o mais antigo).
 */

interface PayablesListProps {
  payables?: Payables;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  /** Mostra de que espaço é cada conta — só faz sentido na camada pessoal. */
  showWorkspace?: boolean;
}

type Grupo = { chave: string; titulo: string; itens: PayableEntry[] };

function agrupa(entries: PayableEntry[]): Grupo[] {
  const vencidas = entries.filter((e) => e.is_overdue);
  const restantes = entries.filter((e) => !e.is_overdue);
  return [
    { chave: 'overdue', titulo: 'Vencidas', itens: vencidas },
    { chave: 'aberto', titulo: 'A vencer', itens: restantes },
  ].filter((g) => g.itens.length > 0);
}

export function PayablesList({
  payables,
  isLoading,
  isError,
  onRetry,
  showWorkspace = false,
}: PayablesListProps) {
  const { settle, isSettling } = useSettlePayables();
  const [selecionadas, setSelecionadas] = React.useState<number[]>([]);
  const [pagoEm, setPagoEm] = React.useState(todayLocalISO);

  const entries = React.useMemo(() => payables?.entries ?? [], [payables]);
  const moeda = payables?.currency ?? 'BRL';
  const fmt = (v: unknown) => formatMoney(Number(v ?? 0), { currency: moeda });

  // O espaço de cada conta selecionada: a escrita é POR espaço, e a lista global
  // mistura casas. Sem este mapa, marcar duas contas de casas diferentes de uma
  // vez mandaria as duas para a rota de uma só — que responderia 200 com
  // `updated: 0` e deixaria as linhas na tela, sem erro nenhum.
  const porEspaco = React.useMemo(() => {
    const mapa = new Map<number, number[]>();
    for (const id of selecionadas) {
      const linha = entries.find((e) => e.transaction_id === id);
      if (!linha) continue;
      mapa.set(linha.workspace_id, [...(mapa.get(linha.workspace_id) ?? []), id]);
    }
    return mapa;
  }, [selecionadas, entries]);

  // Some da seleção o que saiu da lista (foi pago em outra aba, por exemplo):
  // manter o id selecionado deixaria o rodapé prometendo pagar algo que já não
  // está ali.
  React.useEffect(() => {
    setSelecionadas((atual) =>
      atual.filter((id) => entries.some((e) => e.transaction_id === id)),
    );
  }, [entries]);

  const alterna = (id: number) =>
    setSelecionadas((atual) =>
      atual.includes(id) ? atual.filter((x) => x !== id) : [...atual, id],
    );

  const confirmar = async () => {
    try {
      let total = 0;
      for (const [workspaceId, ids] of porEspaco) {
        const r = await settle({
          workspaceId,
          transactionIds: ids,
          settled: true,
          settledOn: pagoEm,
        });
        total += r.updated;
      }
      setSelecionadas([]);
      toast.success(
        total === 1 ? 'Conta marcada como paga.' : `${total} contas marcadas como pagas.`,
      );
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível marcar como paga.'));
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (isError) {
    // Sem este ramo, a falha da API vira "você não deve nada" — uma resposta
    // financeira, e falsa. Mesma regra do Seu mês (ERR-001).
    return (
      <ErrorState
        message="Não foi possível carregar as suas contas a pagar."
        onRetry={onRetry}
      />
    );
  }

  const grupos = agrupa(entries);
  const vencido = Number(payables?.overdue_total ?? 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3">
        <StatTile
          label="Total em aberto"
          value={Number(payables?.total ?? 0)}
          kind="neutral"
          icon={Wallet}
          currency={moeda}
          hint="Sai do caixa quando você marcar como pago"
        />
        <StatTile
          label="Vencido"
          value={vencido}
          kind={vencido > 0 ? 'expense' : 'neutral'}
          icon={AlertTriangle}
          currency={moeda}
          hint={vencido > 0 ? 'Pague o quanto antes' : 'Nada em atraso'}
        />
        <StatTile
          label="A vencer neste mês"
          value={Number(payables?.due_this_month_total ?? 0)}
          kind="neutral"
          icon={CalendarClock}
          currency={moeda}
        />
      </div>

      <ExcludedForeignNotice
        count={payables?.excluded_foreign_count}
        baseCurrency={moeda}
      />

      {entries.length === 0 ? (
        <EmptyState
          icon={CheckCircle2}
          title="Nenhuma conta em aberto"
          description="Boletos, Pix e transferências que ainda não foram pagos aparecem aqui."
        />
      ) : (
        <div className="space-y-6">
          {grupos.map((grupo) => (
            <section key={grupo.chave} className="rounded-xl border border-border bg-card">
              <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
                <h2 className="text-base font-semibold text-foreground">{grupo.titulo}</h2>
                <span className="text-sm text-muted-foreground">
                  {grupo.itens.length} {grupo.itens.length === 1 ? 'conta' : 'contas'}
                </span>
              </div>
              <ul className="divide-y divide-border">
                {grupo.itens.map((item) => {
                  const marcada = selecionadas.includes(item.transaction_id);
                  const rotulo = `${item.title} — ${fmt(item.converted_amount ?? item.amount)}`;
                  return (
                    <li
                      key={item.transaction_id}
                      className="flex items-start gap-3 px-4 py-3"
                    >
                      {/* `<input type=checkbox>` nativo: a lista é uma fila de
                          seleção múltipla, e o alvo de toque de 20px com rótulo
                          associado é o que o leitor de tela e o dedo esperam. */}
                      <input
                        type="checkbox"
                        id={`pagar-${item.transaction_id}`}
                        checked={marcada}
                        onChange={() => alterna(item.transaction_id)}
                        aria-label={`Marcar ${rotulo} como paga`}
                        className="mt-1 h-5 w-5 shrink-0 rounded border-border accent-primary"
                      />
                      <label
                        htmlFor={`pagar-${item.transaction_id}`}
                        className="flex min-w-0 flex-1 cursor-pointer items-start justify-between gap-3"
                      >
                        <span className="min-w-0">
                          <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                            <span className="min-w-0 break-words text-sm font-medium text-foreground">
                              {item.title}
                            </span>
                            {item.is_overdue && (
                              <StatusPill tone="danger">vencida</StatusPill>
                            )}
                            {item.recurring_expense_id != null && (
                              <StatusPill tone="neutral">
                                <Repeat className="h-3 w-3" aria-hidden="true" /> fixa
                              </StatusPill>
                            )}
                          </span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            {[
                              /* parseApiDay: vencimento é DIA de calendário, não
                                 instante — parseApiDate voltaria um dia. */
                              `vence ${parseApiDay(item.due_date).toLocaleDateString('pt-BR')}`,
                              showWorkspace ? item.workspace_name : null,
                              paymentMethodLabel(item.payment_method),
                              item.installments_of
                                ? `parcela ${item.installment_no}/${item.installments_of}`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        </span>
                        <span className="shrink-0 tabular-nums text-sm font-medium text-foreground">
                          {/* O valor NA MOEDA DE DESTINO quando há cotação; o
                              original quando não há. Omitir a linha sem cotação
                              seria pior aqui do que em qualquer outra tela — a
                              conta continua sendo devida (ADR 0006). */}
                          {item.converted_amount != null
                            ? fmt(item.converted_amount)
                            : formatMoney(Number(item.amount), { currency: item.currency })}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}

      {selecionadas.length > 0 && (
        /* Barra fixa no rodapé: a lista pode ser longa, e o botão de confirmar
           não pode depender de rolar até o fim para ser alcançado. */
        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-between gap-3 border-t border-border bg-card px-4 py-3 shadow-lg sm:mx-0 sm:rounded-xl sm:border">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground">
              {selecionadas.length}{' '}
              {selecionadas.length === 1 ? 'conta selecionada' : 'contas selecionadas'}
            </p>
            <p className="text-xs text-muted-foreground">
              O valor sai do caixa no mês da data informada.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="pago-em" className="text-xs text-muted-foreground">
              Pago em
            </label>
            <input
              id="pago-em"
              type="date"
              value={pagoEm}
              onChange={(e) => setPagoEm(e.target.value)}
              className={`${nativeSelectClass} w-auto`}
            />
            <Button onClick={confirmar} pending={isSettling} className="font-medium">
              Marcar como paga
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
