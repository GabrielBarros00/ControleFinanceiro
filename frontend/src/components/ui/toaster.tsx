import * as React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToastStore, type Toast, type ToastVariant } from '@/stores/toast';

const VARIANTS: Record<ToastVariant, { border: string; icon: React.ReactNode }> = {
  success: { border: 'border-l-income', icon: <CheckCircle2 className="h-5 w-5 text-income" /> },
  error: { border: 'border-l-destructive', icon: <AlertCircle className="h-5 w-5 text-destructive" /> },
  info: { border: 'border-l-primary', icon: <Info className="h-5 w-5 text-primary" /> },
  warning: { border: 'border-l-warning', icon: <AlertTriangle className="h-5 w-5 text-warning" /> },
};

function ToastCard({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss);

  React.useEffect(() => {
    if (toast.duration <= 0) return;
    const timer = setTimeout(() => dismiss(toast.id), toast.duration);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, dismiss]);

  const v = VARIANTS[toast.variant];
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 48, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 48, scale: 0.9 }}
      transition={{ type: 'spring', stiffness: 400, damping: 30 }}
      role="status"
      className={cn(
        'pointer-events-auto flex w-80 items-start gap-3 rounded-xl border border-l-4 border-border bg-card p-4 shadow-2xl',
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
            onClick={() => { toast.action?.onClick(); dismiss(toast.id); }}
            className="mt-1 text-xs font-bold text-primary underline-offset-4 hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label="Fechar"
        onClick={() => dismiss(toast.id)}
        className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
    </motion.div>
  );
}

// Stack fixo bottom-right, acima dos modais (z-[100] > Dialog z-50). Montar 1x em App.
export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-100 flex flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} />
        ))}
      </AnimatePresence>
    </div>
  );
}
