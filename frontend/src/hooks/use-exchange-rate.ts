import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';
import { useBaseCurrency } from './use-base-currency';

/*
 * Taxa de câmbio de REFERÊNCIA para a dica "≈ tanto" do formulário.
 *
 * O alvo é a MOEDA-BASE do workspace, não 'BRL' fixo: num workspace em USD a
 * dica mostrava a conversão para um real que não é usado em lugar nenhum.
 * O endpoint devolve a mesma taxa cruzada que a criação do lançamento vai
 * aplicar, então dica e valor gravado não divergem.
 *
 * Best-effort: falha da fonte não quebra o form (o valor definitivo é calculado
 * e congelado no servidor).
 */
export function useExchangeRate(from: string, to?: string) {
  const { currentWorkspaceId } = useUIStore();
  const baseCurrency = useBaseCurrency();
  const target = to ?? baseCurrency;

  const query = useQuery({
    queryKey: ['exchange-rate', currentWorkspaceId, from, target],
    queryFn: async (): Promise<{ rate: string } | null> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/analytics/exchange-rate`, {
        params: { from_currency: from, to_currency: target },
      });
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!from && from !== target,
    retry: false,
    staleTime: 1000 * 60 * 30,
  });

  return {
    rate: query.data?.rate ? parseFloat(query.data.rate) : null,
    isLoading: query.isLoading,
  };
}
