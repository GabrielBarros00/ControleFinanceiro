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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  /**
   * Exige digitar exatamente este texto para liberar a confirmação.
   *
   * Para o que é irreversível e grande. Excluir um espaço apaga o histórico
   * financeiro COMPARTILHADO de todo mundo que participa dele, e até aqui tinha
   * a mesma proteção de apagar um café de R$ 12,50: um sim/não. Um gesto
   * deliberado é o que separa "eu quis" de "eu cliquei sem ler".
   */
  exigirDigitar?: string;
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

  const [digitado, setDigitado] = React.useState('');

  const settle = React.useCallback((result: boolean) => {
    resolverRef.current?.(result);
    resolverRef.current = null;
    setOptions(null);
    setDigitado('');
  }, []);

  const travadoPelaDigitacao =
    !!options?.exigirDigitar && digitado.trim() !== options.exigirDigitar;

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
            {options.exigirDigitar && (
              <div className="space-y-2">
                <Label htmlFor="confirmar-digitando" className="text-xs font-normal text-muted-foreground">
                  Para confirmar, digite <span className="font-semibold text-foreground">{options.exigirDigitar}</span>
                </Label>
                <Input
                  id="confirmar-digitando"
                  autoFocus
                  value={digitado}
                  onChange={(e) => setDigitado(e.target.value)}
                  placeholder={options.exigirDigitar}
                />
              </div>
            )}
            <DialogFooter className="pt-2">
              <Button type="button" variant="ghost" onClick={() => settle(false)}>
                {options.cancelLabel ?? 'Cancelar'}
              </Button>
              <Button
                type="button"
                variant={options.destructive ? 'destructive' : 'default'}
                className="px-6 font-bold"
                disabled={travadoPelaDigitacao}
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
