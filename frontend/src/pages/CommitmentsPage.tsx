import { AlertTriangle, CalendarClock, CreditCard, Landmark } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { StatTile } from '@/components/ui/stat-tile';
import { useCommitments } from '@/hooks/use-overview';
import { formatMoney } from '@/lib/money';
import { parseApiDay } from '@/lib/date';

/**
 * Compromissos financeiros da PESSOA (ADR 0020 + 0021).
 *
 * Antes chamava-se "Endividamento" e vivia dentro de um workspace, o que
 * embaralhava dois eixos com nomes parecidos: *acertos entre pessoas* (quem deve
 * a quem no rateio, que se resolve com uma transferência) e *compromissos com
 * terceiros* (o banco e a operadora do cartão, que se resolvem pagando a fatura).
 *
 * Aqui é o segundo, e é da pessoa: cartão e financiamento são de quem assinou.
 *
 * Os quatro números do topo substituem um "Total a pagar" que somava a próxima
 * fatura com o principal INTEIRO dos financiamentos — juntava o que vence em
 * cinco dias com o que vence em quinze anos, e não respondia nenhuma pergunta.
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
  const proximas = commitments?.next_installments ?? [];
  const vencido = Number(commitments?.overdue ?? 0);

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
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Valores POSITIVOS num card já rotulado "Vencido"/"A pagar": o sinal
            de menos ao lado do rótulo era redundante e lia como desconto. */}
        <StatTile
          label="Vencido"
          value={vencido}
          kind={vencido > 0 ? 'expense' : 'neutral'}
          currency={moeda}
          hint={vencido > 0 ? 'Pague o quanto antes' : 'Nada em atraso'}
        />
        <StatTile
          label="A vencer neste mês"
          value={Number(commitments?.due_this_month ?? 0)}
          kind="neutral"
          currency={moeda}
          hint="O que ainda sai do caixa até o fim do mês"
        />
        <StatTile
          label="Saldo devedor"
          value={Number(commitments?.outstanding_total ?? 0)}
          kind="neutral"
          currency={moeda}
          hint="Principal em aberto + faturas não pagas"
        />
        <StatTile
          label="Comprometimento mensal"
          value={Number(commitments?.monthly_commitment ?? 0)}
          kind="neutral"
          currency={moeda}
          hint="Uma parcela por financiamento ativo"
        />
      </div>

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

      {proximas.length > 0 && (
        <section className="rounded-xl border border-border bg-card">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <CalendarClock className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold text-foreground">Próximas parcelas</h2>
          </div>
          <div className="divide-y divide-border">
            {proximas.map((p) => (
              <div
                key={`${p.financing_id}-${p.installment_number}`}
                className="flex items-center justify-between gap-4 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{p.title}</p>
                  <p className="text-sm text-muted-foreground">
                    Parcela {p.installment_number} · vence{' '}
                    {parseApiDay(p.due_date).toLocaleDateString('pt-BR')}
                  </p>
                </div>
                <span className="shrink-0 tabular-nums font-medium text-foreground">
                  {fmt(p.amount)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
