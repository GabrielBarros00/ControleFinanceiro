import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export function useAnalytics() {
  const { currentWorkspaceId } = useUIStore();

  const forecastQuery = useQuery({
    queryKey: ['analytics-forecast', currentWorkspaceId],
    queryFn: async () => {
      if (!currentWorkspaceId) return null;
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/analytics/forecast`);
      return response.data;
    },
    enabled: !!currentWorkspaceId
  });

  return {
    forecast: forecastQuery.data,
    isLoading: forecastQuery.isLoading,
    isError: forecastQuery.isError
  };
}
