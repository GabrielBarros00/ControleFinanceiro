import * as React from 'react';
import { cn } from '@/lib/utils';

/*
 * NativeSelect — o `<select>` do navegador, com a aparência do `Input`.
 *
 * Por que NATIVO e não o `Select` de `ui/select.tsx`: o popup do Base UI escapa
 * do focus-trap do `Dialog` (Radix), então dentro de modal o app sempre usou
 * `<select>` puro. Isso continua valendo — o que não podia continuar era cada
 * tela declarar a sua própria constante `selectClass`. Havia TREZE cópias
 * (transaction-form/*, SettlementDialog, AmortizationTable, RecurrenceEditor,
 * MaterializeScopeField, WorkspaceCreateDialog, BudgetPanel, GlobalLedgerPage,
 * AdminPage, RecurringTransactionsPage), doze idênticas e uma divergente.
 *
 * O QUE ISSO CONSERTA, e é o motivo real de existir: todas usavam `text-sm`.
 * O Safari do iPhone dá zoom na página ao focar um campo com fonte MENOR que
 * 16px, e não desfaz o zoom ao sair — a partir do primeiro toque num select, o
 * app inteiro fica grande e deslocado até a pessoa recarregar. Era a explicação
 * literal de "tela com tamanho maior do que deveria". `text-base md:text-sm`
 * (16px no celular, 14px no desktop) é exatamente o que o `Input` já fazia em
 * `ui/input.tsx` — o `<select>` é que tinha ficado para trás.
 *
 * `md:` e não `sm:` de propósito: é o mesmo ponto de corte do `Input`, e
 * tablets em retrato (≥640px e <768px) também são toque.
 */
export const nativeSelectClass =
  'flex h-10 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-base text-foreground shadow-sm transition-colors outline-hidden focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:border-border dark:bg-background';

export const NativeSelect = React.forwardRef<
  HTMLSelectElement,
  React.ComponentProps<'select'>
>(({ className, ...props }, ref) => (
  <select ref={ref} data-slot="native-select" className={cn(nativeSelectClass, className)} {...props} />
));
NativeSelect.displayName = 'NativeSelect';
