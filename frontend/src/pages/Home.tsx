import { Link } from 'react-router-dom';
import { Plus, ArrowRight, Receipt, TrendingUp, TrendingDown, Wallet } from 'lucide-react';
import { useReports } from '@/hooks/use-reports';
import { useAnalytics } from '@/hooks/use-analytics';
import { useTransactions } from '@/hooks/use-transactions';
import { useAuth } from '@/hooks/use-auth';
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
import { TransactionLedger } from '@/components/money/TransactionLedger';
import { formatMoney, sameMoney } from '@/lib/money';
import { currentMonthLocal } from '@/lib/date';


function daysLeftInMonth(): number {
  const now = new Date();
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return last - now.getDate();
}

export function Home() {
  const { user } = useAuth();
  // Mês LOCAL explícito nas três consultas: sem ele, resumo e previsão usavam
  // o date.today() do servidor e divergiam do extrato na virada do mês.
  const month = currentMonthLocal();
  const baseCurrency = useBaseCurrency();
  const { data: reports, isLoading: reportsLoading } = useReports(month);
  const { forecast, isLoading: forecastLoading } = useAnalytics(month);
  const { transactions, isLoading: txLoading } = useTransactions({ page: 1, limit: 6, month });
  const setNewTxOpen = useNewTxStore((s) => s.setOpen);
  // O Início era a tela que renderizava o ledger SEM `canWrite`, e o default
  // permissivo mostrava editar/excluir a um viewer. `isLoading` importa: o hook
  // devolve 'viewer' enquanto carrega, então esperar evita o piscar ao contrário
  // (botão habilitado por um instante para quem não pode escrever).
  const { canWrite, isLoading: roleLoading } = useWorkspaceRole();
  const openDetail = useTxDetailStore((s) => s.open);

  const loading = reportsLoading || forecastLoading || roleLoading;
  const summary = reports?.current_summary;
  const myIncome = Number(summary?.my_income ?? 0);
  const myExpenses = Number(summary?.my_expenses ?? 0);
  // `my_net` vem do backend; recalcular aqui era uma segunda definição do
  // mesmo número esperando divergir.
  const myNet = summary?.my_net == null ? myIncome - myExpenses : Number(summary.my_net);
  // Números da CASA vêm `null` para quem não tem acesso financeiro completo
  // (ADR 0018). `?? 0` aqui era um erro esperando acontecer: a dica renderizaria
  // "Casa R$ 0,00" ao lado da despesa real do membro — um número inventado na
  // tela. `null` tem de continuar `null` até a decisão de exibir.
  const houseIncome = summary?.total_income == null ? null : Number(summary.total_income);
  const houseExpenses = summary?.total_expenses == null ? null : Number(summary.total_expenses);
  // Meta PESSOAL — o card mostra "sua despesa", então o orçamento ao lado tem
  // que ser o seu. Com `total_budget` (a meta da CASA) a barra marcava ~50% num
  // workspace de duas pessoas com rateio igual, enquanto Relatórios, que compara
  // casa com casa, mostrava 100% para o MESMO orçamento.
  const budget = parseFloat(forecast?.my_budget ?? '0') || 0;
  // "Casa X" só quando o total do workspace DIFERE da sua parte. Sozinho no
  // workspace (ou num mês em que tudo foi só seu) ele repetia o número de cima.
  // Sem acesso completo (house === null) a dica simplesmente não existe.
  const casa = (mine: number, house: number | null) =>
    house == null || sameMoney(mine, house)
      ? undefined
      : `Casa ${formatMoney(house, { currency: baseCurrency })}`;
  const firstName = user?.name?.split(' ')[0];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Início"
        subtitle={firstName ? `Olá, ${firstName} — aqui está seu mês.` : 'Aqui está seu mês.'}
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
          <div className="grid gap-6 lg:grid-cols-3 lg:items-start">
            <HeroBalance
              className="lg:col-span-2"
              net={myNet}
              spent={myExpenses}
              budget={budget}
              daysLeft={daysLeftInMonth()}
              currency={baseCurrency}
              budgetHref={`/reports?month=${month}`}
            />
            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
              <StatTile
                label="Sua receita"
                value={myIncome}
                kind="income"
                icon={TrendingUp}
                currency={baseCurrency}
                hint={casa(myIncome, houseIncome)}
              />
              <StatTile
                label="Sua despesa"
                value={myExpenses}
                kind="expense"
                icon={TrendingDown}
                currency={baseCurrency}
                hint={casa(myExpenses, houseExpenses)}
              />
              <StatTile
                // "Saldo" sugeria saldo bancário; é renda menos consumo do
                // PERÍODO (ADR 0020)
                label="Resultado do mês"
                value={myNet}
                kind={myNet >= 0 ? 'income' : 'expense'}
                icon={Wallet}
                currency={baseCurrency}
              />
              <ExcludedForeignNotice
                count={summary?.excluded_foreign_count}
                baseCurrency={baseCurrency}
              />
            </div>
          </div>

          <section className="rounded-xl border border-border bg-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">Últimos lançamentos</h2>
              <Link
                to="/transactions"
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
                  description="Registre seu primeiro gasto para começar a acompanhar seu mês."
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
