import * as React from 'react';
import { cn } from '@/lib/utils';
import { urlDoAvatar } from '@/lib/avatar';

/*
 * Avatar — a foto de alguém, ou a inicial do nome quando não há foto.
 *
 * Existe porque o mesmo círculo estava escrito à mão em SETE lugares (barra
 * lateral, perfil, lista de membros, avatares empilhados da divisão, cartões de
 * saldo, extrato mensal e chips de divisão simples), cada um com um tamanho e
 * uma cor de fundo próprios, e nenhum deles sabia exibir imagem. Acrescentar a
 * foto de perfil sem unificar seria acrescentá-la sete vezes — e as duas ou três
 * que ficassem para trás continuariam mostrando a letra para sempre.
 *
 * `iniciais` aceita 1 ou 2 letras porque as telas divergiam de propósito: onde
 * cabe pouco (`h-6`), uma letra; no extrato de dívidas, duas, que distinguem
 * "Ana" de "André".
 */

const TAMANHOS = {
  xs: 'h-6 w-6 text-[10px]',
  sm: 'h-8 w-8 text-xs',
  md: 'h-9 w-9 text-sm',
  lg: 'h-10 w-10 text-sm',
  xl: 'h-20 w-20 text-3xl',
} as const;

export type AvatarSize = keyof typeof TAMANHOS;

interface AvatarProps {
  /** Nome da pessoa — de onde saem as iniciais e o texto alternativo. */
  name?: string | null;
  userId?: number | null;
  /** Token de cache vindo da API (`avatar_version`). Sem ele, não há foto. */
  version?: string | null;
  size?: AvatarSize;
  /** Quantas letras usar quando não há foto. */
  letras?: 1 | 2;
  className?: string;
  title?: string;
}

export function Avatar({
  name,
  userId,
  version,
  size = 'md',
  letras = 1,
  className,
  title,
}: AvatarProps) {
  const src = urlDoAvatar(userId, version);
  // Uma foto que falha ao carregar (volume fora do ar, sessão perdida) tem de
  // cair para a inicial em vez de deixar o ícone de imagem quebrada — que é
  // pior que nunca ter havido foto.
  const [falhou, setFalhou] = React.useState(false);
  React.useEffect(() => setFalhou(false), [src]);

  const inicial = (name ?? '').trim().slice(0, letras).toUpperCase() || '?';
  const base = cn(
    'shrink-0 overflow-hidden rounded-full',
    TAMANHOS[size],
    className,
  );

  if (src && !falhou) {
    return (
      <img
        src={src}
        alt={name ? `Foto de ${name}` : 'Foto de perfil'}
        title={title ?? name ?? undefined}
        onError={() => setFalhou(true)}
        className={cn(base, 'object-cover')}
        // A imagem é sempre um quadrado de 256px vindo do nosso domínio; o
        // navegador não precisa adiar nada nem negociar CORS.
        loading="lazy"
        decoding="async"
      />
    );
  }

  return (
    <span
      title={title ?? name ?? undefined}
      aria-hidden={!title}
      className={cn(
        base,
        'flex items-center justify-center bg-brand-subtle font-semibold text-brand',
      )}
    >
      {inicial}
    </span>
  );
}
