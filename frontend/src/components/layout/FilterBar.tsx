import * as React from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogTitle,
} from '@/components/ui/dialog';
import { useIsMobile } from '@/hooks/use-media-query';
import { cn } from '@/lib/utils';

/*
 * FilterBar — filtros em linha no desktop, numa gaveta no celular.
 *
 * Em Lançamentos os controles são busca + três selects; no Extrato são seis
 * chips de origem + dois selects. Abaixo de `sm` eles empilham em largura
 * total: são ~210px e ~260px de filtros ANTES da primeira linha de dados, numa
 * tela de 844px de altura. A pessoa abre "Lançamentos" e não vê lançamento
 * nenhum sem rolar.
 *
 * A gaveta troca isso por um botão de uma linha que ainda diz quantos filtros
 * estão ativos — informação que a versão empilhada dava só a quem lesse os três
 * selects.
 *
 * Renderiza os filhos UMA vez (por isso `useIsMobile`, e não `sm:hidden` em duas
 * cópias): são campos de formulário com `id` e `label`, e duas cópias fariam
 * dois rótulos apontarem para o mesmo `id`.
 */
interface FilterBarProps {
  /** Quantos filtros estão ativos — vai no selo do botão. */
  ativos?: number;
  /** Sempre visível, fora da gaveta (a busca costuma ser o filtro principal). */
  destaque?: React.ReactNode;
  onLimpar?: () => void;
  children: React.ReactNode;
  className?: string;
}

export function FilterBar({ ativos = 0, destaque, onLimpar, children, className }: FilterBarProps) {
  const isMobile = useIsMobile();
  const [aberto, setAberto] = React.useState(false);

  if (!isMobile) {
    return (
      <div className={cn('flex flex-wrap items-center gap-3', className)}>
        {destaque}
        {children}
      </div>
    );
  }

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {destaque}
      <Button
        type="button"
        variant="outline"
        onClick={() => setAberto(true)}
        className="h-10 w-full justify-center gap-2"
      >
        <SlidersHorizontal className="h-4 w-4" />
        Filtros
        {ativos > 0 && (
          <span className="ml-1 rounded-full bg-brand px-1.5 py-0.5 text-[11px] font-semibold text-primary-foreground">
            {ativos}
          </span>
        )}
      </Button>

      <Dialog open={aberto} onOpenChange={setAberto}>
        <DialogContent>
          <DialogTitle className="text-base">Filtros</DialogTitle>
          <DialogDescription className="sr-only">
            Refine a lista por método de pagamento, categoria e outros critérios.
          </DialogDescription>
          <div className="space-y-3">{children}</div>
          <div className="flex gap-2">
            {onLimpar && ativos > 0 && (
              <Button
                type="button"
                variant="outline"
                className="h-11 flex-1"
                onClick={() => {
                  onLimpar();
                  setAberto(false);
                }}
              >
                Limpar
              </Button>
            )}
            <Button type="button" className="h-11 flex-1" onClick={() => setAberto(false)}>
              Ver resultados
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
