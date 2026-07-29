import * as React from 'react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { maskCurrency, parseCurrency } from '@/lib/money';

interface MoneyInputProps extends Omit<React.ComponentProps<"input">, 'onChange' | 'value'> {
  value?: number;
  onChange?: (value: number) => void;
  prefix?: string;
}

// Recuo do prefixo (left-3) e respiro entre ele e o número
const PREFIX_LEFT = 12;
const PREFIX_GAP = 6;
const PREFIX_MIN_PADDING = 36; // = pl-9, o suficiente para "R$"

const MoneyInput = React.forwardRef<HTMLInputElement, MoneyInputProps>(
  ({ value, onChange, prefix = 'R$', className, style, ...props }, ref) => {
    const [displayValue, setDisplayValue] = React.useState('');
    const prefixRef = React.useRef<HTMLSpanElement>(null);
    const [padding, setPadding] = React.useState(PREFIX_MIN_PADDING);

    // O recuo do texto acompanha a LARGURA REAL do prefixo. Com padding fixo
    // (pl-9), símbolos de 3 caracteres — "US$", "ARS", "CHF" — encostavam no
    // valor ("US$1.234,56") ou ficavam por baixo dele.
    React.useLayoutEffect(() => {
      if (!prefix) return;
      const width = prefixRef.current?.offsetWidth ?? 0;
      setPadding(Math.max(PREFIX_MIN_PADDING, PREFIX_LEFT + width + PREFIX_GAP));
    }, [prefix]);

    React.useEffect(() => {
      if (value !== undefined && !isNaN(value)) {
        // Math.round, não toFixed(0): `1.005 * 100` dá 100.49999999999999 em
        // ponto flutuante e o toFixed truncava para 100 (R$ 1,00 em vez de 1,01).
        const masked = maskCurrency(String(Math.round(value * 100)));
        // Compara com o valor JÁ exibido lendo o DOM em vez de depender de
        // `displayValue`: o efeito escrevia o mesmo state de que dependia.
        setDisplayValue((atual) => (atual === masked ? atual : masked));
      } else {
        setDisplayValue('');
      }
    }, [value]);

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const rawValue = e.target.value;
      const masked = maskCurrency(rawValue);
      const numericValue = parseCurrency(masked);

      setDisplayValue(masked);
      if (onChange) {
        onChange(numericValue);
      }
    };

    return (
      <div className="relative">
        {prefix && (
          <span
            ref={prefixRef}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground font-bold text-sm pointer-events-none"
          >
            {prefix}
          </span>
        )}
        <Input
          {...props}
          ref={ref}
          value={displayValue}
          onChange={handleChange}
          className={cn(className)}
          style={prefix ? { ...style, paddingLeft: padding } : style}
        />
      </div>
    );
  }
);

MoneyInput.displayName = 'MoneyInput';

export { MoneyInput };
