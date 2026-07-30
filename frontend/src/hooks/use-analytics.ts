import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

/** Previsão do mês pedido (YYYY-MM). O backend sempre aceitou `?month`, mas o
 *  hook nunca o enviava — a previsão ficava presa ao mês do SERVIDOR mesmo
 *  com outro período selecionado na tela. */
export function useAnalytics(month?: string) {
  const currentWorkspaceId = useWorkspaceId();

  const forecastQuery = useQuery({
    queryKey: ['analytics-forecast', currentWorkspaceId, month],
    queryFn: async () => {
      if (!currentWorkspaceId) return null;
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/analytics/forecast`, {
        params: month ? { month } : undefined,
      });
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
