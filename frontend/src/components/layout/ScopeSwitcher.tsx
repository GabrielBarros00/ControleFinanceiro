import * as React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Check, ChevronsUpDown, Home, Plus, User } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { useWorkspaces, type Workspace } from '@/hooks/use-workspaces';
import { useWorkspaceIdFromUrl, workspacePath } from '@/hooks/use-workspace-id';
import { WorkspaceCreateDialog } from '@/components/workspace/WorkspaceCreateDialog';
import { rotuloDeMembros } from './nav-items';

/*
 * ScopeSwitcher — "onde você está" e como sair daqui.
 *
 * Este componente existe por um buraco concreto: **no celular não havia como
 * trocar de espaço**. O seletor morava dentro da `Sidebar`, que é `hidden
 * md:flex`, e o sheet "Mais" listava só destinos. Quem participa do próprio
 * espaço e de dois compartilhados ficava preso naquele em que o app abriu.
 *
 * E resolve o outro lado do mesmo problema: o app tem duas camadas (ADR 0020) —
 * pessoal, sem espaço na URL, e compartilhada, em `/w/:id` — e nada na tela do
 * celular dizia em qual delas você estava. As duas viram UMA lista só, porque
 * para quem usa não são conceitos diferentes: são lugares.
 *
 * O escopo atual sai de `useWorkspaceIdFromUrl` (o ESTRITO) e não de
 * `useWorkspaceId`: este último cai no último espaço visitado quando a rota é
 * pessoal, e era assim que a barra lateral marcava um espaço como "atual"
 * enquanto a pessoa olhava os próprios cartões.
 */

interface ScopeSwitcherProps {
  /**
   * `topbar` (celular) é compacto e transparente; `sidebar` (desktop) é o cartão
   * com borda que já existia no topo da barra lateral.
   */
  variant?: 'topbar' | 'sidebar';
  className?: string;
}

export function ScopeSwitcher({ variant = 'topbar', className }: ScopeSwitcherProps) {
  const { workspaces, currentWorkspace, switchWorkspace } = useWorkspaces();
  const workspaceDaUrl = useWorkspaceIdFromUrl();
  const navigate = useNavigate();
  const location = useLocation();
  const [aberto, setAberto] = React.useState(false);
  const [criarAberto, setCriarAberto] = React.useState(false);

  // Na camada pessoal o `currentWorkspace` continua apontando para o último
  // espaço visitado — o que importa aqui é a URL.
  const noEspaco = workspaceDaUrl !== null;
  const espacoAtual = noEspaco
    ? workspaces.find((w) => w.id === workspaceDaUrl) ?? currentWorkspace
    : null;

  const irParaPessoal = () => {
    setAberto(false);
    navigate('/overview');
  };

  const irParaEspaco = (ws: Workspace) => {
    setAberto(false);
    switchWorkspace(ws.id);
    // Trocar de espaço é NAVEGAR (ADR 0020): entra no histórico, o botão
    // "voltar" funciona e o link é compartilhável. `workspacePath` preserva a
    // subrota, então quem está em Lançamentos continua em Lançamentos.
    navigate(workspacePath(ws.id, location.pathname));
  };

  const rotulo = noEspaco ? (espacoAtual?.name ?? 'Espaço') : 'Pessoal';
  const apoio = noEspaco ? rotuloDeMembros(espacoAtual?.member_count) : 'Só você vê';
  const Icone = noEspaco ? Home : User;

  return (
    <>
      <button
        type="button"
        onClick={() => setAberto(true)}
        aria-haspopup="dialog"
        aria-expanded={aberto}
        className={cn(
          'flex min-w-0 items-center gap-2 text-left transition-colors',
          variant === 'sidebar'
            ? 'w-full justify-between rounded-lg border border-border bg-card px-3 py-2.5 hover:bg-muted'
            : 'h-10 max-w-[62vw] rounded-lg px-2 hover:bg-muted',
          className,
        )}
      >
        <span
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-md',
            noEspaco ? 'bg-brand-subtle text-brand' : 'bg-muted text-muted-foreground',
          )}
        >
          <Icone className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-foreground">{rotulo}</span>
          {apoio && (
            <span className="block truncate text-[11px] text-muted-foreground">{apoio}</span>
          )}
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </button>

      <Dialog open={aberto} onOpenChange={setAberto}>
        <DialogContent className="sm:max-w-sm">
          <DialogTitle className="text-base">Onde você está</DialogTitle>
          <DialogDescription className="sr-only">
            Escolha entre as suas finanças pessoais e os espaços compartilhados de que você
            participa.
          </DialogDescription>

          <div className="space-y-4">
            <Secao rotulo="Pessoal">
              <Linha
                icone={User}
                titulo="Suas finanças"
                apoio="Rendas, cartões e o seu resultado do mês"
                ativo={!noEspaco}
                onClick={irParaPessoal}
              />
            </Secao>

            <Secao rotulo={workspaces.length > 0 ? 'Compartilhado' : 'Espaços'}>
              {workspaces.length === 0 ? (
                <p className="px-1 text-sm text-muted-foreground">
                  Você ainda não participa de nenhum espaço.
                </p>
              ) : (
                workspaces.map((ws) => (
                  <Linha
                    key={ws.id}
                    icone={Home}
                    titulo={ws.name}
                    apoio={rotuloDeMembros(ws.member_count) ?? undefined}
                    ativo={noEspaco && ws.id === workspaceDaUrl}
                    onClick={() => irParaEspaco(ws)}
                  />
                ))
              )}
            </Secao>

            <button
              type="button"
              onClick={() => {
                setAberto(false);
                setCriarAberto(true);
              }}
              className="flex w-full items-center gap-2 rounded-xl border border-dashed border-border px-3 py-3 text-sm font-medium text-brand transition-colors hover:bg-muted"
            >
              <Plus className="h-4 w-4" /> Criar espaço
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <WorkspaceCreateDialog open={criarAberto} onOpenChange={setCriarAberto} />
    </>
  );
}

function Secao({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {rotulo}
      </p>
      {children}
    </div>
  );
}

function Linha({
  icone: Icone,
  titulo,
  apoio,
  ativo,
  onClick,
}: {
  icone: typeof Home;
  titulo: string;
  apoio?: string;
  ativo: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={ativo ? 'true' : undefined}
      className={cn(
        // min-h-14: é uma lista tocada com o polegar, não um menu de ponteiro.
        'flex min-h-14 w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors',
        ativo ? 'bg-brand-subtle text-brand' : 'hover:bg-muted',
      )}
    >
      <span
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
          ativo ? 'bg-brand text-primary-foreground' : 'bg-muted text-muted-foreground',
        )}
      >
        <Icone className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            'block truncate text-sm font-medium',
            ativo ? 'text-brand' : 'text-foreground',
          )}
        >
          {titulo}
        </span>
        {apoio && <span className="block truncate text-xs text-muted-foreground">{apoio}</span>}
      </span>
      {ativo && <Check className="h-4 w-4 shrink-0" />}
    </button>
  );
}
