import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { cn } from '@/lib/utils';

/*
 * PageHeader — anatomia única de cabeçalho de página (docs/frontend-redesign/04).
 * Título calmo (não font-black gigante) + subtítulo + slots de período e ação.
 */
interface PageHeaderProps {
  title: string;
  subtitle?: string;
  period?: ReactNode;
  action?: ReactNode;
  backTo?: string;
  className?: string;
}

export function PageHeader({ title, subtitle, period, action, backTo, className }: PageHeaderProps) {
  return (
    <header
      className={cn(
        'flex flex-col gap-4 pb-1 sm:flex-row sm:items-start sm:justify-between',
        className,
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        {backTo && (
          <Link
            to={backTo}
            aria-label="Voltar"
            className="mt-1 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground sm:text-[28px]">
            {title}
          </h1>
          {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {(period || action) && (
        <div className="flex shrink-0 items-center gap-2">
          {period}
          {action}
        </div>
      )}
    </header>
  );
}
