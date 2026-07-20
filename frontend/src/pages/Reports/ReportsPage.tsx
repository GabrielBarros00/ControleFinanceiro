import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer, 
  PieChart, 
  Pie, 
  Cell,
  LineChart,
  Line
} from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BarChart3, TrendingUp, PieChart as PieChartIcon } from 'lucide-react';

import { useReports } from '@/hooks/use-reports';
import { Skeleton } from "@/components/ui/skeleton";
import { BudgetPanel } from './BudgetPanel';

const COLORS = ['oklch(0.488 0.243 264.376)', 'oklch(0.696 0.17 162.48)', 'oklch(0.769 0.188 70.08)', 'oklch(0.627 0.265 303.9)', 'oklch(0.645 0.246 16.439)'];

export function ReportsPage() {
  const { data, isLoading, isError } = useReports();

  if (isLoading) {
    return (
      <div className="space-y-8">
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-24 bg-card border-border" />)}
        </div>
        <Skeleton className="h-[400px] w-full bg-card border-border" />
      </div>
    );
  }

  // Estado de erro explícito (ERR-001): falha não pode virar "tudo zero"
  if (isError || !data) {
    return (
      <div className="p-12 text-center rounded-xl bg-destructive/10 border border-destructive/20">
        <p className="text-sm font-bold text-destructive">Não foi possível carregar os relatórios.</p>
        <p className="text-xs text-muted-foreground mt-1">Verifique a conexão e tente novamente.</p>
      </div>
    );
  }

  const monthlyData = data?.monthly_history || [];
  const currentSummary = data?.current_summary || { total_expenses: 0, total_income: 0, net_savings: 0, categories: [] };
  const categoryData = currentSummary.categories || [];

  return (
    <div className="space-y-8 animate-in fade-in duration-700">
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="bg-card border-border shadow-lg transition-all hover:shadow-xl group">
          <CardHeader className="pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Total Gasto (Mês)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-black text-foreground group-hover:text-primary transition-colors">
              R$ {currentSummary.total_expenses.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card border-border shadow-lg transition-all hover:shadow-xl group border-l-4 border-l-emerald-500">
          <CardHeader className="pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Receita Total (Mês)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-black text-foreground">
              R$ {currentSummary.total_income.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card border-border shadow-lg transition-all hover:shadow-xl group">
          <CardHeader className="pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Maior Categoria</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-black text-foreground capitalize">
              {categoryData.length > 0 ? [...categoryData].sort((a: { value: number }, b: { value: number }) => b.value - a.value)[0].name : 'Nenhuma'}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card border-border shadow-lg transition-all hover:shadow-xl group">
          <CardHeader className="pb-2">
            <CardTitle className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">Saldo Líquido</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-black ${currentSummary.net_savings >= 0 ? 'text-emerald-500' : 'text-destructive'}`}>
              R$ {currentSummary.net_savings.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="bg-card border border-border">
          <TabsTrigger value="overview" className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground font-bold">Visão Geral</TabsTrigger>
          <TabsTrigger value="categories" className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground font-bold">Categorias</TabsTrigger>
          <TabsTrigger value="trends" className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground font-bold">Fluxo</TabsTrigger>
          <TabsTrigger value="budget" className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground font-bold">Orçamento</TabsTrigger>
        </TabsList>

        <TabsContent value="budget" className="animate-in slide-in-from-bottom-4 duration-500">
          <BudgetPanel spentByCategory={categoryData} totalExpenses={currentSummary.total_expenses} />
        </TabsContent>
        
        <TabsContent value="overview" className="space-y-4 animate-in slide-in-from-bottom-4 duration-500">
          <Card className="bg-card border-border shadow-xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <BarChart3 className="h-5 w-5 text-primary" />
                Receitas vs Despesas
              </CardTitle>
              <CardDescription>Comparativo mensal dos últimos 6 meses.</CardDescription>
            </CardHeader>
            <CardContent className="h-[400px]">
              {monthlyData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis dataKey="name" stroke="oklch(0.556 0 0)" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke="oklch(0.556 0 0)" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `R$${value}`} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: 'oklch(0.165 0 0)', border: '1px solid oklch(0.205 0 0)', borderRadius: '12px' }}
                      itemStyle={{ color: 'oklch(0.985 0 0)', fontWeight: 'bold' }}
                    />
                    <Bar dataKey="income" fill="oklch(0.696 0.17 162.48)" radius={[4, 4, 0, 0]} name="Receita" />
                    <Bar dataKey="expenses" fill="oklch(0.488 0.243 264.376)" radius={[4, 4, 0, 0]} name="Despesa" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground italic">Sem dados suficientes para gerar o gráfico.</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="categories" className="animate-in slide-in-from-bottom-4 duration-500">
          <div className="grid gap-4 md:grid-cols-2">
            <Card className="bg-card border-border shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <PieChartIcon className="h-5 w-5 text-primary" />
                  Distribuição por Categoria
                </CardTitle>
              </CardHeader>
              <CardContent className="h-[350px]">
                {categoryData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={categoryData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={100}
                        paddingAngle={5}
                        dataKey="value"
                      >
                        {categoryData.map((_: { name: string; value: number }, index: number) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip 
                        contentStyle={{ backgroundColor: 'oklch(0.165 0 0)', border: '1px solid oklch(0.205 0 0)', borderRadius: '12px' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground italic">Nenhuma categoria registrada.</div>
                )}
              </CardContent>
            </Card>
            <Card className="bg-card border-border shadow-xl">
              <CardHeader>
                <CardTitle>Detalhamento de Gastos</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {categoryData.length > 0 ? categoryData.map((item: { name: string; value: number }, idx: number) => (
                    <div key={item.name} className="flex items-center justify-between p-2 rounded-lg hover:bg-accent/30 transition-colors">
                      <div className="flex items-center gap-3">
                        <div className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
                        <span className="text-sm font-medium">{item.name}</span>
                      </div>
                      <span className="text-sm font-black">R$ {item.value.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</span>
                    </div>
                  )) : (
                    <p className="text-center text-muted-foreground py-8">Comece a registrar gastos para ver os detalhes.</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="trends" className="animate-in slide-in-from-bottom-4 duration-500">
          <Card className="bg-card border-border shadow-xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-primary" />
                Histórico de Fluxo de Caixa
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[400px]">
               {monthlyData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis dataKey="name" stroke="oklch(0.556 0 0)" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke="oklch(0.556 0 0)" fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: 'oklch(0.165 0 0)', border: '1px solid oklch(0.205 0 0)', borderRadius: '12px' }}
                    />
                    <Line type="monotone" dataKey="income" stroke="oklch(0.696 0.17 162.48)" strokeWidth={3} dot={{ r: 6, strokeWidth: 2, fill: 'oklch(0.165 0 0)' }} name="Receita" />
                    <Line type="monotone" dataKey="expenses" stroke="oklch(0.488 0.243 264.376)" strokeWidth={3} dot={{ r: 6, strokeWidth: 2, fill: 'oklch(0.165 0 0)' }} name="Despesa" />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                 <div className="flex items-center justify-center h-full text-muted-foreground italic">Dê o primeiro passo registrando seus ganhos e gastos.</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
