import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export interface Estimate {
  id: number;
  category: string;
  amount: string;
  month: string; // YYYY-MM
  description?: string | null;
}

/** Orçamento mensal (estimates). O forecast usa a soma do mês como total_budget. */
export function useEstimates(month: string) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['estimates', currentWorkspaceId, month],
    queryFn: async (): Promise<Estimate[]> => {
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/analytics/estimates`,
        { params: { month } }
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['estimates', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['analytics-forecast', currentWorkspaceId] });
  };

  const upsertMutation = useMutation({
    mutationFn: async (amount: number) => {
      const existing = (listQuery.data ?? []).find((e) => e.category === 'Geral');
      const payload = { category: 'Geral', amount: String(amount), month };
      if (existing) {
        const response = await apiClient.put(
          `/workspaces/${currentWorkspaceId}/analytics/estimates/${existing.id}`,
          payload
        );
        return response.data as Estimate;
      }
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/analytics/estimates`,
        payload
      );
      return response.data as Estimate;
    },
    onSuccess: invalidate,
  });

  // Orçamento POR CATEGORIA (a soma do mês continua sendo o total_budget)
  const upsertCategoryMutation = useMutation({
    mutationFn: async ({ category, amount }: { category: string; amount: number }) => {
      const existing = (listQuery.data ?? []).find((e) => e.category === category);
      const payload = { category, amount: String(amount), month };
      if (existing) {
        const response = await apiClient.put(
          `/workspaces/${currentWorkspaceId}/analytics/estimates/${existing.id}`,
          payload
        );
        return response.data as Estimate;
      }
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/analytics/estimates`,
        payload
      );
      return response.data as Estimate;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/analytics/estimates/${id}`);
    },
    onSuccess: invalidate,
  });

  return {
    estimates: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    setBudget: upsertMutation.mutateAsync,
    isSaving: upsertMutation.isPending,
    setCategoryBudget: upsertCategoryMutation.mutateAsync,
    removeEstimate: deleteMutation.mutateAsync,
  };
}
