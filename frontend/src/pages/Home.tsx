import { Link } from 'react-router-dom';
import { Plus, ArrowRight, Receipt, TrendingDown, Wallet, HandCoins } from 'lucide-react';
import { useReports } from '@/hooks/use-reports';
import { useAnalytics } from '@/hooks/use-analytics';
import { useTransactions } from '@/hooks/use-transactions';
import { useNewTxStore, useTxDetailStore } from '@/stores';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { StatTile } from '@/components/ui/stat-tile';
import { HeroBalance } from '@/components/dashboard/HeroBalance';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { TransactionLedger } from '@/components/money/TransactionLedger';
import { formatMoney, sameMoney } from '@/lib/money';
import { currentMonthLocal } from '@/lib/date';


function daysLeftInMonth(): number {
  const now = new Date();
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return last - now.getDate();
}

/**
 * Painel DESTE workspace — e só dele (ADR 0021).
 *
 * O que saiu daqui foi o número mais enganoso do app. "Sua receita" era a renda
 * GLOBAL da pessoa e "Resultado do mês" era essa renda menos a despesa DESTE
 * workspace: com salário de 9.000 e 1.150 de despesa na Casa, o painel anunciava
 * 7.850 de sobra, ignorando os 500 gastos noutro workspace — e num terceiro
 * workspace o mesmo salário daria uma terceira "sobra", todas maiores que a real.
 *
 * Renda e resultado agora existem num lugar só, a Visão global (`/overview`),
 * onde o denominador é o consumo somado de todos os workspaces. Aqui ficam os
 * números que dependem só desta casa — e o par que faltava: quanto eu CONSUMI
 * contra quanto eu PAGUEI, cuja diferença é o acerto.
 */
