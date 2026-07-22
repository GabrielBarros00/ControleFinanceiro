import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export interface Settlement {
  id: number;
  from_user_id: number;
  to_user_id: number;
  amount: string;
  note?: string | null;
  settled_at: string;
  created_by_user_id?: number | null;
}

export interface SettlementCreate {
  from_user_id: number;
  to_user_id: number;
  amount: number;
  note?: string;
  billing_month?: string;
}

export function useSettlements() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['settlements', currentWorkspaceId],
    queryFn: async (): Promise<Settlement[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/settlements`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['settlements', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['debts', currentWorkspaceId] });
    // O ledger mensal agora é ciente de acertos — sem isso a "Dívidas do mês"
    // não refazia o fetch e parecia que ninguém tinha pago (causa secundária).
    queryClient.invalidateQueries({ queryKey: ['debts-monthly', currentWorkspaceId] });
  };

  const createMutation = useMutation({
    mutationFn: async (data: SettlementCreate) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/settlements`, data);
      return response.data as Settlement;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/settlements/${id}`);
    },
    onSuccess: invalidate,
  });

  return {
    settlements: listQuery.data || [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    isMutating: createMutation.isPending || deleteMutation.isPending,
  };
}
