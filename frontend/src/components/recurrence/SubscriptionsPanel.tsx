import { CalendarClock, Sparkles } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatCurrency } from '@/lib/money';
import { parseApiDay } from '@/lib/date';
import { emTeste, type AssinaturaResumo } from '@/lib/assinatura';

const dia = (valor: string) => parseApiDay(valor).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });

/**
 * Assinaturas (ADR 0039): quanto custam por mês, somadas, e quando cada uma
 * cobra de novo.
 *
 * O destaque é a SUA parte, e o valor cheio vem nomeado ao lado: numa casa que
 * divide o streaming, "R$ 55,90" seria o número de todo mundo. Os valores por
 * mês vêm do servidor (anual ÷ 12, semanal × 52 ÷ 12) — a mesma conta que o
 * agente de IA usa. Moedas diferentes não se somam.
 */
export function SubscriptionsPanel({ itens, moedaBase, hoje }: { itens: AssinaturaResumo[]; moedaBase: string; hoje: string }) {
  const ativas = itens.filter((i) => i.is_subscription && i.is_active);
  if (ativas.length === 0) return null;
  const porMoeda = new Map<string, { minha: number; cheia: number }>();
  for (const i of ativas) {
    const moeda = i.currency ?? moedaBase;
    const soma = porMoeda.get(moeda) ?? { minha: 0, cheia: 0 };
    soma.minha += Number(i.my_monthly_equivalent ?? 0);
    soma.cheia += Number(i.monthly_equivalent ?? 0);
    porMoeda.set(moeda, soma);
  }
  const proximas = [...ativas].sort((a, b) => (a.next_occurrence ?? '9999').localeCompare(b.next_occurrence ?? '9999'));

  return (
    <Card className="border-border bg-card shadow-xl" data-testid="quadro-assinaturas">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Sparkles className="h-5 w-5 text-primary" /> Assinaturas
        </CardTitle>
        <CardDescription>
          {[...porMoeda.entries()].map(([moeda, v]) => (
            <span key={moeda} className="mr-3 inline-block">
              <strong className="tabular text-foreground">{formatCurrency(v.minha, moeda)}</strong>/mês a sua parte
              {Math.abs(v.cheia - v.minha) >= 0.005 && <> · de {formatCurrency(v.cheia, moeda)}</>}
            </span>
          ))}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y divide-border/60">
          {proximas.map((i) => (
            <li key={i.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-foreground">{i.title}</span>
                <span className="block text-xs text-muted-foreground">
                  {[i.plan, i.next_occurrence && `cobra em ${dia(i.next_occurrence)}`].filter(Boolean).join(' · ')}
                </span>
                {/* Debaixo do nome, não entre ele e o valor: no celular a etiqueta
                    no meio da linha espremia o texto em três linhas. */}
                {emTeste(i, hoje) && (
                  <span className="mt-1 inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning-subtle px-2 py-0.5 text-[11px] font-semibold text-warning">
                    <CalendarClock className="h-3 w-3" /> teste grátis até {dia(i.trial_ends_on!)}
                  </span>
                )}
              </span>
              <span className="tabular shrink-0 whitespace-nowrap font-semibold">
                {formatCurrency(Number(i.my_monthly_equivalent ?? 0), i.currency ?? moedaBase)}/mês
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
