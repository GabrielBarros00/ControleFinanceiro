import * as React from 'react';
import { Input } from '@/components/ui/input';
import { maskCurrency, parseCurrency } from '@/lib/money';

interface MoneyInputProps extends Omit<React.ComponentProps<"input">, 'onChange' | 'value'> {
  value?: number;
  onChange?: (value: number) => void;
  prefix?: string;
}

const MoneyInput = React.forwardRef<HTMLInputElement, MoneyInputProps>(
  ({ value, onChange, prefix = 'R$', ...props }, ref) => {
    const [displayValue, setDisplayValue] = React.useState('');

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
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground font-bold text-sm pointer-events-none">
            {prefix}
          </span>
        )}
        <Input
          {...props}
          ref={ref}
          value={displayValue}
          onChange={handleChange}
          className={`${prefix ? 'pl-9' : ''} ${props.className || ''}`}
        />
      </div>
    );
  }
);

MoneyInput.displayName = 'MoneyInput';

export { MoneyInput };
