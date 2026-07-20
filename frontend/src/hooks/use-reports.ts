import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export function useReports() {
  const { currentWorkspaceId } = useUIStore();

  const reportsQuery = useQuery({
    queryKey: ['reports', currentWorkspaceId],
    queryFn: async () => {
      if (!currentWorkspaceId) return null;
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/analytics/reports`);
      return response.data;
    },
    enabled: !!currentWorkspaceId
  });

  return {
    data: reportsQuery.data,
    isLoading: reportsQuery.isLoading,
    isError: reportsQuery.isError
  };
}
