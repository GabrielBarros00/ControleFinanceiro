import * as React from 'react';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToastStore, type Toast, type ToastVariant } from '@/stores/toast';

const VARIANTS: Record<ToastVariant, { border: string; icon: React.ReactNode }> = {
  success: { border: 'border-l-income', icon: <CheckCircle2 className="h-5 w-5 text-income" /> },
  error: { border: 'border-l-destructive', icon: <AlertCircle className="h-5 w-5 text-destructive" /> },
  info: { border: 'border-l-primary', icon: <Info className="h-5 w-5 text-primary" /> },
  warning: { border: 'border-l-warning', icon: <AlertTriangle className="h-5 w-5 text-warning" /> },
};

/** Prazo máximo da animação de saída: sem `animationend` (movimento reduzido,
 *  aba em segundo plano), o aviso sai assim mesmo. */
const SAIDA_MS = 250;

/*
 * Animação em CSS (`tailwindcss-animate`), sem o `framer-motion`.
 *
 * A biblioteca entrava na carga inicial de TODA tela — 135 KiB, 44 KiB gzip —
 * só para estes avisos (auditoria 2026-09-26, P3). A entrada é `animate-in`; a
 * saída, que o `AnimatePresence` segurava na tela, é o estado `saindo`: o aviso
 * continua montado com `animate-out` até a animação acabar, e só então sai da
 * store. Quem pede movimento reduzido não vê animação nenhuma.
 */
function ToastCard({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss);
  const [saindo, setSaindo] = React.useState(false);

  const sair = React.useCallback(() => setSaindo(true), []);

  React.useEffect(() => {
    if (toast.duration <= 0) return;
    const timer = setTimeout(sair, toast.duration);
    return () => clearTimeout(timer);
  }, [toast.duration, sair]);

  React.useEffect(() => {
    if (!saindo) return;
    const timer = setTimeout(() => dismiss(toast.id), SAIDA_MS);
    return () => clearTimeout(timer);
  }, [saindo, toast.id, dismiss]);

  const v = VARIANTS[toast.variant];
  return (
    <div
      role="status"
      onAnimationEnd={() => { if (saindo) dismiss(toast.id); }}
      className={cn(
        'pointer-events-auto flex w-80 items-start gap-3 rounded-xl border border-l-4 border-border bg-card p-4 shadow-2xl',
        'duration-200 motion-reduce:animate-none',
        saindo
          ? 'animate-out fade-out-0 slide-out-to-right-12 zoom-out-90 fill-mode-forwards'
          : 'animate-in fade-in-0 slide-in-from-right-12 zoom-in-95',
        v.border
      )}
    >
      <span className="mt-0.5 shrink-0">{v.icon}</span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-sm font-bold text-foreground">{toast.title}</p>
        {toast.description && (
          <p className="text-xs text-muted-foreground wrap-break-word">{toast.description}</p>
        )}
        {/* A ação fecha o aviso ao ser usada: deixá-lo na tela depois do
            "Desfazer" faria a pessoa clicar de novo achando que não pegou. */}
        {toast.action && (
          <button
            type="button"
            onClick={() => { toast.action?.onClick(); sair(); }}
            className="mt-1 text-xs font-bold text-primary underline-offset-4 hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label="Fechar"
        onClick={sair}
        className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

// Stack fixo bottom-right, acima dos modais (z-[100] > Dialog z-50). Montar 1x em App.
export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-100 flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} />
      ))}
    </div>
  );
}
