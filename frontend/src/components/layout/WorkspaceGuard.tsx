import { Navigate, Outlet, useParams } from 'react-router-dom';
import * as React from 'react';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useUIStore } from '@/stores';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from '@/stores/toast';

/**
 * Redireciona para o Início e conta o que aconteceu.
 *
 * O aviso sai num efeito, e não no corpo do componente: disparar um toast
 * durante a renderização atualiza o store de outro componente no meio do render
 * do React, o que é justamente o que ele proíbe.
 */
function RedirecionaAvisando({ valido }: { valido: boolean }) {
  React.useEffect(() => {
    if (valido) {
      toast.info(
        'Você não tem acesso a este espaço',
        'Ou ele foi excluído, ou você deixou de ser membro dele.',
      );
    } else {
      toast.info('Espaço não encontrado', 'O endereço não corresponde a nenhum espaço seu.');
    }
  }, [valido]);
  return <Navigate to="/overview" replace />;
}

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
  //
  // O esqueleto tem FORMA de página, e não é decoração: antes eram dois
  // retângulos cinzas soltos, sem título e sem nada que dissesse em que tela a
  // pessoa estava. Numa conexão lenta, abrir "Lançamentos" mostrava um bloco
  // cinza mudo por segundos — enquanto `/overview`, ao lado, já mostrava o
  // título e o seletor de período com esqueleto só nos números. Duas telas do
  // mesmo app respondendo de formas diferentes à mesma situação.
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-8 w-52" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
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

  /*
   * Não pertence: redireciona, mas DIZENDO por quê.
   *
   * O `Navigate` silencioso deixava quem clicou num link antigo — ou num
   * favorito de um espaço do qual saiu — aterrissando no "Seu mês" sem nenhuma
   * explicação. As duas leituras possíveis ("errei o endereço" e "perdi o
   * acesso") pedem reações diferentes, e a tela não ajudava a escolher.
   *
   * O aviso distingue os dois casos com a informação que o guard já tem: id
   * inválido é endereço errado; id válido do qual não se é membro é falta de
   * acesso.
   */
  if (!pertence) return <RedirecionaAvisando valido={valido} />;

  return <Outlet />;
}
