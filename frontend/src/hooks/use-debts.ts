import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

export function useDebts() {
  const currentWorkspaceId = useWorkspaceId();

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
