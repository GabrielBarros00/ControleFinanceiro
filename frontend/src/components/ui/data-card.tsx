import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { useIsMobile } from '@/hooks/use-media-query';

/*
 * DataCard — uma LINHA de tabela em formato de cartão, para o celular.
 *
 * Toda tabela larga do app (amortização com 7 colunas, pessoas do /admin com 7,
 * despesas do mês com 5, rendas, recorrência) vivia dentro do `overflow-auto` do
 * `ui/table.tsx`. Tecnicamente rolava; na prática a coluna de VALOR — a única
 * que a pessoa foi ali ver — ficava fora da tela, sem nenhuma pista de que havia
 * mais à direita, e arrastar na horizontal dentro de um cartão disputa com o
 * gesto de rolar a página.
 *
 * Use com `CardsOrTable` (abaixo). A tabela do desktop fica intocada; este
 * componente existe para as cinco telas não inventarem cinco cartões
 * diferentes.
 */

export interface DataCardField {
  label: string;
  value: ReactNode;
  /** Ocupa a linha inteira em vez de metade da grade. */
  full?: boolean;
}

interface DataCardProps {
  title: ReactNode;
  /** Linha secundária sob o título (data, categoria, quem pagou…). */
  meta?: ReactNode;
  /** Número em destaque, alinhado à direita do título. */
  value?: ReactNode;
  /** Selo de estado — pago, pendente, atrasado. */
  badge?: ReactNode;
  /** Pares rótulo/valor, em duas colunas. */
  fields?: DataCardField[];
  /** Botões, na base do cartão. */
  actions?: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function DataCard({
  title, meta, value, badge, fields, actions, onClick, className,
}: DataCardProps) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      {...(onClick ? { type: 'button' as const, onClick } : {})}
      className={cn(
        'w-full rounded-xl border border-border bg-card p-3 text-left',
        onClick && 'transition-colors hover:bg-muted/50',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="min-w-0 break-words text-sm font-medium text-foreground">{title}</span>
            {badge}
          </div>
          {meta && <p className="mt-0.5 break-words text-xs text-muted-foreground">{meta}</p>}
        </div>
        {value && <div className="shrink-0 text-right">{value}</div>}
      </div>

      {fields && fields.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-border pt-3">
          {fields.map((f, i) => (
            <div key={i} className={cn('min-w-0', f.full && 'col-span-2')}>
              <dt className="text-[11px] text-muted-foreground">{f.label}</dt>
              <dd className="break-words text-sm text-foreground">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {actions && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {actions}
        </div>
      )}
    </Tag>
  );
}

/**
 * O par "cartões no celular / tabela no desktop".
 *
 * Renderiza UM dos dois, via `useIsMobile` — não os dois com `sm:hidden` e
 * `hidden sm:block`. Duas razões, e a primeira é a que decide:
 *
 * 1. **Conteúdo duplicado no DOM.** Cada pessoa, cada parcela e cada despesa
 *    passaria a existir duas vezes, com os mesmos rótulos acessíveis e os mesmos
 *    `aria-label`. Não é teórico: ao tentar o caminho do CSS, dez testes
 *    quebraram de uma vez com "Found multiple elements with the text" — no
 *    jsdom não há layout, então `hidden` não esconde de ninguém. O que os testes
 *    encontraram é o que um leitor de tela encontraria se a regra de CSS falhasse
 *    por qualquer motivo.
 * 2. Ponto de corte único: se estivesse escrito à mão em cinco telas, bastaria
 *    alguém trocar `sm:` por `md:` numa delas para existir uma faixa de largura
 *    sem tabela e sem cartão que ninguém testa.
 */
export function CardsOrTable({ cards, table }: { cards: ReactNode; table: ReactNode }) {
  const isMobile = useIsMobile();
  return <>{isMobile ? cards : table}</>;
}
