/**
 * Assinatura (ADR 0039): o que as telas precisam decidir sobre ela.
 *
 * Fora do componente porque o `react-refresh` só recarrega arquivo que exporta
 * componente — e a lista de recorrências usa a mesma regra no selo.
 */
export interface AssinaturaResumo {
  id: number;
  title: string;
  currency?: string | null;
  is_active: boolean;
  is_subscription?: boolean | null;
  plan?: string | null;
  trial_ends_on?: string | null;
  next_occurrence?: string | null;
  monthly_equivalent?: string | number | null;
  my_monthly_equivalent?: string | number | null;
}

/** Teste grátis que ainda não acabou: a data a lembrar para cancelar. `hoje` é AAAA-MM-DD local. */
export function emTeste(item: Pick<AssinaturaResumo, 'is_subscription' | 'trial_ends_on'>, hoje: string): boolean {
  return Boolean(item.is_subscription && item.trial_ends_on && item.trial_ends_on >= hoje);
}
