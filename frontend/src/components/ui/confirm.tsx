import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = React.createContext<ConfirmFn | null>(null);

// Substitui window.confirm(): abre um Dialog no tema e resolve a Promise com a
// escolha. Montar <ConfirmProvider> uma vez no topo da árvore (App).
export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [options, setOptions] = React.useState<ConfirmOptions | null>(null);
  const resolverRef = React.useRef<((v: boolean) => void) | null>(null);

  const confirm = React.useCallback<ConfirmFn>((opts) => {
    setOptions(opts);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
    });
  }, []);

  const settle = React.useCallback((result: boolean) => {
    resolverRef.current?.(result);
    resolverRef.current = null;
    setOptions(null);
  }, []);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={!!options} onOpenChange={(open) => { if (!open) settle(false); }}>
        {options && (
          <DialogContent className="bg-card border-border sm:max-w-[420px]">
            <DialogHeader>
              <DialogTitle>{options.title}</DialogTitle>
              {options.description && <DialogDescription>{options.description}</DialogDescription>}
            </DialogHeader>
            <DialogFooter className="pt-2">
              <Button type="button" variant="ghost" onClick={() => settle(false)}>
                {options.cancelLabel ?? 'Cancelar'}
              </Button>
              <Button
                type="button"
                variant={options.destructive ? 'destructive' : 'default'}
                className="px-6 font-bold"
                onClick={() => settle(true)}
              >
                {options.confirmLabel ?? 'Confirmar'}
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const ctx = React.useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm precisa estar dentro de <ConfirmProvider>');
  return ctx;
}
