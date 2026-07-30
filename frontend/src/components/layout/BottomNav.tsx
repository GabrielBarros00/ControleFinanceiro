import * as React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Plus, MoreHorizontal, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { navFlat, mobilePrimaryPaths, type NavItem } from './nav-items';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { useNewTxStore } from '@/stores';
import { useAuth } from '@/hooks/use-auth';

const isActivePath = (pathname: string, to: string) =>
  pathname === to || pathname.startsWith(`${to}/`);

function MoreSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const workspaceId = useWorkspaceId();
  const itens = navFlat(workspaceId);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] md:hidden" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-foreground/20 animate-in fade-in" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-border bg-card p-4 pb-8 shadow-lg animate-in slide-in-from-bottom duration-200">
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-muted" />
        <div className="grid grid-cols-3 gap-2">
          {itens.map((item) => {
            const active = isActivePath(location.pathname, item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={onClose}
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
      </div>
    </div>
  );
}

export function BottomNav() {
  const location = useLocation();
  const setNewTxOpen = useNewTxStore((s) => s.setOpen);
  const [moreOpen, setMoreOpen] = React.useState(false);
  const workspaceId = useWorkspaceId();
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
        isActivePath(location.pathname, nav.to) ? 'text-brand' : 'text-muted-foreground',
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
        <button
          type="button"
          onClick={() => setNewTxOpen(true)}
          aria-label="Nova despesa"
          className="mx-1 -mt-5 flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand text-primary-foreground shadow-lg"
        >
          <Plus className="h-6 w-6" />
        </button>
        {primary.slice(2).map(item)}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] text-muted-foreground"
        >
          <MoreHorizontal className="h-5 w-5" />
          Mais
        </button>
      </nav>
      <MoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} />
    </>
  );
}
