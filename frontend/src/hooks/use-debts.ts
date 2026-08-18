import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/** Uma dívida já simplificada: A paga B, um valor só. */
export type Debt = components['schemas']['DebtRow'];

export function useDebts() {
  const currentWorkspaceId = useWorkspaceId();

  const queryKey = ['debts', currentWorkspaceId];

  const debtsQuery = useQuery({
    queryKey,
    // O retorno era `any`: a rota não declarava schema, então nem o hook nem
    // quem o consome sabiam o que vinha. Agora o `tsc` acusa cada divergência.
    queryFn: async (): Promise<Debt[]> => {
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
