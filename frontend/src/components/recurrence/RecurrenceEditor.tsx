import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  WEEKDAYS,
  MONTHS,
  PRESET_LABEL,
  type RecurrenceFrequency,
  type RecurrenceValue,
} from '@/lib/recurrence';

// <select> nativo: usado dentro de Dialog (Radix), onde o Select do Base UI foge do focus-trap
const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

const FREQS: RecurrenceFrequency[] = ['daily', 'weekly', 'monthly', 'yearly'];

interface RecurrenceEditorProps {
  value: RecurrenceValue;
  onChange: (patch: Partial<RecurrenceValue>) => void;
  idPrefix?: string;
}

export function RecurrenceEditor({ value, onChange, idPrefix = 'rec' }: RecurrenceEditorProps) {
  const handleFrequencySelect = (selected: string) => {
    if (selected === 'custom') {
      // Entra no modo personalizado; interval=1 seria igual a preset, então ≥2
      onChange({ custom: true, interval: value.interval > 1 ? value.interval : 2 });
    } else {
      onChange({ custom: false, frequency: selected as RecurrenceFrequency, interval: 1 });
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-frequency`}>Frequência</Label>
          <select
            id={`${idPrefix}-frequency`}
            className={selectClass}
            value={value.custom ? 'custom' : value.frequency}
            onChange={(e) => handleFrequencySelect(e.target.value)}
          >
            {FREQS.map((f) => (
              <option key={f} value={f} className="bg-card">{PRESET_LABEL[f]}</option>
            ))}
            <option value="custom" className="bg-card">Personalizado…</option>
          </select>
        </div>

        {/* Presets: campos de fase contextuais */}
        {!value.custom && value.frequency === 'weekly' && (
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-dow`}>Dia da semana</Label>
            <select
              id={`${idPrefix}-dow`}
              className={selectClass}
              value={value.day_of_week}
              onChange={(e) => onChange({ day_of_week: Number(e.target.value) })}
            >
              {WEEKDAYS.map((name, idx) => (
                <option key={idx} value={idx} className="bg-card">{name}</option>
              ))}
            </select>
          </div>
        )}
        {!value.custom && (value.frequency === 'monthly' || value.frequency === 'yearly') && (
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-dom`}>Dia do mês</Label>
            <Input
              id={`${idPrefix}-dom`}
              type="number"
              min={1}
              max={31}
              value={value.day_of_month}
              onChange={(e) => onChange({ day_of_month: Number(e.target.value) })}
              className="bg-background/50"
            />
          </div>
        )}
      </div>

      {!value.custom && value.frequency === 'yearly' && (
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-moy`}>Mês do ano</Label>
          <select
            id={`${idPrefix}-moy`}
            className={selectClass}
            value={value.month_of_year}
            onChange={(e) => onChange({ month_of_year: Number(e.target.value) })}
          >
            {MONTHS.map((name, idx) => (
              <option key={idx} value={idx + 1} className="bg-card">{name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Personalizado: "a cada N períodos" a partir de uma data-âncora */}
      {value.custom && (
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-interval`}>A cada</Label>
            <div className="flex gap-2">
              <Input
                id={`${idPrefix}-interval`}
                type="number"
                min={1}
                value={value.interval}
                onChange={(e) => onChange({ interval: Math.max(1, Number(e.target.value) || 1) })}
                className="w-20 bg-background/50"
              />
              <select
                aria-label="Unidade"
                className={selectClass}
                value={value.frequency}
                onChange={(e) => onChange({ frequency: e.target.value as RecurrenceFrequency })}
              >
                <option value="daily" className="bg-card">Dias</option>
                <option value="weekly" className="bg-card">Semanas</option>
                <option value="monthly" className="bg-card">Meses</option>
                <option value="yearly" className="bg-card">Anos</option>
              </select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-start`}>A partir de</Label>
            <Input
              id={`${idPrefix}-start`}
              type="date"
              value={value.start_date}
              onChange={(e) => onChange({ start_date: e.target.value })}
              className="bg-background/50"
            />
          </div>
        </div>
      )}
    </div>
  );
}
