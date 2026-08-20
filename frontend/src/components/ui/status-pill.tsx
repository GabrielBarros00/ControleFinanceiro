import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/*
 * StatusPill — pílula de status com tom semântico (docs/frontend-redesign/05 §3).
 * Padroniza Confirmada/Paga/Cancelada, Ativa/Inativa, Paga/Pendente/Vencida etc.
 */
export type PillTone = 'neutral' | 'success' | 'warning' | 'danger' | 'brand';

const TONE: Record<PillTone, string> = {
  neutral: 'bg-muted text-muted-foreground',
  success: 'bg-income-subtle text-income',
  warning: 'bg-warning-subtle text-warning',
  danger: 'bg-expense-subtle text-expense',
  brand: 'bg-brand-subtle text-brand',
};

export function StatusPill({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: PillTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Mapa de status de transação → rótulo + tom (usado no extrato/detalhe). */
export function txStatusPill(status?: string): { label: string; tone: PillTone } | null {
  switch (status) {
    case 'paid':
      return { label: 'Paga', tone: 'success' };
    case 'cancelled':
      return { label: 'Cancelada', tone: 'danger' };
    case 'pending':
      return { label: 'Pendente', tone: 'warning' };
    case 'confirmed':
    default:
      return null; // confirmada = estado normal, não polui a linha
  }
}

/**
 * Pílula de LIQUIDAÇÃO — outro eixo (ADR 0029).
 *
 * `status` é competência: a despesa existe, entra em rateio e relatórios.
 * `settled_at` é caixa: o dinheiro saiu ou não. São perguntas diferentes e por
 * isso duas pílulas, não uma — juntá-las faria "A pagar" parecer um estado da
 * despesa, quando ela pode estar confirmada, dividida e cobrada e ainda assim
 * não ter sido paga.
 *
 * `null` quando já foi paga: é o caso normal e não precisa marcar a linha, mesma
 * regra do `confirmed` acima. Compra no cartão também não marca — ela nunca tem
 * liquidação própria, e uma pílula "A pagar" ali apontaria para a fatura.
 */
export function settlementPill(
  settledAt?: string | null,
  creditCardId?: number | null,
): { label: string; tone: PillTone } | null {
  if (creditCardId != null || settledAt != null) return null;
  return { label: 'A pagar', tone: 'warning' };
}
