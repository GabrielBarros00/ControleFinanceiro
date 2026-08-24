import { Navigate, Outlet, useParams } from 'react-router-dom';
import * as React from 'react';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useUIStore } from '@/stores';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Porteiro de `/w/:workspaceId/*` (ADR 0020).
 *
 * Confere que o id da URL é um workspace de que o usuário PARTICIPA antes de
 * qualquer tela montar. Fecha um buraco que o `localStorage` tinha: o id ficava
 * guardado para sempre, então quem fosse removido de um workspace continuava com
 * o app apontado para ele — a tela ficava num ciclo de 403 sem explicar nada, e
 * um "Nova despesa" ali dava erro sem dizer por quê.
 *
 * Também mantém o "último visitado" em dia, que é o que decide para onde `/`
 * redireciona.
 */
export function WorkspaceGuard() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { workspaces, isLoading, isError, refetch } = useWorkspaces();
  const setCurrentWorkspaceId = useUIStore((s) => s.setCurrentWorkspaceId);

  const id = Number(workspaceId);
  const valido = Number.isInteger(id) && id > 0;
  const pertence = valido && workspaces.some((w) => w.id === id);

  React.useEffect(() => {
    if (pertence) setCurrentWorkspaceId(id);
  }, [pertence, id, setCurrentWorkspaceId]);

  // Esperar a lista é essencial: decidir com ela vazia mandaria todo mundo para
  // /overview no primeiro carregamento.
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // Erro NÃO é "não pertenço". A lista vem de `listQuery.data ?? []`, então uma
  // falha de rede chegava aqui indistinguível de uma resposta legítima vazia — e
  // o `Navigate` abaixo ejetava a pessoa do espaço em que ela estava, sem dizer
  // nada, por causa de um backend que piscou. Redirecionar é irreversível pela
  // tela (o link some do histórico com `replace`); errar para o lado de mostrar o
  // problema com um botão de tentar de novo custa um clique.
  if (isError) {
    return (
      <ErrorState
        title="Não foi possível carregar seus espaços"
        message="Verifique a conexão e tente de novo. Seus dados continuam aqui."
        onRetry={refetch}
      />
    );
  }

  if (!pertence) return <Navigate to="/overview" replace />;

  return <Outlet />;
}
