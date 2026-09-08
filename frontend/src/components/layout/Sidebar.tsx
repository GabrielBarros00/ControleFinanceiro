import * as React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar } from '@/components/ui/avatar';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useAuth } from '@/hooks/use-auth';
import { activeNavPath, navSections, rotuloDeEspaco } from './nav-items';
import { ScopeSwitcher } from './ScopeSwitcher';
import { useIsPlatformAdmin } from '@/hooks/use-admin';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { useAuthStore } from '@/stores';

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
        <Avatar
          name={user?.name ?? 'Usuário'}
          userId={user?.id}
          version={user?.avatar_version}
          size="sm"
        />
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
  // Só para dizer "De você" em vez de repetir o próprio nome (`rotuloDeEspaco`).
  const usuario = useAuthStore((s) => s.user);
  const espaco = workspaces.find((w) => w.id === workspaceIdAtual);
  // Um item ativo por vez: ver `activeNavPath`. O teste de prefixo por item
  // acendia Painel e Relatórios juntos, porque `/w/1/reports` começa com `/w/1`.
  const ativo = activeNavPath(location.pathname, workspaceIdAtual, ehAdminDaPlataforma);
  const secoes = navSections(workspaceIdAtual, ehAdminDaPlataforma, {
    nome: espaco?.name,
    hint: rotuloDeEspaco(espaco, usuario?.id),
  });

  /*
   * Trazer o item ativo para a vista.
   *
   * A barra tem 21 itens e ~1.100px de altura num painel de 768px — a altura de
   * um notebook comum. Medido: em `/admin` o item ativo ficava em y=1066, em
   * `/w/:id/settings` em y=969, em `/w/:id/import` em y=929. Ou seja, estando NA
   * página, nada aparecia aceso na barra — e a seção "Compartilhado" mostrava só
   * o cabeçalho, dando a entender que o espaço não tem itens.
   *
   * Duas perguntas ficavam sem resposta ao mesmo tempo: "onde estou?" e "para
   * onde posso ir?".
   *
   * `block: 'nearest'` não mexe em nada quando o item já está visível — que é o
   * caso comum. E é `useLayoutEffect` para o ajuste acontecer antes da pintura,
   * em vez de a barra dar um pulo depois de a tela aparecer.
   */
  const refDoItemAtivo = React.useRef<HTMLAnchorElement>(null);
  React.useLayoutEffect(() => {
    refDoItemAtivo.current?.scrollIntoView({ block: 'nearest' });
  }, [ativo]);

  return (
    <aside className="sticky top-0 hidden h-dvh w-[240px] shrink-0 flex-col border-r border-border bg-card md:flex">
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

      {/* `aria-label`: são DUAS navegações no app (esta e a barra inferior do
          celular), e sem nome um leitor de tela anuncia "navegação" duas vezes
          sem distinguir uma da outra. */}
      {/* A máscara de gradiente é a AFORDÂNCIA de que há mais coisa fora
          de vista. Sem ela a barra rolava, mas nada dizia isso: não há barra de
          rolagem à mostra, e o corte caía exatamente sobre um cabeçalho de
          seção, o que se lê como "esta seção está vazia".

          `mask-image` desbota as duas pontas do conteúdo; onde não há o que
          rolar, não há o que desbotar, então ela não custa nada no caso comum. */}
      <nav
        aria-label="Navegação principal"
        className="flex-1 space-y-5 overflow-y-auto px-3 py-5 [mask-image:linear-gradient(to_bottom,transparent,black_12px,black_calc(100%-12px),transparent)]"
      >
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
                  /* O item ativo era marcado só VISUALMENTE (fundo e barrinha).
                     Para tecnologia assistiva a lista era de links iguais, sem
                     nada dizendo qual é a página atual — e a barra inferior do
                     celular já fazia isso certo, então o app respondia de dois
                     jeitos à mesma pergunta. */
                  aria-current={active ? 'page' : undefined}
                  ref={active ? refDoItemAtivo : undefined}
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
