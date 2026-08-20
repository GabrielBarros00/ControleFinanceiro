import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/**
 * Previsão de fechamento do mês. Todo campo da CASA é anulável de propósito: sem
 * acesso financeiro completo a resposta traz as MESMAS chaves com `null` (ADR
 * 0018), e `docs/API.md` proíbe coagir isso para zero — "sem acesso" e "zero" são
 * respostas diferentes.
 */
export type Forecast = components['schemas']['ForecastRead'];

/** Previsão do mês pedido (YYYY-MM). O backend sempre aceitou `?month`, mas o
 *  hook nunca o enviava — a previsão ficava presa ao mês do SERVIDOR mesmo
 *  com outro período selecionado na tela. */
export function useAnalytics(month?: string) {
  const currentWorkspaceId = useWorkspaceId();

  const forecastQuery = useQuery({
    queryKey: ['analytics-forecast', currentWorkspaceId, month],
    // Devolvia `any`: a rota não declarava schema, então nenhuma tela que lê a
    // previsão tinha checagem sobre os campos que exibe.
    queryFn: async (): Promise<Forecast | null> => {
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
