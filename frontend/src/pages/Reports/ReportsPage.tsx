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
import * as React from 'react';
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
import { cn } from '@/lib/utils';


export function ReportsPage() {
  // Relatórios seguem o mesmo período das outras telas — antes ficavam presos
  // no mês corrente, sem como olhar o passado.
  const [month, setMonth] = useMonthParam();
  /**
   * De quem é a composição por categoria que a aba mostra.
   *
   * A pizza e o ranking sempre foram do ESPAÇO para quem tem acesso completo, e
   * nada na tela dizia isso — ficavam sob um cabeçalho cujo primeiro número é
   * "Seu gasto (mês)". Quem divide o aluguel via "Moradia R$ 8.450" e lia como
   * seu. `my_categories` já vinha no mesmo payload (é o que a tela usa quando o
   * acesso é restrito); faltava poder escolher.
   */
  const [comporPor, setComporPor] = React.useState<'espaco' | 'minha'>('espaco');
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
        <Skeleton className="h-[260px] w-full bg-card border-border sm:h-[400px]" />
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
    (m: { expenses?: number | string; my_expenses?: number | string }) =>
      (Number(m.expenses) || 0) + (Number(m.my_expenses) || 0) > 0,
  ).length;
  // Números da casa vêm `null` sem acesso financeiro completo (ADR 0018), então
  // o fallback deles é `null` e não 0 — 0 viraria "Espaço R$ 0,00" na dica e um
  // gráfico de pizza vazio apresentado como se a casa não tivesse gastado nada.
  const currentSummary = data?.current_summary || {
    total_expenses: null, my_expenses: 0, paid_by_me: 0, my_balance: 0, categories: null,
  };
  const categoryDataCasa = currentSummary.categories || [];
  // Mesma composição, recortada na sua parte — é o par de `categories` para a
  // meta pessoal (a da casa compara com o total; a sua, com a sua fatia)
  const myCategoryData = currentSummary.my_categories || [];
  // Destaque = a sua parte (splits); sublinha = total da casa/workspace
  const myExpenses = Number(currentSummary.my_expenses ?? 0);
  // Receita e saldo saíram destes relatórios (ADR 0021): são pessoais e viviam
  // aqui misturando renda GLOBAL com gasto DESTE workspace. O par certo do gasto
  // é o caixa — quanto eu paguei — e a diferença entre os dois, que é o acerto.
  const paidByMe = Number(currentSummary.paid_by_me ?? 0);
  const myBalance = Number(currentSummary.my_balance ?? 0);
  // Ver Home: o hint da casa é redundante quando bate com a sua parte — e não
  // existe quando o acesso é restrito (`house` nulo).
  const numeroDaCasa = (valor: unknown): number | null =>
    valor == null ? null : Number(valor);
  const casa = (mine: number, house: number | null) =>
    house == null || sameMoney(mine, house)
      ? undefined
      : `Casa ${formatMoney(house, { currency: baseCurrency })}`;
  // Sem acesso completo não há composição da casa: a pizza e o ranking passam a
  // mostrar a SUA parte (`my_categories`, que o backend continua devolvendo). É
  // melhor que uma tela vazia — e é o número que a pessoa pode conferir.
  const temVisaoDaCasa = currentSummary.total_expenses != null;
  // Sem acesso completo não HÁ o que escolher: só a sua parte existe.
  const porEspaco = temVisaoDaCasa && comporPor === 'espaco';
  const categoryData = porEspaco ? categoryDataCasa : myCategoryData;
  const totalDaComposicao = categoryData.reduce(
    (acc: number, c: { value: number }) => acc + Number(c.value || 0),
    0,
  );

  return (
    <div className="space-y-8 animate-in fade-in duration-700">
      {header}
      <div className="grid gap-4 md:grid-cols-4">
        <StatTile
          label="Seu gasto (mês)"
          value={myExpenses}
          kind="expense"
          currency={baseCurrency}
          hint={casa(myExpenses, numeroDaCasa(currentSummary.total_expenses))}
        />
        {/* Ver Home: "pago por você" sugeria dinheiro fora da conta, e a compra
            no cartão entra aqui antes de a fatura ser paga (ADR 0022). */}
        <StatTile
          label="Adiantado por você (mês)"
          value={paidByMe}
          kind="neutral"
          currency={baseCurrency}
          hint="O que você assumiu das despesas deste espaço"
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
          // "Saldo" ficou reservado a saldo de conta: aqui é o acerto deste espaço.
          label={myBalance >= 0 ? 'A receber neste espaço' : 'A pagar neste espaço'}
          value={Math.abs(myBalance)}
          kind={myBalance >= 0 ? 'income' : 'expense'}
          currency={baseCurrency}
          hint="Diferença entre o que você pagou e a sua parte"
        />
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Visão geral</TabsTrigger>
          <TabsTrigger value="categories">Categorias</TabsTrigger>
          {/* "Fluxo" (de caixa) era promessa que a aba não cumpria: ela desenha
              evolução de DESPESA. Caixa de verdade é global e vive na Visão
              global (ADR 0022). */}
          <TabsTrigger value="trends">Evolução</TabsTrigger>
          <TabsTrigger value="budget">Orçamento</TabsTrigger>
        </TabsList>

        <TabsContent value="budget" className="animate-in slide-in-from-bottom-4 duration-500">
          <BudgetPanel
            spentByCategory={categoryDataCasa}
            totalExpenses={currentSummary.total_expenses}
            // Recorte pessoal: é contra ele que a meta pessoal é comparada
            mySpentByCategory={myCategoryData}
            myExpenses={myExpenses}
            excludedForeignCount={currentSummary.excluded_foreign_count}
            month={month}
          />
        </TabsContent>
        
        <TabsContent value="overview" className="space-y-4 animate-in slide-in-from-bottom-4 duration-500">
          <Card className="bg-card border-border shadow-xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <BarChart3 className="h-5 w-5 text-primary" />
                Gasto da casa × sua parte
              </CardTitle>
              {/* Não é "Receitas vs Despesas": renda saiu do espaço no ADR
                  0021 e o gráfico só desenha despesa. O título prometia uma
                  comparação que os dados não tinham. */}
              <CardDescription>Comparativo mensal dos últimos 6 meses.</CardDescription>
            </CardHeader>
            <CardContent className="h-[260px] sm:h-[400px]">
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
                    <Bar dataKey="expenses" fill={chart.series[0]} radius={[4, 4, 0, 0]} name="Despesa (espaço)" />
                    <Bar dataKey="my_expenses" fill={chart.series[2]} radius={[4, 4, 0, 0]} name="Minha parte" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground italic">Sem dados suficientes para gerar o gráfico.</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="categories" className="animate-in slide-in-from-bottom-4 duration-500 space-y-4">
          {/* Sem o seletor, a composição era do espaço e não se anunciava. Ele
              some para quem só tem a própria visão — dois botões em que um
              nunca pode ser clicado ensinam a coisa errada sobre o acesso. */}
          {temVisaoDaCasa && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">
                {porEspaco
                  ? 'Composição do espaço inteiro — inclui o que é das outras pessoas.'
                  : 'Só a sua fatia de cada despesa.'}{' '}
                <span className="font-medium text-foreground">
                  Total: {formatMoney(totalDaComposicao, { currency: baseCurrency })}
                </span>
              </p>
              <div
                role="group"
                aria-label="De quem é a composição"
                className="inline-flex shrink-0 rounded-lg border border-border bg-background p-0.5"
              >
                {([
                  ['espaco', 'Espaço'],
                  ['minha', 'Sua parte'],
                ] as const).map(([valor, texto]) => (
                  <button
                    key={valor}
                    type="button"
                    aria-pressed={comporPor === valor}
                    onClick={() => setComporPor(valor)}
                    className={cn(
                      'rounded-md px-3 py-1.5 text-sm font-semibold transition-colors',
                      comporPor === valor
                        ? 'bg-brand text-primary-foreground'
                        : 'text-muted-foreground hover:bg-muted',
                    )}
                  >
                    {texto}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <Card className="bg-card border-border shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <PieChartIcon className="h-5 w-5 text-primary" />
                  {porEspaco ? 'Distribuição do espaço' : 'Sua distribuição por categoria'}
                </CardTitle>
              </CardHeader>
              <CardContent className="h-[240px] sm:h-[350px]">
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
                <CardTitle>{porEspaco ? 'Gastos do espaço' : 'Gastos da sua parte'}</CardTitle>
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
                Evolução das despesas
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[260px] sm:h-[400px]">
               {monthsWithData >= 2 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monthlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} vertical={false} />
                    <XAxis dataKey="name" stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: '12px', color: chart.tooltipText }}
                    />
                    <Line type="monotone" dataKey="expenses" stroke={chart.series[0]} strokeWidth={3} dot={{ r: 6, strokeWidth: 2, fill: chart.tooltipBg }} name="Despesa (espaço)" />
                    <Line type="monotone" dataKey="my_expenses" stroke={chart.series[2]} strokeWidth={2} strokeDasharray="4 4" dot={{ r: 4, strokeWidth: 2, fill: chart.tooltipBg }} name="Minha parte" />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                 <div className="flex items-center justify-center h-full text-muted-foreground italic">Dê o primeiro passo registrando as despesas deste espaço.</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
