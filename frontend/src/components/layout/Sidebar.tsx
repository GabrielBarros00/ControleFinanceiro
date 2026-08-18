import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useAuth } from '@/hooks/use-auth';
import { activeNavPath, navSections } from './nav-items';
import { ScopeSwitcher } from './ScopeSwitcher';
import { useIsPlatformAdmin } from '@/hooks/use-admin';
import { useWorkspaceId } from '@/hooks/use-workspace-id';

function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="flex items-center gap-2.5">
      {/* `/me/settings`, não `/settings`: o alias legado cai no
          `RedirectParaWorkspace` e leva às configurações DO ESPAÇO (membros,
          categorias) — quem clica no próprio nome e avatar espera perfil,
          senha e aparência, que são pessoais (ADR 0021). */}
      <Link
        to="/me/settings"
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
  const { workspaces } = useWorkspaces();
  const espaco = workspaces.find((w) => w.id === workspaceIdAtual);
  // Um item ativo por vez: ver `activeNavPath`. O teste de prefixo por item
  // acendia Painel e Relatórios juntos, porque `/w/1/reports` começa com `/w/1`.
  const ativo = activeNavPath(location.pathname, workspaceIdAtual, ehAdminDaPlataforma);
  const secoes = navSections(workspaceIdAtual, ehAdminDaPlataforma, {
    nome: espaco?.name,
    membros: espaco?.member_count,
  });

  return (
    <aside className="sticky top-0 hidden h-screen w-[240px] shrink-0 flex-col border-r border-border bg-card md:flex">
      <div className="px-4 py-5">
        {/* O nome por extenso não cabe em 240px a `text-lg`: 15px com
            `whitespace-nowrap` mantém a marca em uma linha só, sem estourar a
            barra nem quebrar "Controle / Financeiro" no meio. */}
        <Link
          to="/overview"
          className="flex items-center gap-2 whitespace-nowrap text-[15px] font-semibold tracking-tight text-foreground"
        >
          <img src="/sidebar_icon.png" alt="" aria-hidden="true" className="h-8 w-8 shrink-0 rounded-lg" />
          Controle Financeiro
        </Link>
      </div>

      <div className="px-3">
        {/* Mesmo componente do celular: o seletor de ANTES só listava espaços,
            então a camada pessoal — que é metade do app — não aparecia nele. */}
        <ScopeSwitcher variant="sidebar" />
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-5">
        {secoes.map((section) => (
          <div key={section.label} className="space-y-1">
            {/* Sem o `/70` que havia aqui: com 11px e maiúsculas, 70% de opacidade
                sobre `muted-foreground` fica abaixo do mínimo de contraste do
                WCAG AA, e o axe reprova em todas as telas — a barra lateral
                aparece em todas. */}
            <p className="px-3 pb-1 text-[11px] font-medium text-muted-foreground">
              <span className="block truncate uppercase tracking-wide">{section.label}</span>
              {(section.subject || section.hint) && (
                <span className="block truncate">
                  {[section.subject, section.hint].filter(Boolean).join(' · ')}
                </span>
              )}
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
