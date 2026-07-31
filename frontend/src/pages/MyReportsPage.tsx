import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  Receipt,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { PageHeader } from '@/components/layout/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile } from '@/components/ui/stat-tile';
import { EmptyState } from '@/components/ui/empty-state';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { useMyReports } from '@/hooks/use-overview';
import { useChartTheme } from '@/hooks/use-chart-theme';
import { formatCompact, formatMoney } from '@/lib/money';

/**
 * Relatórios GLOBAIS e pessoais (ADR 0020 + 0021 + 0022).
 *
 * Os Relatórios do app sempre foram de UM workspace: respondem "quanto esta casa
 * gastou". Nenhuma tela respondia "como está o MEU período" — renda contra
 * consumo, resultado mês a mês, quanto de mim foi para cada casa.
 *
 * Depois do ADR 0021 os Relatórios locais nem podem mais responder isso: renda
 * saiu do workspace, e somar salário global com despesa de uma casa só produzia
 * uma "sobra" maior que a real (era exatamente o número que aquele ADR removeu).
 * Este é o lugar certo para a pergunta — e ele NÃO substitui os Relatórios do
 * workspace, que continuam operacionais e são outro eixo.
 */
const MESES = 6;

function rotuloMes(month: string): string {
  const [ano, mes] = month.split('-').map(Number);
  return new Date(ano, mes - 1, 1)
    .toLocaleDateString('pt-BR', { month: 'short' })
    .replace('.', '');
}

export function MyReportsPage() {
  const { reports, isLoading } = useMyReports(MESES);
  const chart = useChartTheme();

  const moeda = reports?.currency ?? 'BRL';
  const n = (v: unknown) => Number(v ?? 0);
  const fmt = (v: unknown) => formatMoney(n(v), { currency: moeda });

  const dados = (reports?.months ?? []).map((m) => ({
    name: rotuloMes(m.month),
    month: m.month,
    renda: n(m.income),
    consumo: n(m.consumption),
    resultado: n(m.result),
    caixa: n(m.net_cash),
  }));
  // Um único mês não desenha tendência nenhuma — a linha vira um ponto solto.
  const temSerie = dados.filter((d) => d.renda !== 0 || d.consumo !== 0).length >= 2;

  const totais = reports?.totals;
  const resultado = n(totais?.result);
  const consumoTotal = n(totais?.consumption);
  const participacao = reports?.by_workspace ?? [];

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Seus relatórios" subtitle="Carregando…" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-[360px] w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Seus relatórios"
        subtitle={`Últimos ${MESES} meses, somando todos os workspaces.`}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Renda no período"
          value={n(totais?.income)}
          kind="income"
          icon={TrendingUp}
          currency={moeda}
        />
        <StatTile
          label="Consumo no período"
          value={consumoTotal}
          kind="expense"
          icon={Receipt}
          currency={moeda}
          hint="Sua parte, em todas as casas"
        />
        <StatTile
          label="Resultado"
          value={resultado}
          kind={resultado >= 0 ? 'income' : 'expense'}
          icon={Wallet}
          currency={moeda}
          hint="Renda menos consumo"
        />
        <StatTile
          label="Caixa líquido"
          value={n(totais?.net_cash)}
          kind={n(totais?.net_cash) >= 0 ? 'income' : 'expense'}
          icon={BarChart3}
          currency={moeda}
          hint="O que entrou menos o que saiu"
        />
      </div>

      <ExcludedForeignNotice
        count={reports?.excluded_foreign_count}
        baseCurrency={moeda}
      />

      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-base font-semibold text-foreground">Renda × consumo</h2>
          <p className="text-sm text-muted-foreground">
            A comparação que os Relatórios do workspace não podem fazer: a renda é
            sua e não mora em casa nenhuma.
          </p>
        </div>
        <div className="h-[320px] p-4">
          {temSerie ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dados}>
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} vertical={false} />
                <XAxis dataKey="name" stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                <YAxis
                  stroke={chart.axis}
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatCompact(v, moeda)}
                />
                <Tooltip
                  formatter={(v: number) => formatMoney(v, { currency: moeda })}
                  contentStyle={{
                    backgroundColor: chart.tooltipBg,
                    border: `1px solid ${chart.tooltipBorder}`,
                    borderRadius: '12px',
                    color: chart.tooltipText,
                  }}
                />
                <Legend />
                <Bar dataKey="renda" name="Renda" fill={chart.series[1]} radius={[6, 6, 0, 0]} />
                <Bar dataKey="consumo" name="Consumo" fill={chart.series[0]} radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-muted-foreground italic">
              Ainda não há meses suficientes para comparar.
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-base font-semibold text-foreground">
            Resultado e caixa, mês a mês
          </h2>
          <p className="text-sm text-muted-foreground">
            Resultado é renda − consumo (competência). Caixa é o dinheiro que se
            moveu, com fatura paga, acerto e parcela de financiamento (ADR 0022).
          </p>
        </div>
        <div className="h-[320px] p-4">
          {temSerie ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dados}>
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} vertical={false} />
                <XAxis dataKey="name" stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} />
                <YAxis
                  stroke={chart.axis}
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => formatCompact(v, moeda)}
                />
                <Tooltip
                  formatter={(v: number) => formatMoney(v, { currency: moeda })}
                  contentStyle={{
                    backgroundColor: chart.tooltipBg,
                    border: `1px solid ${chart.tooltipBorder}`,
                    borderRadius: '12px',
                    color: chart.tooltipText,
                  }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="resultado"
                  name="Resultado"
                  stroke={chart.series[1]}
                  strokeWidth={3}
                  dot={{ r: 5, strokeWidth: 2, fill: chart.tooltipBg }}
                />
                <Line
                  type="monotone"
                  dataKey="caixa"
                  name="Caixa líquido"
                  stroke={chart.series[2]}
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  dot={{ r: 4, strokeWidth: 2, fill: chart.tooltipBg }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-muted-foreground italic">
              Ainda não há meses suficientes para desenhar a evolução.
            </div>
          )}
        </div>
      </section>

      {/* Participação por casa — e o caminho de volta para ela. Sem o link, o
          número respondia "a Casa consumiu tanto de mim" e deixava o usuário
          sem como investigar. */}
      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-base font-semibold text-foreground">Por workspace</h2>
          <p className="text-sm text-muted-foreground">
            Quanto do seu consumo do período foi para cada casa.
          </p>
        </div>
        <div className="divide-y divide-border">
          {participacao.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={Receipt}
                title="Nenhum consumo no período"
                description="Assim que houver lançamentos, cada workspace aparece aqui."
              />
            </div>
          ) : (
            participacao.map((w) => {
              const fatia = consumoTotal > 0 ? (n(w.consumption) / consumoTotal) * 100 : 0;
              return (
                <Link
                  key={w.workspace_id}
                  to={`/w/${w.workspace_id}/reports`}
                  className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-foreground">{w.workspace_name}</p>
                    <div className="mt-1.5 h-1.5 w-full max-w-[320px] overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-brand"
                        style={{ width: `${Math.min(fatia, 100)}%` }}
                      />
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-3 text-sm">
                    <span className="tabular-nums text-foreground">{fmt(w.consumption)}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {fatia.toFixed(0)}%
                    </span>
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                  </div>
                </Link>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
