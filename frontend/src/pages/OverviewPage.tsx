import { Link } from 'react-router-dom';
import {
  ArrowRight,
  ArrowDownLeft,
  ArrowUpRight,
  Receipt,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile } from '@/components/ui/stat-tile';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { useOverview, useMyActivity } from '@/hooks/use-overview';
import { useAuth } from '@/hooks/use-auth';
import { useMonthParam } from '@/hooks/use-month-param';
import { formatMoney } from '@/lib/money';
import { parseApiDate } from '@/lib/date';

/**
 * Início GLOBAL e pessoal (ADR 0020).
 *
 * O Início antigo era a dashboard de UM workspace disfarçada de tela pessoal: lia
 * o `currentWorkspaceId` do navegador, mostrava "minha parte" ao lado do total da
 * casa e não somava nada de ninguém. Quem tem duas casas não tinha onde perguntar
 * "como está o meu mês".
 *
 * Os números aparecem separados porque são perguntas diferentes — e o app inteiro
 * chamava tudo de "gasto":
 *
 * - **Consumo**: a minha parte das despesas (competência).
 * - **Adiantado nos lançamentos**: o que assumi das despesas. Chamava-se "Saída
 *   de caixa" e não era caixa (ADR 0022) — a compra no cartão entrava aqui com o
 *   dinheiro ainda na conta.
 * - **Caixa**: o dinheiro que de fato entrou e saiu, com pagamento de fatura,
 *   acerto e parcela de financiamento.
 * - **A pagar / a receber**: a diferença, por casa.
 * - **Resultado do mês**: renda − consumo. (Era o que se chamava "Seu saldo",
 *   que sugeria saldo bancário e nunca foi isso.)
 */
