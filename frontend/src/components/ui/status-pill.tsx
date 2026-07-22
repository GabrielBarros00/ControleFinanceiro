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
