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
import { useChartTheme } from '@/hooks/use-chart-theme';
import { StatTile } from '@/components/ui/stat-tile';
import { formatCompact, formatMoney, sameMoney } from '@/lib/money';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { monthShortLabel } from '@/lib/date';
import { useMonthParam } from '@/hooks/use-month-param';


export function ReportsPage() {
  // Relatórios seguem o mesmo período das outras telas — antes ficavam presos
  // no mês corrente, sem como olhar o passado.
  const [month, setMonth] = useMonthParam();
  const { data, isLoading, isError } = useReports(month);
  const baseCurrency = useBaseCurrency();
  // Cores lidas do tema atual (claro/escuro) — nunca hardcoded (corrige B3)
  const chart = useChartTheme();
  const COLORS = chart.series;

  const header = (
    <PageHeader
      title="Relatórios"
      subtitle="Para onde o dinheiro foi."
      period={<PeriodPicker value={month} onChange={setMonth} />}
    />
  );

  if (isLoading) {
    return (
      <div className="space-y-8">
        {header}
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
      <div className="space-y-8">
        {header}
        <div className="p-12 text-center rounded-xl bg-destructive/10 border border-destructive/20">
          <p className="text-sm font-bold text-destructive">Não foi possível carregar os relatórios.</p>
          <p className="text-xs text-muted-foreground mt-1">Verifique a conexão e tente novamente.</p>
        </div>
      </div>
    );
  }

  // O eixo lê `name`; o backend manda `month` (YYYY-MM) como rótulo autoritativo
  // e o nome curto é formatado aqui, em PT-BR (ver monthShortLabel).
  const monthlyData = (data?.monthly_history || []).map(
    (m: { month?: string; name?: string }) => ({
      ...m,
      name: m.month ? monthShortLabel(m.month) : m.name,
    }),
  );
  // "Pouca história" (B4): conta meses com movimento real, não o tamanho da série
  // (o back devolve 6 meses, a maioria zerada para quem é novo).
  const monthsWithData = monthlyData.filter(
    (m: { income?: number | string; expenses?: number | string }) =>
      (Number(m.income) || 0) + (Number(m.expenses) || 0) > 0,
  ).length;
  const currentSummary = data?.current_summary || { total_expenses: 0, total_income: 0, net_savings: 0, my_expenses: 0, my_income: 0, my_net: 0, categories: [] };
  const categoryData = currentSummary.categories || [];
  // Destaque = a sua parte (splits); sublinha = total da casa/workspace
  const myExpenses = Number(currentSummary.my_expenses ?? 0);
  const myIncome = Number(currentSummary.my_income ?? 0);
  const myNet = Number(currentSummary.my_net ?? 0);
  // Ver Home: o hint da casa é redundante quando bate com a sua parte
  const casa = (mine: number, house: number) =>
    sameMoney(mine, house) ? undefined : `Casa ${formatMoney(house, { currency: baseCurrency })}`;

  return (
    <div className="space-y-8 animate-in fade-in duration-700">
      {header}
      <div className="grid gap-4 md:grid-cols-4">
        <StatTile
          label="Seu gasto (mês)"
          value={myExpenses}
          kind="expense"
          currency={baseCurrency}
          hint={casa(myExpenses, Number(currentSummary.total_expenses))}
        />
        <StatTile
          label="Sua receita (mês)"
          value={myIncome}
          kind="income"
          currency={baseCurrency}
          hint={casa(myIncome, Number(currentSummary.total_income))}
        />
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">Maior categoria</p>
          <p className="mt-1 truncate text-2xl font-semibold text-foreground">
            {categoryData.length > 0
              ? [...categoryData].sort((a: { value: number }, b: { value: number }) => b.value - a.value)[0].name
              : 'Nenhuma'}
          </p>
        </div>
        <StatTile
          label="Seu saldo (mês)"
          value={myNet}
          kind={myNet >= 0 ? 'income' : 'expense'}
          currency={baseCurrency}
          hint={casa(myNet, Number(currentSummary.net_savings))}
        />
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Visão geral</TabsTrigger>
          <TabsTrigger value="categories">Categorias</TabsTrigger>
          <TabsTrigger value="trends">Fluxo</TabsTrigger>
          <TabsTrigger value="budget">Orçamento</TabsTrigger>
        </TabsList>

        <TabsContent value="budget" className="animate-in slide-in-from-bottom-4 duration-500">
          <BudgetPanel
            spentByCategory={categoryData}
            totalExpenses={currentSummary.total_expenses}
            excludedForeignCount={currentSummary.excluded_foreign_count}
            month={month}
          />
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
              {monthsWithData >= 2 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} vertical={false} />
                    <XAxis dataKey="name" stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => formatCompact(value, baseCurrency)} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: '12px', color: chart.tooltipText }}
                      itemStyle={{ color: chart.tooltipText, fontWeight: 'bold' }}
                    />
                    <Bar dataKey="income" fill={chart.series[1]} radius={[4, 4, 0, 0]} name="Receita" />
                    <Bar dataKey="expenses" fill={chart.series[0]} radius={[4, 4, 0, 0]} name="Despesa (casa)" />
                    <Bar dataKey="my_expenses" fill={chart.series[2]} radius={[4, 4, 0, 0]} name="Minha parte" />
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
                        contentStyle={{ backgroundColor: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: '12px', color: chart.tooltipText }}
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
                <div className="space-y-3.5">
                  {categoryData.length > 0 ? (
                    [...categoryData]
                      .sort((a: { value: number }, b: { value: number }) => b.value - a.value)
                      .map((item: { name: string; value: number }, idx: number) => {
                        const max = Math.max(...categoryData.map((c: { value: number }) => c.value), 1);
                        const pct = (item.value / max) * 100;
                        const color = COLORS[idx % COLORS.length];
                        return (
                          <div key={item.name} className="space-y-1.5">
                            <div className="flex items-center justify-between">
                              <div className="flex min-w-0 items-center gap-2.5">
                                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                                <span className="truncate text-sm font-medium text-foreground">{item.name}</span>
                              </div>
                              <span className="tabular text-sm font-semibold text-foreground">{formatMoney(item.value, { currency: baseCurrency })}</span>
                            </div>
                            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                              <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
                            </div>
                          </div>
                        );
                      })
                  ) : (
                    <p className="py-8 text-center text-muted-foreground">Comece a registrar gastos para ver os detalhes.</p>
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
               {monthsWithData >= 2 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} vertical={false} />
                    <XAxis dataKey="name" stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: '12px', color: chart.tooltipText }}
                    />
                    <Line type="monotone" dataKey="income" stroke={chart.series[1]} strokeWidth={3} dot={{ r: 6, strokeWidth: 2, fill: chart.tooltipBg }} name="Receita" />
                    <Line type="monotone" dataKey="expenses" stroke={chart.series[0]} strokeWidth={3} dot={{ r: 6, strokeWidth: 2, fill: chart.tooltipBg }} name="Despesa (casa)" />
                    <Line type="monotone" dataKey="my_expenses" stroke={chart.series[2]} strokeWidth={2} strokeDasharray="4 4" dot={{ r: 4, strokeWidth: 2, fill: chart.tooltipBg }} name="Minha parte" />
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
