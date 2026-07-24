import * as React from 'react';
import { ChevronDown, Check } from 'lucide-react';
import { CURRENCIES } from '@/lib/currencies';
import { cn } from '@/lib/utils';

interface CurrencyComboboxProps {
  value: string;
  onChange: (code: string) => void;
}

// Combobox de moeda com busca e navegação por teclado (↑/↓/Enter/Esc). Renderiza
// a lista INLINE (sem portal), então funciona dentro do Dialog do form sem
// escapar do focus-trap.
export function CurrencyCombobox({ value, onChange }: CurrencyComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [highlight, setHighlight] = React.useState(0);
  const ref = React.useRef<HTMLDivElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? CURRENCIES.filter((c) => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q))
    : CURRENCIES;

  // Mantém o item destacado visível ao navegar por teclado
  React.useEffect(() => {
    if (!open) return;
    const el = listRef.current?.children[highlight] as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [highlight, open]);

  const select = (code: string) => {
    onChange(code);
    setOpen(false);
    setQuery('');
  };

  const openMenu = () => {
    setOpen(true);
    setHighlight(Math.max(0, filtered.findIndex((c) => c.code === value)));
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filtered[highlight]) select(filtered[highlight].code);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Moeda"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openMenu())}
        className="flex h-10 w-[92px] shrink-0 items-center justify-between rounded-md border border-border bg-background px-2 text-sm font-semibold text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {value}
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-1 w-64 overflow-hidden rounded-md border border-border bg-card shadow-xl">
          <input
            autoFocus
            value={query}
            onChange={(e) => { setQuery(e.target.value); setHighlight(0); }}
            onKeyDown={onKeyDown}
            placeholder="Buscar moeda..."
            className="w-full border-b border-border bg-background px-3 py-2 text-sm outline-none"
          />
          <div ref={listRef} role="listbox" className="max-h-56 overflow-auto py-1">
            {filtered.length === 0 ? (
              <p className="px-3 py-3 text-xs text-muted-foreground">Nenhuma moeda encontrada.</p>
            ) : (
              filtered.map((c, i) => (
                <button
                  type="button"
                  key={c.code}
                  role="option"
                  aria-selected={c.code === value}
                  onMouseEnter={() => setHighlight(i)}
                  onClick={() => select(c.code)}
                  className={cn(
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm',
                    i === highlight ? 'bg-accent' : 'hover:bg-accent',
                    c.code === value && 'font-semibold',
                  )}
                >
                  <span className="w-9 shrink-0 font-semibold">{c.code}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{c.name}</span>
                  {c.ptax && (
                    <span className="shrink-0 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-emerald-500">
                      oficial
                    </span>
                  )}
                  {c.code === value && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
