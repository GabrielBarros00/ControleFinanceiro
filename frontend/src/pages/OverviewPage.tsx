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
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile } from '@/components/ui/stat-tile';
import { EmptyState } from '@/components/ui/empty-state';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { useOverview, useMyActivity } from '@/hooks/use-overview';
import { useAuth } from '@/hooks/use-auth';
import { formatMoney } from '@/lib/money';
import { currentMonthLocal } from '@/lib/date';
import { parseApiDate } from '@/lib/date';

/**
 * Início GLOBAL e pessoal (ADR 0020).
 *
 * O Início antigo era a dashboard de UM workspace disfarçada de tela pessoal: lia
 * o `currentWorkspaceId` do navegador, mostrava "minha parte" ao lado do total da
 * casa e não somava nada de ninguém. Quem tem duas casas não tinha onde perguntar
 * "como está o meu mês".
 *
 * Os quatro números aparecem separados porque são perguntas diferentes — e o app
 * inteiro chamava tudo de "gasto":
 *
 * - **Consumo**: a minha parte das despesas.
 * - **Saída de caixa**: o que efetivamente saiu do meu bolso.
 * - **A pagar / a receber**: a diferença, por casa.
 * - **Resultado do mês**: renda − consumo. (Era o que se chamava "Seu saldo",
 *   que sugeria saldo bancário e nunca foi isso.)
 */
export function OverviewPage() {
  const { user } = useAuth();
  const month = currentMonthLocal();
  const { overview, isLoading } = useOverview(month);
  const { activity, isLoading: activityLoading } = useMyActivity(8);

  const firstName = user?.name?.split(' ')[0];
  const n = (v: unknown) => Number(v ?? 0);
  const moeda = overview?.currency ?? 'BRL';
  const fmt = (v: unknown) => formatMoney(n(v), { currency: moeda });

  const result = n(overview?.result);
  const aPagar = n(overview?.to_pay);
  const aReceber = n(overview?.to_receive);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Início"
        subtitle={
          firstName
            ? `Olá, ${firstName} — seu mês somando todos os workspaces.`
            : 'Seu mês somando todos os workspaces.'
        }
      />

      {isLoading ? (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-56 w-full" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label="Renda"
              value={n(overview?.income)}
              kind="income"
              icon={TrendingUp}
              currency={moeda}
              hint="Suas entradas, em todos os workspaces"
            />
            <StatTile
              label="Consumo"
              value={n(overview?.consumption)}
              kind="expense"
              icon={Receipt}
              currency={moeda}
              hint="Sua parte das despesas"
            />
            <StatTile
              label="Saída de caixa"
              value={n(overview?.cash_out)}
              kind="expense"
              icon={ArrowUpRight}
              currency={moeda}
              hint="O que saiu do seu bolso"
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

          {(aPagar > 0 || aReceber > 0) && (
            <div className="grid gap-4 sm:grid-cols-2">
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
              <h2 className="text-base font-semibold text-foreground">Por workspace</h2>
              <p className="text-sm text-muted-foreground">
                Acertos ficam separados por casa — não se compensam entre elas.
              </p>
            </div>
            <div className="divide-y divide-border">
              {(overview?.by_workspace ?? []).length === 0 ? (
                <div className="p-4">
                  <EmptyState
                    icon={Receipt}
                    title="Nenhum movimento neste mês"
                    description="Assim que houver lançamentos, cada workspace aparece aqui."
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
                        Consumo {fmt(w.consumption)} · Pago {fmt(w.cash_out)}
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
                    <span className="shrink-0 text-sm tabular-nums text-foreground">
                      {formatMoney(Number(t.total_amount), { currency: t.currency })}
                    </span>
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
