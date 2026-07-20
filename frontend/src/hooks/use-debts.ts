import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export function useDebts() {
  const { currentWorkspaceId } = useUIStore();

  const queryKey = ['debts', currentWorkspaceId];

  const debtsQuery = useQuery({
    queryKey,
    queryFn: async () => {
      if (!currentWorkspaceId) return [];
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/debts`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  return {
    debts: debtsQuery.data || [],
    isLoading: debtsQuery.isLoading,
    isError: debtsQuery.isError,
    refetch: debtsQuery.refetch,
  };
}
