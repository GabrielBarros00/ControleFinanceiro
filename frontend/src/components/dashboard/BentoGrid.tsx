import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CreditCard, DollarSign, Users, Plus } from 'lucide-react';
import { TransactionHistory } from './TransactionHistory';
import { Button } from "@/components/ui/button";
import { useReports } from '@/hooks/use-reports';
import { useAuth } from '@/hooks/use-auth';
import { useWorkspaces } from '@/hooks/use-workspaces';

interface BentoGridProps {
  onNewTransaction: () => void;
}

export function BentoGrid({ onNewTransaction }: BentoGridProps) {
  const { data } = useReports();
  const { user } = useAuth();
  const { currentWorkspace } = useWorkspaces();

  const summary = data?.current_summary || { total_expenses: 0, total_income: 0, net_savings: 0, my_expenses: 0, my_income: 0 };
  // Destaque = a sua parte (splits); sublinha = total da casa/workspace
  const myIncome = Number(summary.my_income ?? 0);
  const myExpenses = Number(summary.my_expenses ?? 0);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-card border-border shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Sua Receita</CardTitle>
            <DollarSign className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-black text-emerald-500">R$ {myIncome.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</div>
            <p className="text-[10px] text-muted-foreground mt-1">Casa: R$ {Number(summary.total_income).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Sua Despesa</CardTitle>
            <CreditCard className="h-4 w-4 text-destructive" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-black text-destructive">R$ {myExpenses.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</div>
            <p className="text-[10px] text-muted-foreground mt-1">Casa: R$ {Number(summary.total_expenses).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Membro</CardTitle>
            <Users className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-black text-foreground truncate">{user?.name.split(' ')[0]}</div>
            <p className="text-[10px] text-muted-foreground mt-1 truncate">
              Logado em {currentWorkspace?.name ?? 'workspace'}
            </p>
          </CardContent>
        </Card>

        <Card
          onClick={onNewTransaction}
          className="bg-primary text-primary-foreground shadow-lg shadow-primary/20 border-none group cursor-pointer overflow-hidden relative"
        >
          <div className="absolute inset-0 bg-white/10 translate-y-full group-hover:translate-y-0 transition-transform duration-300" />
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 relative z-10">
            <CardTitle className="text-[10px] font-bold uppercase tracking-wider">Novo Registro</CardTitle>
            <Plus className="h-4 w-4" />
          </CardHeader>
          <CardContent className="flex h-[80px] items-center justify-center relative z-10">
            <Button variant="secondary" onClick={onNewTransaction} className="w-full font-black shadow-sm uppercase text-[10px] tracking-tighter">
              + Adicionar Transação
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-1">
        <TransactionHistory />
      </div>
    </div>
  );
}
