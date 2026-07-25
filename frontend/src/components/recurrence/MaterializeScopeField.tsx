import { Label } from '@/components/ui/label';
import type { MaterializeScope } from '@/lib/recurrence';

// <select> nativo: dentro de Dialog (Radix) o Select do Base UI foge do focus-trap
const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

interface MaterializeScopeFieldProps {
  value: MaterializeScope;
  onChange: (scope: MaterializeScope) => void;
  /** Muda só o texto ("rendas" x "despesas"). */
  kind: 'income' | 'expense';
  idPrefix?: string;
}

/**
 * Data de início retroativa é ambígua: quem cadastra um salário que começou em
 * abril pode querer o histórico lançado, só o mês atual, ou só daqui pra frente.
 * Perguntar é mais barato que adivinhar e depois ter que apagar meses inteiros.
 */
export function MaterializeScopeField({
  value,
  onChange,
  kind,
  idPrefix = 'materialize',
}: MaterializeScopeFieldProps) {
  const noun = kind === 'income' ? 'rendas' : 'despesas';
  return (
    <div className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
      <Label htmlFor={`${idPrefix}-scope`}>A data de início é anterior a este mês. Lançar…</Label>
      <select
        id={`${idPrefix}-scope`}
        className={selectClass}
        value={value}
        onChange={(e) => onChange(e.target.value as MaterializeScope)}
      >
        <option value="current" className="bg-card">Só o mês atual</option>
        <option value="past" className="bg-card">Os meses anteriores também (lançar o histórico)</option>
        <option value="future" className="bg-card">Só os meses futuros</option>
      </select>
      <p className="text-[10px] font-medium text-muted-foreground">
        {value === 'past'
          ? `As ${noun} de cada mês desde a data de início serão criadas (até 24 meses).`
          : value === 'future'
            ? `Nada é lançado agora; a data de início é ajustada para a próxima ocorrência.`
            : `Só a ocorrência deste mês é lançada; os meses anteriores ficam de fora.`}
      </p>
    </div>
  );
}
