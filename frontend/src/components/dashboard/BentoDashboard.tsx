import { useAnalytics } from '@/hooks/use-analytics';
import { useReports } from '@/hooks/use-reports';
import { BentoGrid } from './BentoGrid';
import { BudgetCard } from './BudgetCard';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, Target, Loader2, Wallet } from 'lucide-react';

export function BentoDashboard() {
  const { forecast, isLoading: isForecastLoading } = useAnalytics();
  const { data: reports, isLoading: isReportsLoading } = useReports();

  if (isForecastLoading || isReportsLoading) {
    return (
      <div className="h-[200px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const projectedTotal = forecast?.projected_eom || 0;
  const currentSpent = reports?.current_summary?.total_expenses || 0;
  const totalIncome = reports?.current_summary?.total_income || 0;
  
  const savingsRate = totalIncome > 0 ? ((totalIncome - currentSpent) / totalIncome) * 100 : 0;

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      {/* Analytics Summary */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-primary/5 border-primary/20 hover:bg-primary/10 transition-all cursor-default group">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-black uppercase tracking-widest text-primary">Previsão Fim do Mês</CardTitle>
            <TrendingUp className="h-4 w-4 text-primary group-hover:scale-125 transition-transform" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-black text-foreground">
              R$ {projectedTotal.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
            </div>
            <p className="text-[10px] font-bold text-muted-foreground mt-1">Gasto total estimado para este mês</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border hover:bg-accent/50 transition-all cursor-default group border-l-4 border-l-primary shadow-lg">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-black uppercase tracking-widest text-foreground">Gasto Real Atual</CardTitle>
            <Target className="h-4 w-4 text-primary group-hover:rotate-45 transition-transform" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-black text-foreground">
              R$ {currentSpent.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
            </div>
            <p className="text-[10px] font-bold text-muted-foreground mt-1">Valor já confirmado no sistema</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border hover:bg-accent/50 transition-all cursor-default group border-l-4 border-l-emerald-500 shadow-lg">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-black uppercase tracking-widest text-emerald-500">Saldo Disponível</CardTitle>
            <Wallet className="h-4 w-4 text-emerald-500 group-hover:scale-110 transition-transform" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-black text-emerald-500">
              R$ {(totalIncome - currentSpent).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
            </div>
            <p className="text-[10px] font-bold text-muted-foreground mt-1">
              {savingsRate > 0 ? `Economia de ${savingsRate.toFixed(1)}% da renda` : 'Você gastou mais do que ganhou'}
            </p>
          </CardContent>
        </Card>

        <BudgetCard
          totalBudget={parseFloat(forecast?.total_budget ?? '0') || 0}
          isOverBudget={!!forecast?.is_over_budget}
        />
      </div>

      <BentoGrid />
    </div>
  );
}
