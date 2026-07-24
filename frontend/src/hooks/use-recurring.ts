import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export function useRecurring() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

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
  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ['transactions', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['reports', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['analytics'] });
  };

  const createMutation = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/recurring`, data);
      return response.data;
    },
    onSuccess: invalidateAll,
  });

  // scope decide o alcance sobre as instâncias já geradas (não pagas):
  // 'future' (mês corrente em diante, padrão), 'all' (todas), 'none' (só o modelo)
  const updateMutation = useMutation({
    mutationFn: async ({ id, data, scope }: { id: number; data: Record<string, unknown>; scope?: 'none' | 'future' | 'all' }) => {
      const response = await apiClient.put(
        `/workspaces/${currentWorkspaceId}/recurring/${id}`,
        data,
        { params: scope ? { scope } : undefined },
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
        queryClient.invalidateQueries({ queryKey: ['transactions', currentWorkspaceId] });
        queryClient.invalidateQueries({ queryKey: ['analytics'] });
        queryClient.invalidateQueries({ queryKey: ['reports', currentWorkspaceId] });
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