export function Home() {
  // Mês LOCAL explícito nas três consultas: sem ele, resumo e previsão usavam
  // o date.today() do servidor e divergiam do extrato na virada do mês.
  const month = currentMonthLocal();
  const baseCurrency = useBaseCurrency();
  const { data: reports, isLoading: reportsLoading } = useReports(month);
  const { forecast, isLoading: forecastLoading } = useAnalytics(month);
  const { transactions, isLoading: txLoading } = useTransactions({ page: 1, limit: 6, month });
  // Links do painel apontam para ESTE workspace, com o id na URL. Eles iam para
  // `/transactions` e `/reports` — as rotas legadas, que redirecionam para a
  // "última casa aberta" e perdiam a query string pelo caminho.
  const workspaceId = useWorkspaceId();
  const base = `/w/${workspaceId}`;
  const setNewTxOpen = useNewTxStore((s) => s.setOpen);
  // O Início era a tela que renderizava o ledger SEM `canWrite`, e o default
  // permissivo mostrava editar/excluir a um viewer. `isLoading` importa: o hook
  // devolve 'viewer' enquanto carrega, então esperar evita o piscar ao contrário
  // (botão habilitado por um instante para quem não pode escrever).
  const { canWrite, isLoading: roleLoading } = useWorkspaceRole();
  const openDetail = useTxDetailStore((s) => s.open);

  const loading = reportsLoading || forecastLoading || roleLoading;
  const summary = reports?.current_summary;
  const myExpenses = Number(summary?.my_expenses ?? 0);
  const paidByMe = Number(summary?.paid_by_me ?? 0);
  // Positivo = adiantei e tenho a receber; negativo = devo. Vem do backend
  // pronto: recalcular aqui seria uma segunda definição esperando divergir.
  const myBalance = Number(summary?.my_balance ?? 0);
  // Números da CASA vêm `null` para quem não tem acesso financeiro completo
  // (ADR 0018). `?? 0` aqui era um erro esperando acontecer: a dica renderizaria
  // "Casa R$ 0,00" ao lado da despesa real do membro — um número inventado na
  // tela. `null` tem de continuar `null` até a decisão de exibir.
  const houseExpenses = summary?.total_expenses == null ? null : Number(summary.total_expenses);
  // Meta PESSOAL — o card mostra "sua parte", então o orçamento ao lado tem
  // que ser o seu. Com `total_budget` (a meta da CASA) a barra marcava ~50% num
  // workspace de duas pessoas com rateio igual, enquanto Relatórios, que compara
  // espaço com espaço, mostrava 100% para o MESMO orçamento.
  const budget = parseFloat(forecast?.my_budget ?? '0') || 0;
  return (
    <div className="space-y-6">
      {/* "Painel" + pílula com o nome do espaço, e não o nome como TÍTULO.
          O título antes era `Workspace · {nome}`, que repetia o jargão; trocá-lo
          pelo nome puro dava uma página cujo cabeçalho não batia com o item de
          navegação por onde se chegou ("Painel"). A pílula carrega o nome e
          ainda diz o que ele é — o escopo — em vez de deixar adivinhar. */}
      <PageHeader
        title="Painel"
        scope="workspace"
        subtitle="Somente este espaço. Sua renda e seu resultado ficam em Pessoal › Seu mês."
        action={
          canWrite ? (
            <Button onClick={() => setNewTxOpen(true)} className="gap-2">
              <Plus className="h-4 w-4" /> Nova despesa
            </Button>
          ) : undefined
        }
      />

      {loading ? (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-3">
            <Skeleton className="h-44 lg:col-span-2" />
            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <>
          {/*
            Empilhado, e não duas colunas.

            Era `lg:grid-cols-3` com o herói ocupando duas colunas e três tiles
            na terceira. O herói tem 170px de altura e a pilha de tiles 362px —
            então sobrava um buraco medido de **700×216px** embaixo do herói, a
            maior área ociosa do produto, bem no meio da tela mais visitada do
            espaço. E o custo não era só estético: a 1366×768 só DUAS linhas de
            "Últimos lançamentos" cabiam acima da dobra.

            Em fila, os três tiles somam 110px em vez de 362px. O bloco todo cai
            de 362px para ~296px e o buraco deixa de existir.
          */}
          <div className="space-y-4">
            <HeroBalance
              // O protagonista aqui é o consumo DESTA casa contra a meta — não
              // uma "sobra", que depende de renda e por isso é da Visão global.
              label="Sua parte no mês"
              hero={myExpenses}
              heroKind="expense"
              spent={myExpenses}
              budget={budget}
              daysLeft={daysLeftInMonth()}
              currency={baseCurrency}
              budgetHref={`${base}/reports?month=${month}`}
            />
            <div className="grid grid-cols-2 gap-3 sm:gap-4 sm:grid-cols-3">
              {/* Gasto da CASA — o número que só existe com acesso financeiro
                  completo (ADR 0018). Sem ele o tile some, em vez de mostrar
                  "R$ 0,00", que seria um número inventado ao lado da sua parte.
                  Repetir "Sua parte" aqui, ao lado do mesmo valor no hero, era a
                  redundância que a auditoria apontou. */}
              {houseExpenses != null && (
                <StatTile
                  label="Gasto do espaço"
                  value={houseExpenses}
                  kind="expense"
                  icon={TrendingDown}
                  currency={baseCurrency}
                  hint={
                    sameMoney(myExpenses, houseExpenses)
                      ? 'Tudo neste mês foi seu'
                      : `Sua parte: ${formatMoney(myExpenses, { currency: baseCurrency })}`
                  }
                />
              )}
              {/* "Pago por você" sugeria dinheiro que saiu da conta, e não é
                  isso: a compra no cartão entra aqui no mês do lançamento, com o
                  dinheiro ainda no banco. Caixa de verdade é global e está na
                  Visão global (ADR 0022) — aqui o número certo é o que a pessoa
                  ASSUMIU desta casa, que é o que fecha o acerto. */}
              <StatTile
                label="Adiantado por você"
                value={paidByMe}
                kind="neutral"
                icon={Wallet}
                currency={baseCurrency}
                hint="O que você assumiu das despesas deste espaço"
              />
              <StatTile
                // Nome pelo que é: a diferença entre o que consumi e o que
                // assumi NESTE workspace, já descontados os acertos do mês.
                // Nunca compensada com outros — dever na casa e ter a receber na
                // viagem envolve pessoas e acordos diferentes.
                label={myBalance >= 0 ? 'Você tem a receber' : 'Você deve'}
                value={Math.abs(myBalance)}
                kind={myBalance >= 0 ? 'income' : 'expense'}
                icon={HandCoins}
                currency={baseCurrency}
                hint="Já descontados os acertos deste mês"
              />
            </div>
            <ExcludedForeignNotice
              count={summary?.excluded_foreign_count}
              baseCurrency={baseCurrency}
            />
          </div>

          <section className="rounded-xl border border-border bg-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">Últimos lançamentos</h2>
              <Link
                to={`${base}/transactions`}
                className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"
              >
                Ver todos <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="p-2 sm:p-3">
              {txLoading ? (
                <div className="space-y-2 p-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-12" />
                  ))}
                </div>
              ) : transactions.length === 0 ? (
                <EmptyState
                  icon={Receipt}
                  title="Nenhum lançamento ainda"
                  description="Registre o primeiro gasto deste espaço para começar a acompanhar o mês."
                  action={
                    canWrite ? (
                      <Button onClick={() => setNewTxOpen(true)} className="gap-2">
                        <Plus className="h-4 w-4" /> Nova despesa
                      </Button>
                    ) : undefined
                  }
                />
              ) : (
                <TransactionLedger
                  transactions={transactions}
                  showDayTotals={false}
                  canWrite={canWrite}
                  onSelect={(tx) => openDetail(tx.id)}
                />
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
