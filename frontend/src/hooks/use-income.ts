import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export interface Income {
  id: number;
  title: string;
  description?: string | null;
  amount: string;
  currency?: string | null;
  received_at: string;
  category?: string | null;
  user_id: number;
  recurring_income_id?: number | null;
  billing_month?: string | null;
  original_amount?: string | null;
  original_currency?: string | null;
  exchange_rate?: string | null;
  rate_source?: string | null;
}

export function useIncome(month?: string) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['income', currentWorkspaceId, month],
    queryFn: async (): Promise<Income[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/income/`, {
        params: { month },
      });
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['income', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['reports', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['analytics-forecast', currentWorkspaceId] });
  };

  const createMutation = useMutation({
    mutationFn: async (data: { title: string; amount: number; received_at: string; description?: string; currency?: string }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/income/`, data);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<{ title: string; amount: number; received_at: string; description: string; currency: string }> }) => {
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/income/${id}`, data);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/income/${id}`);
    },
    onSuccess: invalidate,
  });

  return {
    incomes: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}
