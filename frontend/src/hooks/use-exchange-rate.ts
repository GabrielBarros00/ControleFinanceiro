import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

// Taxa de câmbio de REFERÊNCIA (PTAX/BCB). Informativa apenas: lançamentos em
// moeda estrangeira NÃO entram nos totais em BRL (ADR 0006) — o hint só ajuda o
// usuário a estimar o valor. Best-effort: falha da fonte não quebra o form.
export function useExchangeRate(from: string, to = 'BRL') {
  const { currentWorkspaceId } = useUIStore();

  const query = useQuery({
    queryKey: ['exchange-rate', currentWorkspaceId, from, to],
    queryFn: async (): Promise<{ rate: string } | null> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/analytics/exchange-rate`, {
        params: { from_currency: from, to_currency: to },
      });
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!from && from !== to,
    retry: false,
    staleTime: 1000 * 60 * 30,
  });

  return {
    rate: query.data?.rate ? parseFloat(query.data.rate) : null,
    isLoading: query.isLoading,
  };
}
