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
  const openDetail = useTxDetailStore((s) => s.open);

  const loading = reportsLoading || forecastLoading;
  const summary = reports?.current_summary;
  const myIncome = Number(summary?.my_income ?? 0);
  const myExpenses = Number(summary?.my_expenses ?? 0);
  const myNet = myIncome - myExpenses;
  const houseIncome = Number(summary?.total_income ?? 0);
  const houseExpenses = Number(summary?.total_expenses ?? 0);
  const budget = parseFloat(forecast?.total_budget ?? '0') || 0;
  // "Casa X" só quando o total do workspace DIFERE da sua parte. Sozinho no
  // workspace (ou num mês em que tudo foi só seu) ele repetia o número de cima.
  const casa = (mine: number, house: number) =>
    sameMoney(mine, house) ? undefined : `Casa ${formatMoney(house, { currency: baseCurrency })}`;
  const firstName = user?.name?.split(' ')[0];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Início"
        subtitle={firstName ? `Olá, ${firstName} — aqui está seu mês.` : 'Aqui está seu mês.'}
        action={
          <Button onClick={() => setNewTxOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" /> Nova despesa
          </Button>
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
                label="Seu saldo"
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
                    <Button onClick={() => setNewTxOpen(true)} className="gap-2">
                      <Plus className="h-4 w-4" /> Nova despesa
                    </Button>
                  }
                />
              ) : (
                <TransactionLedger transactions={transactions} showDayTotals={false} onSelect={(tx) => openDetail(tx.id)} />
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
