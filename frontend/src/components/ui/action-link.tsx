import * as React from 'react';
import { Loader2 } from 'lucide-react';

import { useAcaoPendente } from '@/hooks/use-acao-pendente';
import { cn } from '@/lib/utils';

type ActionLinkProps = Omit<React.ComponentPropsWithoutRef<'button'>, 'onClick'> & {
  /** Pode devolver uma promessa: o gatilho se tranca até ela assentar. */
  onClick?: (evento: React.MouseEvent<HTMLButtonElement>) => unknown;
};

/**
 * Gatilho de ação com cara de link — e com a mesma trava do `Button`.
 *
 * Alguns comandos do app não podem virar `<Button>` sem brigar com o layout:
 * "Marcar todas como lidas" no topo do sino, "Marcar como lida" dentro de cada
 * linha da lista. Eram `<button>` crus, e por isso ficavam de fora do único
 * lugar que trava duplo clique.
 *
 * Não vale trocar por `<Button variant="link">`: aqueles têm altura mínima,
 * padding e `gap` de botão, que quebram a linha da notificação. O que precisa
 * ser compartilhado é o COMPORTAMENTO, não a aparência — e é o que este
 * componente compartilha, via `useAcaoPendente`.
 */
export function ActionLink({ onClick, className, children, disabled, ...props }: ActionLinkProps) {
  const { disparar, pendente } = useAcaoPendente(onClick);

  return (
    <button
      type="button"
      onClick={disparar}
      disabled={disabled || pendente}
      aria-busy={pendente || undefined}
      className={cn(
        'inline-flex items-center gap-1 disabled:cursor-default disabled:opacity-60',
        className,
      )}
      {...props}
    >
      {pendente ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
