import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { MaterializeScope } from '@/lib/recurrence';
import { useWorkspaceId } from './use-workspace-id';

export function useRecurring() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();

  const queryKey = ['recurring', currentWorkspaceId];

  const recurringQuery = useQuery({
    queryKey,
    queryFn: async () => {
      if (!currentWorkspaceId) return [];
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/recurring`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  // Criar/editar/excluir template pode materializar (ou re-sincronizar) a despesa
  // do mês corrente no backend — refaz o extrato e os relatórios também.
  const invalidateAll = () =>
    invalidateForEvent(queryClient, 'recurring.updated', currentWorkspaceId);

  // materialize decide o alcance quando a start_date é retroativa:
  // 'current' (só o mês corrente, padrão), 'past' (lança o histórico),
  // 'future' (nada agora; empurra a start_date para a próxima ocorrência)
  const createMutation = useMutation({
    mutationFn: async ({ data, materialize }: { data: Record<string, unknown>; materialize?: MaterializeScope }) => {
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/recurring`,
        data,
        { params: materialize ? { materialize } : undefined },
      );
      return response.data;
    },
    onSuccess: invalidateAll,
  });

  // scope decide o alcance sobre as instâncias já geradas (não pagas):
  // 'future' (mês corrente em diante, padrão), 'all' (todas), 'none' (só o modelo)
  const updateMutation = useMutation({
    mutationFn: async ({ id, data, scope, materialize }: {
      id: number;
      data: Record<string, unknown>;
      scope?: 'none' | 'future' | 'all';
      materialize?: MaterializeScope;
    }) => {
      const response = await apiClient.put(
        `/workspaces/${currentWorkspaceId}/recurring/${id}`,
        data,
        { params: { ...(scope ? { scope } : {}), ...(materialize ? { materialize } : {}) } },
      );
      return response.data;
    },
    onSuccess: invalidateAll,
  });

  const removeMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/recurring/${id}`);
    },
    onSuccess: invalidateAll,
  });

  // Materializa as instâncias vencidas do mês (idempotente no backend)
  const generateMutation = useMutation({
    mutationFn: async (): Promise<{ created: number }> => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/recurring/generate`);
      return response.data;
    },
    onSuccess: (result) => {
      if (result.created > 0) {
        // Materializar cria lançamentos de verdade: mesmo alcance de um
        // transaction.bulk_created vindo pelo WebSocket
        invalidateForEvent(queryClient, 'transaction.bulk_created', currentWorkspaceId);
      }
    },
  });

  return {
    recurring: recurringQuery.data || [],
    isLoading: recurringQuery.isLoading,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: removeMutation.mutateAsync,
    generate: generateMutation.mutateAsync,
    isGenerating: generateMutation.isPending,
  };
}
