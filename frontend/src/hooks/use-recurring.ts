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

  const createMutation = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/recurring`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Record<string, unknown> }) => {
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/recurring/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/recurring/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
    },
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
