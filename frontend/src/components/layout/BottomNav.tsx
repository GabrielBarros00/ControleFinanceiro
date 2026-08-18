import * as React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Plus, MoreHorizontal, LogOut } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { activeNavPath, navSections, navFlat, mobilePrimaryPaths, type NavItem } from './nav-items';
import { useWorkspaceId, useWorkspaceIdFromUrl } from '@/hooks/use-workspace-id';
import { useNewTxStore } from '@/stores';
import { useAuth } from '@/hooks/use-auth';
import { useIsPlatformAdmin } from '@/hooks/use-admin';
import { useWorkspaces } from '@/hooks/use-workspaces';


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
 *
 * ## O que mudou nesta rodada, e por quê
 *
 * A gaveta chamava `navFlat()`, que **descarta os rótulos de seção**, e
 * despejava os quinze destinos numa grade de 3 colunas. O resultado era a queixa
 * literal de quem usa: não dá para saber qual é qual. "Acertos" e "Seus
 * acertos", "Relatórios" e "Seus relatórios", "Configurações" e "Suas
 * configurações" apareciam lado a lado, mesmo ícone, mesma cor, sem nada dizendo
 * que um é do espaço compartilhado e o outro é seu — a hierarquia que a barra
 * lateral do desktop tem e o celular não tinha.
 *
 * Agora usa `navSections()`, com cabeçalho por seção, e em LINHAS em vez de
 * grade: "Financiamentos" e "Suas configurações" não cabiam numa coluna de
 * ~110px a `text-xs` e saíam truncados ou espremidos em duas linhas.
 *
 * E passa `isPlatformAdmin`: a chamada omitia o argumento, então o item
 * "Administração" — que só existe nesta gaveta, no celular — nunca aparecia para
 * quem tem o papel. O default `false` do parâmetro escondia o defeito.
 */
function MoreSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const workspaceId = useWorkspaceId();
  const ehAdminDaPlataforma = useIsPlatformAdmin();
  const { workspaces } = useWorkspaces();
  const espaco = workspaces.find((w) => w.id === workspaceId);
  const secoes = navSections(workspaceId, ehAdminDaPlataforma, {
    nome: espaco?.name,
    membros: espaco?.member_count,
  });
  const ativo = activeNavPath(location.pathname, workspaceId, ehAdminDaPlataforma);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="max-h-[85vh] md:hidden sm:max-w-none"
      >
        {/* O título é obrigatório: sem ele o Radix emite um erro em console que
            a suíte de a11y trata como falha dura — e, antes disso, é o nome que
            o leitor de tela anuncia. `sr-only` porque a gaveta é visual. */}
        <DialogTitle className="sr-only">Mais opções de navegação</DialogTitle>
        <DialogDescription className="sr-only">
          Todas as seções do aplicativo e a opção de sair da conta.
        </DialogDescription>
        <div className="mx-auto mb-1 h-1 w-10 shrink-0 rounded-full bg-muted" />

        <div className="min-h-0 space-y-5 overflow-y-auto">
          {secoes.map((secao) => (
            <div key={secao.label} className="space-y-1">
              <p className="px-1 text-[11px] font-medium text-muted-foreground">
                <span className="uppercase tracking-wide">{secao.label}</span>
                {(secao.subject || secao.hint) && (
                  <span className="block truncate">
                    {[secao.subject, secao.hint].filter(Boolean).join(' · ')}
                  </span>
                )}
              </p>
              {secao.items.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={() => onOpenChange(false)}
                  aria-current={ativo === item.to ? 'page' : undefined}
                  className={cn(
                    'flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm',
                    ativo === item.to
                      ? 'bg-brand-subtle font-medium text-brand'
                      : 'text-foreground hover:bg-muted',
                  )}
                >
                  <item.icon className="h-[18px] w-[18px] shrink-0" />
                  {item.label}
                </Link>
              ))}
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={() => logout().finally(() => navigate('/login'))}
          className="flex min-h-12 w-full shrink-0 items-center justify-center gap-2 rounded-xl border border-border text-sm font-medium text-destructive"
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
      aria-current={activeNavPath(location.pathname, workspaceId) === nav.to ? 'page' : undefined}
      className={cn(
        'flex min-h-[52px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-center text-[11px] leading-tight',
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
      {/* `pb-safe`: a barra é `fixed bottom-0`, então sem a área segura os
          rótulos ficam sob o indicador de home do iPhone e sob a barra de
          gestos do Android — legíveis pela metade e difíceis de acertar. */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex items-stretch justify-around border-t border-border bg-card/95 px-1 pb-safe backdrop-blur-sm md:hidden">
        {primary.slice(0, 2).map(item)}
        {/* O FAB só existe DENTRO de um espaço. Fora dele — no Seu mês,
            em `/me/*` — ele abria o diálogo com o último espaço visitado, sem
            mostrar qual, e a despesa ia para o lugar errado. O ADR 0020 define a
            camada pessoal como somente leitura por esse motivo, e a suíte de
            acessibilidade afirmava isso testando só o desktop, onde o FAB está
            escondido por `md:hidden` e o problema não aparecia. */}
        {workspaceDaUrl !== null && (
          <button
            type="button"
            onClick={() => setNewTxOpen(true)}
            aria-label="Nova despesa"
            className="mx-1 my-2 -mt-5 flex h-12 w-12 shrink-0 items-center justify-center self-start rounded-full bg-brand text-primary-foreground shadow-lg"
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
          className="flex min-h-[52px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] leading-tight text-muted-foreground"
        >
          <MoreHorizontal className="h-5 w-5" />
          Mais
        </button>
      </nav>
      <MoreSheet open={moreOpen} onOpenChange={setMoreOpen} />
    </>
  );
}
