import { useFormContext } from 'react-hook-form';
import { Label } from '@/components/ui/label';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useFormCurrency } from './use-form-currency';
import type { Participant } from './SplitEditor';
import type { TransactionFormValues } from './schema';

interface SimpleSplitChipsProps {
  participants: Participant[];
}

// Divisão simples (modo padrão): escolha quem participa → rateio IGUAL.
// Escreve em `splits` com method 'equal'. Controle fino (%/fixo/por item) mora
// em "Opções avançadas".
export function SimpleSplitChips({ participants }: SimpleSplitChipsProps) {
  const { watch, setValue } = useFormContext<TransactionFormValues>();
  const { fmt } = useFormCurrency();
  const splits = watch('splits') ?? [];
  const total = watch('total_amount') ?? 0;
  const selected = new Set(splits.map((s) => s.user_id));

  const toggle = (id: string) => {
    const next = selected.has(id)
      ? splits.filter((s) => s.user_id !== id)
      : [...splits, { user_id: id, value: 0 }];
    setValue('splits', next, { shouldValidate: true, shouldDirty: true });
  };

  const count = selected.size;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-semibold text-foreground">Dividir com</Label>
        {count > 0 && total > 0 && (
          <span className="text-xs font-semibold text-muted-foreground">
            ≈ {fmt(total / count)} cada
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {participants.map((p) => {
          const active = selected.has(p.id);
          return (
            <button
              key={p.id}
              type="button"
              aria-pressed={active}
              aria-label={p.name}
              onClick={() => toggle(p.id)}
              className={cn(
                'inline-flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-sm font-semibold transition-colors',
                active
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border bg-background text-muted-foreground hover:border-primary/50'
              )}
            >
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold uppercase',
                  active ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                )}
              >
                {active ? <Check className="h-3.5 w-3.5" /> : p.name.slice(0, 2)}
              </span>
              {p.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
