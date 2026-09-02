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
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
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
  /**
   * De quem é este caixa. `'pessoa'` soma o que EU assumi (o valor do meu
   * `TransactionPayer`); `'espaco'` soma a conta inteira, de quem quer que vá
   * pagá-la.
   *
   * A distinção só existia no serviço. Na tela, as duas camadas mostravam o
   * mesmo "Sai do caixa quando você marcar como pago" — e no espaço isso é
   * falso para toda conta que outra pessoa vai pagar.
   */
  escopo?: 'pessoa' | 'espaco';
}

type Grupo = { chave: string; titulo: string; itens: PayableEntry[] };

function agrupa(entries: PayableEntry[]): Grupo[] {
  // "Vence hoje" sai do meio de "a vencer" (ADR 0034): é o grupo que pede ação
  // AGORA, e diluí-lo entre as contas do dia 28 fazia justamente a de hoje passar
  // despercebida. `due_state` vem do servidor porque o fuso do navegador dá outra
  // resposta perto da meia-noite.
  const vencidas = entries.filter((e) => e.due_state === 'overdue');
  const hoje = entries.filter((e) => e.due_state === 'due_today');
  const restantes = entries.filter(
    (e) => e.due_state !== 'overdue' && e.due_state !== 'due_today',
  );
  return [
    { chave: 'overdue', titulo: 'Vencidas', itens: vencidas },
    { chave: 'hoje', titulo: 'Vencem hoje', itens: hoje },
    { chave: 'aberto', titulo: 'A vencer', itens: restantes },
  ].filter((g) => g.itens.length > 0);
}

/** "vence em 3 dias" / "venceu há 2 dias" — calculado no SERVIDOR. */
function prazo(dias: number): string {
  if (dias === 0) return 'vence hoje';
  if (dias === 1) return 'vence amanhã';
  if (dias === -1) return 'venceu ontem';
  if (dias > 1) return `vence em ${dias} dias`;
  return `venceu há ${Math.abs(dias)} dias`;
}

export function PayablesList({
  payables,
  isLoading,
  isError,
  onRetry,
  showWorkspace = false,
  escopo = 'pessoa',
}: PayablesListProps) {
  const { settle, isSettling } = useSettlePayables();
  const [selecionadas, setSelecionadas] = React.useState<number[]>([]);
  const [pagoEm, setPagoEm] = React.useState(todayLocalISO);
  const [contaId, setContaId] = React.useState<number | null>(null);
  const { activeAccounts } = usePaymentAccounts();

  const entries = React.useMemo(() => payables?.entries ?? [], [payables]);
  const moeda = payables?.currency ?? 'BRL';
  // A conta tem de estar na MESMA moeda do lançamento (ADR 0034) — o saldo dela
  // soma os valores como estão, sem converter.
  const contasCompativeis = React.useMemo(
    () => activeAccounts.filter((c) => c.currency === moeda),
    [activeAccounts, moeda],
  );
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
          accountId: contaId ?? undefined,
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
          hint={
            escopo === 'pessoa'
              ? 'O que você assumiu e ainda não pagou'
              : 'A conta cheia do espaço — inclui o que outra pessoa vai pagar'
          }
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
                            {item.due_state === 'overdue' && (
                              <StatusPill tone="danger">
                                {prazo(item.days_until_due)}
                              </StatusPill>
                            )}
                            {item.due_state === 'due_today' && (
                              <StatusPill tone="warning">vence hoje</StatusPill>
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
                              item.due_state === 'upcoming' && item.days_until_due <= 7
                                ? prazo(item.days_until_due)
                                : null,
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

      {/* PRÓXIMAS: competência do mês que vem, vencimento dentro do horizonte
          (ADR 0034). Fora da lista principal e fora dos totais de propósito — os
          números do topo respondem "quanto ainda sai NESTE mês", e somar o
          aluguel do dia 1º do mês seguinte inflaria justamente o número que a
          pessoa usa para decidir se o dinheiro fecha.

          Sem caixa de seleção: pagar antecipadamente uma conta do mês que vem é
          possível pelo lançamento, e oferecê-lo aqui misturaria os dois meses na
          mesma ação. */}
      {(payables?.upcoming?.length ?? 0) > 0 && (
        <section className="rounded-xl border border-dashed border-border bg-card">
          <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">Próximas contas</h2>
              <p className="text-sm text-muted-foreground">
                Já conhecidas, mas do mês que vem — não entram nos totais acima.
              </p>
            </div>
            <span className="shrink-0 text-sm text-muted-foreground">
              {payables?.upcoming?.length}
            </span>
          </div>
          <ul className="divide-y divide-border">
            {(payables?.upcoming ?? []).map((item) => (
              <li
                key={item.transaction_id}
                className="flex items-start justify-between gap-3 px-4 py-3"
              >
                <span className="min-w-0">
                  <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="min-w-0 break-words text-sm font-medium text-foreground">
                      {item.title}
                    </span>
                    {item.recurring_expense_id != null && (
                      <StatusPill tone="neutral">
                        <Repeat className="h-3 w-3" aria-hidden="true" /> fixa
                      </StatusPill>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {[
                      `vence ${parseApiDay(item.due_date).toLocaleDateString('pt-BR')}`,
                      prazo(item.days_until_due),
                      showWorkspace ? item.workspace_name : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </span>
                <span className="shrink-0 tabular-nums text-sm text-muted-foreground">
                  {item.converted_amount != null
                    ? fmt(item.converted_amount)
                    : formatMoney(Number(item.amount), { currency: item.currency })}
                </span>
              </li>
            ))}
          </ul>
        </section>
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
            {/* De qual conta saiu (ADR 0034). É AQUI que a pessoa sabe disso, e
                até esta onda não havia onde dizer — o saldo por conta não tinha
                como se alimentar do gesto mais comum do app. Só contas na moeda
                do destino: o servidor recusa as outras, e oferecer uma opção que
                vira erro é pior do que não oferecer. */}
            {contasCompativeis.length > 0 && (
              <>
                <label htmlFor="conta-origem" className="text-xs text-muted-foreground">
                  Saiu de
                </label>
                <select
                  id="conta-origem"
                  value={contaId ?? ''}
                  onChange={(e) => setContaId(e.target.value ? Number(e.target.value) : null)}
                  className={`${nativeSelectClass} w-auto`}
                >
                  <option value="">Não informar</option>
                  {contasCompativeis.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </>
            )}
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
