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
        const masked = maskCurrency((value * 100).toFixed(0));
        if (masked !== displayValue) {
          setDisplayValue(masked);
        }
      } else if (value === undefined || isNaN(value)) {
        setDisplayValue('');
      }
    }, [value, displayValue]);

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