export function OverviewPage() {
  const { user } = useAuth();
  // Mês na URL, como no resto do app. Estava fixo em `currentMonthLocal()`: a
  // única tela que soma todos os workspaces não deixava olhar o mês passado, e
  // "como foi meu mês" só valia para o mês corrente.
  const [month, setMonth] = useMonthParam();
  const { overview, isLoading, isError, refetch } = useOverview(month);
  const { activity, isLoading: activityLoading } = useMyActivity(8);

  const firstName = user?.name?.split(' ')[0];
  const n = (v: unknown) => Number(v ?? 0);
  const moeda = overview?.currency ?? 'BRL';
  const fmt = (v: unknown) => formatMoney(n(v), { currency: moeda });

  const result = n(overview?.result);
  const netCash = n(overview?.net_cash);
  const aPagar = n(overview?.to_pay);
  const aReceber = n(overview?.to_receive);

  // Detalhamento da saída: só as linhas com valor, para o quadro não virar uma
  // lista de zeros em quem não tem cartão nem financiamento.
  // `origem` leva ao extrato já filtrado: o número deixa de ser um total que o
  // usuário tem de acreditar e passa a ter as linhas por trás dele, a um clique.
  const quebra = overview?.cash_out_breakdown;
  const entradas = overview?.cash_in_breakdown;
  type LinhaCaixa = { rotulo: string; valor: number; origem: string };
  const saidas: LinhaCaixa[] = [
    { rotulo: 'Lançamentos à vista', valor: n(quebra?.transactions), origem: 'transaction' },
    { rotulo: 'Faturas de cartão pagas', valor: n(quebra?.statement_payments), origem: 'statement_payment' },
    { rotulo: 'Acertos enviados', valor: n(quebra?.settlements_sent), origem: 'settlement_sent' },
    { rotulo: 'Parcelas de financiamento', valor: n(quebra?.financing_installments), origem: 'financing_installment' },
    { rotulo: 'Rendas recebidas', valor: n(entradas?.income), origem: 'income' },
    { rotulo: 'Acertos recebidos', valor: n(entradas?.settlements_received), origem: 'settlement_received' },
  ].filter((l) => l.valor !== 0);

  return (
    <div className="space-y-6">
      {/* "Seu mês" e não "Início": o item de navegação tem esse nome, e um
          título que não bate com o item por onde se chegou faz duvidar de que a
          página é a certa. Sem `scope`: o título já diz de quem é o mês, e a
          pílula "Pessoal" ao lado dele seria a mesma informação duas vezes. */}
      <PageHeader
        title="Seu mês"
        subtitle={
          firstName
            ? `Olá, ${firstName} — seu mês somando todos os seus espaços.`
            : 'Seu mês somando todos os seus espaços.'
        }
        period={<PeriodPicker value={month} onChange={setMonth} />}
      />

      {isLoading ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-56 w-full" />
        </div>
      ) : isError ? (
        // Sem este ramo, a falha da API virava um mês inteiro de zeros: os
        // `StatTile` abaixo leem `n(overview?.x)`, que é `Number(undefined ?? 0)`.
        // "Renda R$ 0,00, Consumo R$ 0,00" é uma resposta, não um erro — e o
        // usuário não teria como saber que ela não foi calculada (regra ERR-001).
        <ErrorState
          message="Não foi possível carregar a sua visão do mês."
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <StatTile
              label="Renda"
              value={n(overview?.income)}
              kind="income"
              icon={TrendingUp}
              currency={moeda}
              // "em todos os espaços" era impreciso — renda não pertence a
              // espaço nenhum (ADR 0021) — e repetia o subtítulo da página,
              // 40px acima, fazendo a Renda parecer o único número consolidado.
              hint="Suas entradas do mês — renda é pessoal, não pertence a um espaço"
            />
            <StatTile
              label="Consumo"
              value={n(overview?.consumption)}
              kind="expense"
              icon={Receipt}
              currency={moeda}
              hint="Sua parte das despesas"
            />
            {/* `neutral`, não `expense`: com `kind="expense"` o MoneyText
                imprime o valor NEGATIVO e em vermelho, ao lado do Consumo e com
                a mesma cara. O resultado é renda − consumo, e "Adiantado" não
                entra nessa conta — mas a tela sugeria que deveria, e um
                adiantamento maior que o consumo (o normal para quem paga a
                conta do grupo) parecia um rombo. O mesmo número já aparece
                neutro na lista por workspace, logo abaixo. */}
            <StatTile
              label="Adiantado nos lançamentos"
              value={n(overview?.paid_in_transactions)}
              kind="neutral"
              icon={ArrowUpRight}
              currency={moeda}
              hint="Valor que você assumiu nos lançamentos; não é gasto nem saída de caixa"
            />
            <StatTile
              label="Resultado do mês"
              value={result}
              kind={result >= 0 ? 'income' : 'expense'}
              icon={Wallet}
              currency={moeda}
              hint="Renda menos consumo"
            />
          </div>

          {/* CAIXA — dinheiro que se moveu de verdade (ADR 0022). Separado dos
              números de competência acima porque responde outra pergunta: a
              compra no cartão é consumo em julho e caixa só quando a fatura é
              paga. O detalhamento existe para o total ser conferível — sem ele,
              "saiu R$ 4.200" não diz se a fatura entrou na conta. */}
          <section className="rounded-xl border border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">Caixa do mês</h2>
              <p className="text-sm text-muted-foreground">
                O dinheiro que entrou e saiu de fato — fatura paga, acerto e parcela
                de financiamento entram aqui, compra no cartão só quando a fatura é paga.
              </p>
            </div>
            <div className="grid gap-4 p-4 sm:grid-cols-3">
              <StatTile
                label="Entrou"
                value={n(overview?.cash_in)}
                kind="income"
                icon={ArrowDownLeft}
                currency={moeda}
              />
              <StatTile
                label="Saiu"
                value={n(overview?.cash_out)}
                kind="expense"
                icon={ArrowUpRight}
                currency={moeda}
              />
              <StatTile
                label="Saldo do movimento"
                value={netCash}
                kind={netCash >= 0 ? 'income' : 'expense'}
                icon={Wallet}
                currency={moeda}
              />
            </div>
            {/* O <Link> fica DENTRO do <dd>, nunca entre o <dl> e o par.
                Envolvendo <dt>/<dd> ele os desqualificava como filhos da lista
                de definição — o Axe acusava `definition-list` e `dlitem`, e um
                leitor de tela deixava de anunciar "rótulo/valor".

                O alvo de clique é estendido por `after:inset-0` sobre a linha
                `relative` (stretched link), e não pelo <dd>: o <dd> não tem
                `flex-1` dentro de um `justify-between`, então ele encolhe ao
                número — a área clicável media ~53px de uma linha de ~475px,
                enquanto o `hover:bg-muted` realçava a faixa toda e a legenda
                abaixo prometia "clique em uma linha". Prometia o que não fazia.

                `aria-labelledby` cita os DOIS ids: ele SUBSTITUI o conteúdo como
                nome acessível, então citar só o rótulo anunciava "Lançamentos à
                vista" e deixava o valor de fora — justamente o dado da linha. */}
            <dl className="grid gap-x-6 gap-y-1 border-t border-border px-4 py-3 text-sm sm:grid-cols-2">
              {saidas.map(({ rotulo, valor, origem }) => (
                <div
                  key={rotulo}
                  className="relative -mx-2 flex items-center justify-between gap-4 rounded-md px-2 py-1 hover:bg-muted focus-within:bg-muted"
                >
                  <dt id={`saida-${origem}`} className="text-muted-foreground">
                    {rotulo}
                  </dt>
                  <dd id={`valor-${origem}`} className="tabular-nums text-foreground">
                    <Link
                      to={`/me/ledger?month=${month}&source=${origem}`}
                      aria-labelledby={`saida-${origem} valor-${origem}`}
                      className="block rounded-sm after:absolute after:inset-0 after:rounded-md after:content-[''] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {fmt(valor)}
                    </Link>
                  </dd>
                </div>
              ))}
            </dl>
            <p className="px-4 pb-3 text-xs text-muted-foreground">
              Clique em uma linha para ver os movimentos que a compõem.
            </p>
          </section>

          {(aPagar > 0 || aReceber > 0) && (
            <div className="grid grid-cols-2 gap-3 sm:gap-4">
              <StatTile
                label="A pagar"
                value={aPagar}
                kind="expense"
                icon={ArrowUpRight}
                currency={moeda}
              />
              <StatTile
                label="A receber"
                value={aReceber}
                kind="income"
                icon={ArrowDownLeft}
                currency={moeda}
              />
            </div>
          )}

          <ExcludedForeignNotice
            count={overview?.excluded_foreign_count}
            baseCurrency={moeda}
          />

          {/* Por workspace — NUNCA somado entre eles: dever numa casa e ter a
              receber noutra envolve pessoas e acordos diferentes. */}
          <section className="rounded-xl border border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">Por espaço</h2>
              <p className="text-sm text-muted-foreground">
                Acertos ficam separados por espaço — não se compensam entre eles.
              </p>
            </div>
            <div className="divide-y divide-border">
              {(overview?.by_workspace ?? []).length === 0 ? (
                <div className="p-4">
                  <EmptyState
                    icon={Receipt}
                    title="Nenhum movimento neste mês"
                    description="Assim que houver lançamentos, cada espaço aparece aqui."
                  />
                </div>
              ) : (
                overview?.by_workspace.map((w) => (
                  <Link
                    key={w.workspace_id}
                    to={`/w/${w.workspace_id}`}
                    className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/50"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-foreground">{w.workspace_name}</p>
                      <p className="text-sm text-muted-foreground">
                        Consumo {fmt(w.consumption)} · Adiantado{' '}
                        {fmt(w.paid_in_transactions)}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3 text-sm">
                      {n(w.to_pay) > 0 && (
                        <span className="text-expense">a pagar {fmt(w.to_pay)}</span>
                      )}
                      {n(w.to_receive) > 0 && (
                        <span className="text-income">a receber {fmt(w.to_receive)}</span>
                      )}
                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </Link>
                ))
              )}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">
                Onde você está envolvido
              </h2>
            </div>
            <div className="divide-y divide-border">
              {activityLoading ? (
                <div className="space-y-2 p-3">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-10" />
                  ))}
                </div>
              ) : activity.length === 0 ? (
                <div className="p-4">
                  <EmptyState
                    icon={Receipt}
                    title="Nada por aqui ainda"
                    description="Lançamentos em que você participa aparecem nesta lista."
                  />
                </div>
              ) : (
                activity.map((t) => (
                  <div key={t.id} className="flex items-center justify-between gap-4 px-4 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{t.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {t.workspace_name} ·{' '}
                        {parseApiDate(t.transaction_date).toLocaleDateString('pt-BR')}
                      </p>
                    </div>
                    {/* A PARTE da pessoa, não o total da despesa. Numa seção
                        chamada "Onde você está envolvido", mostrar o valor cheio
                        fazia o jantar de 200 rateado 50/50 aparecer como 200 para
                        quem consumiu 100. O total vem abaixo, como referência.
                        Sem split (entrou por ter criado ou pago), `my_share` é
                        nulo e só o total faz sentido. */}
                    <div className="shrink-0 text-right">
                      <span className="block text-sm tabular-nums text-foreground">
                        {formatMoney(n(t.my_share ?? t.total_amount), {
                          currency: t.currency,
                        })}
                      </span>
                      {t.my_share != null && n(t.my_share) !== n(t.total_amount) && (
                        <span className="block text-xs tabular-nums text-muted-foreground">
                          de {formatMoney(n(t.total_amount), { currency: t.currency })}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
