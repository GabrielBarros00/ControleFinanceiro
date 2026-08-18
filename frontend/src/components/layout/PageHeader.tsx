import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ScopeBadge } from './ScopeBadge';

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
  /**
   * Marca a camada a que a tela pertence (ADR 0020): `personal` soma todos os
   * espaços e só você vê; `workspace` é somente este espaço. Informe nas telas
   * que têm par homônimo na outra camada — é o que evita ler "Acertos" achando
   * que é "Seus acertos".
   */
  scope?: 'personal' | 'workspace';
  className?: string;
}

export function PageHeader({ title, subtitle, period, action, backTo, scope, className }: PageHeaderProps) {
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
            className="-ml-1 mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
        )}
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <h1 className="min-w-0 truncate text-2xl font-semibold tracking-tight text-foreground sm:text-[28px]">
              {title}
            </h1>
            {scope && <ScopeBadge scope={scope} />}
          </div>
          {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {(period || action) && (
        /*
         * `flex-wrap` + `min-w-0`, e NÃO `shrink-0`.
         *
         * Com `shrink-0` sem quebra de linha, este bloco não podia nem encolher
         * nem descer: em Rendas ele soma PeriodPicker (196px) + "Lançar
         * pendentes" + "Nova renda" ≈ 490px numa faixa útil de 328px a 360px de
         * tela, e o excesso virava rolagem HORIZONTAL na página inteira — o
         * `Button` tem `whitespace-nowrap`, então o texto também não quebrava.
         *
         * Não era a causa ISOLADA, e isso foi medido: revertendo só esta linha,
         * `mobile_layout.mobile.spec.ts` continua verde. O estouro exige as três
         * peças juntas — este `shrink-0`, o `min-w-[132px]` do `PeriodPicker` e
         * o bloco de ações da própria tela sem `flex-wrap`. Reverter as três
         * derruba o teste com "/me/income rola 163px". As três continuam
         * corrigidas: qualquer uma sozinha volta a apertar a faixa quando
         * aparecer uma ação com rótulo mais longo.
         */
        <div className="flex min-w-0 flex-wrap items-center gap-2 sm:justify-end">
          {period}
          {action}
        </div>
      )}
    </header>
  );
}
