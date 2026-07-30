import { CreditCard, Landmark, AlertTriangle } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { StatTile } from '@/components/ui/stat-tile';
import { useCommitments } from '@/hooks/use-overview';
import { formatMoney } from '@/lib/money';
import { parseApiDay } from '@/lib/date';

/**
 * Compromissos financeiros da PESSOA (ADR 0020).
 *
 * Antes chamava-se "Endividamento" e vivia dentro de um workspace, o que
 * embaralhava dois eixos com nomes parecidos: *acertos entre pessoas* (quem deve
 * a quem no rateio, que se resolve com uma transferência) e *compromissos com
 * terceiros* (o banco e a operadora do cartão, que se resolvem pagando a fatura).
 *
 * Aqui é o segundo, e globalmente: o cartão compartilhado entre dois workspaces
 * aparece UMA vez — antes exigia dois cadastros e a mesma fatura era contada em
 * dobro.
 */
export function CommitmentsPage() {
  const { commitments, isLoading } = useCommitments();
  const moeda = commitments?.currency ?? 'BRL';
  const fmt = (v: unknown) => formatMoney(Number(v ?? 0), { currency: moeda });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-24 w-full max-w-xs" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const cartoes = commitments?.cards ?? [];
  const financiamentos = commitments?.financings ?? [];

  if (cartoes.length === 0 && financiamentos.length === 0) {
    return (
      <EmptyState
        icon={Landmark}
        title="Nenhum compromisso em aberto"
        description="Faturas de cartão e parcelas de financiamento a vencer aparecem aqui."
      />
    );
  }

  return (
    <div className="space-y-6">
      <StatTile
        label="Total a pagar"
        value={Number(commitments?.total ?? 0)}
        kind="expense"
        currency={moeda}
        hint="Faturas em aberto e saldo devedor dos financiamentos"
        className="max-w-xs"
      />

      {cartoes.length > 0 && (
        <section className="rounded-xl border border-border bg-card">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <CreditCard className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold text-foreground">Faturas de cartão</h2>
          </div>
          <div className="divide-y divide-border">
            {cartoes.map((c) => (
              <div key={c.statement_id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{c.card_name}</p>
                  <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                    {/* parseApiDay: vencimento é DIA de calendário, não instante —
                        parseApiDate voltaria um dia dependendo do fuso */}
                    vence {parseApiDay(c.due_date).toLocaleDateString('pt-BR')}
                    {c.is_overdue && (
                      <span className="inline-flex items-center gap-1 text-expense">
                        <AlertTriangle className="h-3.5 w-3.5" /> vencida
                      </span>
                    )}
                  </p>
                </div>
                <span className="shrink-0 tabular-nums font-medium text-foreground">
                  {fmt(c.amount)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {financiamentos.length > 0 && (
        <section className="rounded-xl border border-border bg-card">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <Landmark className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold text-foreground">Financiamentos</h2>
          </div>
          <div className="divide-y divide-border">
            {financiamentos.map((f) => (
              <div key={f.financing_id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{f.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {f.remaining_installments} parcela(s) · próxima em{' '}
                    {parseApiDay(f.next_due_date).toLocaleDateString('pt-BR')}
                  </p>
                </div>
                <span className="shrink-0 tabular-nums font-medium text-foreground">
                  {fmt(f.outstanding)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
