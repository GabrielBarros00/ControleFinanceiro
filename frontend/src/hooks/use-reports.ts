import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

/** Relatórios do mês pedido (YYYY-MM). Sem `month`, o back usa o mês corrente. */
export function useReports(month?: string) {
  const currentWorkspaceId = useWorkspaceId();

  const reportsQuery = useQuery({
    queryKey: ['reports', currentWorkspaceId, month],
    queryFn: async () => {
      if (!currentWorkspaceId) return null;
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/analytics/reports`, {
        params: month ? { month } : undefined,
      });
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
