import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

// Valores vêm de rota Dict[str, Any] (jsonable_encoder → número); coagimos com
// Number() na exibição para robustez a número OU string.
export interface LiabilityByPerson {
  user_id: number;
  financing: number;
  cards: number;
  total: number;
}

export interface LiabilityFinancing {
  id: number;
  title: string;
  owner_id: number;
  outstanding: number;
  month_due: number;
  next_due_date: string | null;
  installments_count: number;
  remaining_installments: number;
}

export interface LiabilityCard {
  id: number;
  name: string;
  committed: number;
  month_due: number;
}

export interface LiabilityOverview {
  month: string;
  base_currency: string;
  totals: { financing_outstanding: number; cards_committed: number; grand_total: number };
  month_due: { financing_due: number; cards_due: number; total: number };
  by_person: LiabilityByPerson[];
  financings: LiabilityFinancing[];
  cards: LiabilityCard[];
}

export function useLiabilities(month: string) {
  const currentWorkspaceId = useWorkspaceId();

  const query = useQuery({
    queryKey: ['liabilities', currentWorkspaceId, month],
    queryFn: async (): Promise<LiabilityOverview | null> => {
      if (!currentWorkspaceId) return null;
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/liabilities/overview`,
        { params: { month } },
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!month,
  });

  return {
    overview: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}
