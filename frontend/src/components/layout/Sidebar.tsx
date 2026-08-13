import * as React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Landmark, Plus, Check, ChevronsUpDown, Users, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWorkspaces, type Workspace } from '@/hooks/use-workspaces';
import { useAuth } from '@/hooks/use-auth';
import { WorkspaceCreateDialog } from '@/components/workspace/WorkspaceCreateDialog';
import { activeNavPath, navSections } from './nav-items';
import { useIsPlatformAdmin } from '@/hooks/use-admin';
import { useWorkspaceId, workspacePath } from '@/hooks/use-workspace-id';

function useOnClickOutside(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) handler();
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [ref, handler]);
}

function WorkspaceSwitcher() {
  const { workspaces, currentWorkspace, switchWorkspace } = useWorkspaces();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [createOpen, setCreateOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  useOnClickOutside(containerRef, () => setOpen(false));

  const sharedHint = (ws: Workspace): string | null => {
    if ((ws.member_count ?? 1) <= 1) return null;
    if (ws.owner_user_id && ws.owner_user_id === user?.id) return 'Compartilhado por você';
    return ws.owner_name ? `de ${ws.owner_name}` : 'Compartilhado';
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:bg-muted"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="h-2 w-2 shrink-0 rounded-full bg-success" />
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold text-foreground">
              {currentWorkspace?.name ?? 'Selecione...'}
            </span>
            {currentWorkspace && sharedHint(currentWorkspace) && (
              <span className="flex items-center gap-1 truncate text-[11px] text-muted-foreground">
                <Users className="h-3 w-3 shrink-0" /> {sharedHint(currentWorkspace)}
              </span>
            )}
          </div>
        </div>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-2 overflow-hidden rounded-lg border border-border bg-card shadow-md animate-in fade-in slide-in-from-top-1 duration-150">
          <div className="max-h-56 overflow-y-auto py-1">
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                type="button"
                onClick={() => {
                  switchWorkspace(ws.id);
                  // Trocar de casa é NAVEGAR (ADR 0020): entra no histórico, o
                  // botão "voltar" funciona e o link é compartilhável.
                  navigate(workspacePath(ws.id, location.pathname));
                  setOpen(false);
                }}
                className={cn(
                  'flex w-full items-center justify-between gap-2 px-3 py-2 text-sm transition-colors hover:bg-muted',
                  ws.id === currentWorkspace?.id ? 'font-semibold text-brand' : 'text-foreground',
                )}
              >
                <span className="truncate text-left">{ws.name}</span>
                {ws.id === currentWorkspace?.id && <Check className="h-4 w-4 shrink-0" />}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setCreateOpen(true);
            }}
            className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-sm font-medium text-brand transition-colors hover:bg-muted"
          >
            <Plus className="h-4 w-4" /> Criar workspace
          </button>
        </div>
      )}

      <WorkspaceCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="flex items-center gap-2.5">
      <Link
        to="/settings"
        className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg p-1.5 transition-colors hover:bg-muted"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-subtle text-sm font-semibold text-brand">
          {user?.name?.[0]?.toUpperCase() ?? 'U'}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{user?.name ?? 'Usuário'}</p>
          <p className="truncate text-[11px] text-muted-foreground">{user?.email}</p>
        </div>
      </Link>
      <button
        type="button"
        onClick={() => {
          logout().finally(() => navigate('/login'));
        }}
        aria-label="Sair da conta"
        className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
      >
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );
}

export function Sidebar() {
  const location = useLocation();
  const workspaceIdAtual = useWorkspaceId();
  // Administração do site (ADR 0026): a seção só existe para quem tem o papel.
  const ehAdminDaPlataforma = useIsPlatformAdmin();
  // Um item ativo por vez: ver `activeNavPath`. O teste de prefixo por item
  // acendia Painel e Relatórios juntos, porque `/w/1/reports` começa com `/w/1`.
  const ativo = activeNavPath(location.pathname, workspaceIdAtual, ehAdminDaPlataforma);

  return (
    <aside className="sticky top-0 hidden h-screen w-[240px] shrink-0 flex-col border-r border-border bg-card md:flex">
      <div className="px-5 py-5">
        <Link to="/overview" className="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-primary-foreground">
            <Landmark className="h-5 w-5" />
          </span>
          CFv4 <span className="font-normal text-muted-foreground">Pro</span>
        </Link>
      </div>

      <div className="px-3">
        <WorkspaceSwitcher />
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-5">
        {navSections(workspaceIdAtual, ehAdminDaPlataforma).map((section) => (
          <div key={section.label} className="space-y-1">
            {/* Sem o `/70` que havia aqui: com 11px e maiúsculas, 70% de opacidade
                sobre `muted-foreground` fica abaixo do mínimo de contraste do
                WCAG AA, e o axe reprova em todas as telas — a barra lateral
                aparece em todas. No Tailwind v3 o modificador não gerava regra
                nenhuma, então o rótulo sempre foi renderizado opaco: tirar o
                `/70` mantém exatamente a aparência que o app já tem. */}
            <p className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {section.label}
            </p>
            {section.items.map((item) => {
              const active = ativo === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    'group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                    active
                      ? 'bg-brand-subtle font-medium text-brand'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )}
                >
                  {active && (
                    <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-brand" aria-hidden />
                  )}
                  <item.icon className="h-[18px] w-[18px] shrink-0" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        <UserMenu />
      </div>
    </aside>
  );
}
