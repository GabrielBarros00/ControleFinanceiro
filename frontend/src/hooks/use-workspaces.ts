import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';
import { invalidateForEvent } from '@/lib/ws-events';

export interface Workspace {
  id: number;
  name: string;
  description?: string | null;
  /** Moeda em que todas as agregações são somadas (ADR 0006). */
  base_currency?: string;
  /**
   * Este espaço controla o pagamento das contas? (ADR 0029)
   *
   * Ligado, o lançamento fora do cartão só vira saída de caixa depois de marcado
   * como pago. Opcional aqui porque uma resposta antiga em cache não o traz —
   * quem lê deve tratar `undefined` como ligado (`useSettlementTracking`).
   */
  settlement_tracking?: boolean;
  owner_user_id?: number | null;
  owner_name?: string | null;
  member_count?: number;
}

export function useWorkspaces() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId, setCurrentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: async (): Promise<Workspace[]> => {
      const response = await apiClient.get('/workspaces/');
      return response.data;
    },
  });

  // Semente do "último visitado": sem ela, quem acabou de se cadastrar cai em
  // /overview com a barra lateral só com a camada global — e não teria como
  // entrar no próprio workspace sem abrir o seletor. Só preenche quando está
  // vazio; nunca sobrescreve uma escolha do usuário.
  const primeiro = listQuery.data?.[0]?.id ?? null;
  React.useEffect(() => {
    if (currentWorkspaceId == null && primeiro != null) {
      setCurrentWorkspaceId(primeiro);
    }
  }, [currentWorkspaceId, primeiro, setCurrentWorkspaceId]);

  const createMutation = useMutation({
    mutationFn: async (data: {
      name: string;
      description?: string;
      base_currency?: string;
      settlement_tracking?: boolean;
    }) => {
      const response = await apiClient.post('/workspaces/', data);
      return response.data as Workspace;
    },
    onSuccess: (ws) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
      setCurrentWorkspaceId(ws.id);
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: {
      id: number;
      data: {
        name?: string;
        description?: string;
        base_currency?: string;
        settlement_tracking?: boolean;
      };
    }) => {
      const response = await apiClient.put(`/workspaces/${id}`, data);
      return response.data as Workspace;
    },
    onSuccess: (_ws, vars) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
      // Trocar a moeda-base reescreve TODA agregação do workspace (relatórios,
      // dívidas, faturas, endividamento) — mesmo alcance do evento no WebSocket
      if (vars.data.base_currency) {
        invalidateForEvent(queryClient, 'workspace.currency_changed', vars.id);
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${id}`);
    },
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
      if (currentWorkspaceId === deletedId) {
        setCurrentWorkspaceId(null);
      }
    },
  });

  /**
   * Troca o workspace CORRENTE (estado + cache). A NAVEGAÇÃO fica com quem
   * chama: o workspace vive na URL (ADR 0020), mas embutir `useNavigate` aqui
   * obrigaria todo consumidor deste hook — inclusive `useBaseCurrency`, usado em
   * componentes testados isoladamente — a existir dentro de um `<Router>`.
   * `workspacePath` monta o destino para quem navega.
   */
  const switchWorkspace = (id: number) => {
    setCurrentWorkspaceId(id);
    // Dados de todos os hooks são keyed por workspaceId; invalidar garante refetch limpo
    queryClient.invalidateQueries();
  };

  return {
    workspaces: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    // Falha de rede PRECISA ser distinguível de "não participo de espaço nenhum".
    // O `?? []` acima transforma erro em lista vazia, e quem só olhasse
    // `workspaces.length` concluía "sem acesso" — foi assim que o `WorkspaceGuard`
    // passou a ejetar para /overview quando o backend estava fora do ar.
    isError: listQuery.isError,
    error: listQuery.error,
    refetch: listQuery.refetch,
    currentWorkspaceId,
    currentWorkspace: (listQuery.data ?? []).find((w) => w.id === currentWorkspaceId) ?? null,
    switchWorkspace,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}
