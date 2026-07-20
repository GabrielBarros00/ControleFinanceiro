import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export interface Income {
  id: number;
  title: string;
  description?: string | null;
  amount: string;
  received_at: string;
  category?: string | null;
  user_id: number;
}

export function useIncome() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['income', currentWorkspaceId],
    queryFn: async (): Promise<Income[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/income/`);
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
    mutationFn: async (data: { title: string; amount: number; received_at: string; description?: string }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/income/`, data);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<{ title: string; amount: number; received_at: string; description: string }> }) => {
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
