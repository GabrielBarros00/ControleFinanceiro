import * as React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Plus, MoreHorizontal, LogOut } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { activeNavPath, navFlat, mobilePrimaryPaths, type NavItem } from './nav-items';
import { useWorkspaceId, useWorkspaceIdFromUrl } from '@/hooks/use-workspace-id';
import { useNewTxStore } from '@/stores';
import { useAuth } from '@/hooks/use-auth';


/**
 * Gaveta "Mais" da navegação inferior.
 *
 * Era um `<div role="dialog" aria-modal="true">` feito à mão, e "à mão" custava
 * tudo o que um diálogo precisa ter: nenhum nome acessível (o leitor de tela
 * anunciava "diálogo" e mais nada), nenhum focus trap (o Tab saía para a página
 * atrás), nenhum Escape, nenhuma devolução de foco ao fechar, nenhuma trava de
 * rolagem, e um overlay que era `<div onClick>` — inalcançável por teclado.
 *
 * O `DialogContent` do projeto (Radix) entrega os seis, e o estilo dele em
 * mobile JÁ é um bottom sheet — não houve o que redesenhar.
 */
function MoreSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const workspaceId = useWorkspaceId();
  const itens = navFlat(workspaceId);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="border-t border-border p-4 pb-8 md:hidden sm:max-w-none"
      >
        {/* O título é obrigatório: sem ele o Radix emite um erro em console que
            a suíte de a11y trata como falha dura — e, antes disso, é o nome que
            o leitor de tela anuncia. `sr-only` porque a gaveta é visual. */}
        <DialogTitle className="sr-only">Mais opções de navegação</DialogTitle>
        <DialogDescription className="sr-only">
          Todas as seções do aplicativo e a opção de sair da conta.
        </DialogDescription>
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-muted" />
        <div className="grid grid-cols-3 gap-2">
          {itens.map((item) => {
            const active = activeNavPath(location.pathname, workspaceId) === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => onOpenChange(false)}
                className={cn(
                  'flex flex-col items-center gap-1.5 rounded-xl p-3 text-xs',
                  active ? 'bg-brand-subtle text-brand' : 'text-muted-foreground hover:bg-muted',
                )}
              >
                <item.icon className="h-5 w-5" />
                {item.label}
              </Link>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => logout().finally(() => navigate('/login'))}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-border py-3 text-sm font-medium text-destructive"
        >
          <LogOut className="h-4 w-4" /> Sair da conta
        </button>
      </DialogContent>
    </Dialog>
  );
}

export function BottomNav() {
  const location = useLocation();
  const setNewTxOpen = useNewTxStore((s) => s.setOpen);
  const [moreOpen, setMoreOpen] = React.useState(false);
  const workspaceId = useWorkspaceId();
  // Estrito, sem o fallback da store: é ele que decide se DÁ para lançar aqui.
  const workspaceDaUrl = useWorkspaceIdFromUrl();
  const itens = navFlat(workspaceId);
  const primary = mobilePrimaryPaths(workspaceId)
    .map((p) => itens.find((i) => i.to === p))
    .filter((i): i is NavItem => Boolean(i));

  const item = (nav: NavItem) => (
    <Link
      key={nav.to}
      to={nav.to}
      className={cn(
        'flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px]',
        activeNavPath(location.pathname, workspaceId) === nav.to
          ? 'text-brand'
          : 'text-muted-foreground',
      )}
    >
      <nav.icon className="h-5 w-5" />
      {nav.label}
    </Link>
  );

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border bg-card/95 px-2 backdrop-blur md:hidden">
        {primary.slice(0, 2).map(item)}
        {/* O FAB só existe DENTRO de um workspace. Fora dele — na Visão global,
            em `/me/*` — ele abria o diálogo com o último workspace visitado, sem
            mostrar qual, e a despesa ia para a casa errada. O ADR 0020 define a
            visão global como somente leitura por esse motivo, e a suíte de
            acessibilidade afirmava isso testando só o desktop, onde o FAB está
            escondido por `md:hidden` e o problema não aparecia. */}
        {workspaceDaUrl !== null && (
          <button
            type="button"
            onClick={() => setNewTxOpen(true)}
            aria-label="Nova despesa"
            className="mx-1 -mt-5 flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand text-primary-foreground shadow-lg"
          >
            <Plus className="h-6 w-6" />
          </button>
        )}
        {primary.slice(2).map(item)}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={moreOpen}
          className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] text-muted-foreground"
        >
          <MoreHorizontal className="h-5 w-5" />
          Mais
        </button>
      </nav>
      <MoreSheet open={moreOpen} onOpenChange={setMoreOpen} />
    </>
  );
}
