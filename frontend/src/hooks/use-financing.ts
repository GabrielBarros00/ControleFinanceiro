import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import { useWorkspaceId } from './use-workspace-id';

export interface Financing {
  id: number;
  title: string;
  description?: string | null;
  total_amount: string;
  interest_rate: string;
  start_date: string;
  installments_count: number;
  method: 'SAC' | 'PRICE';
  status: 'active' | 'settled' | 'simulated';
}

export interface Installment {
  id: number;
  installment_number: number;
  due_date: string;
  principal_amount: string;
  interest_amount: string;
  total_amount: string;
  remaining_balance: string;
  is_paid: boolean;
}

export function useFinancing() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();

  const listQuery = useQuery({
    queryKey: ['financing', currentWorkspaceId],
    queryFn: async (): Promise<Financing[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/financing`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  // Pagar parcela muda o saldo devedor mostrado em Endividamento também
  const invalidate = () =>
    invalidateForEvent(queryClient, 'financing.updated', currentWorkspaceId);

  const createMutation = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/financing`, data);
      return response.data as Financing;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/financing/${id}`);
    },
    onSuccess: invalidate,
  });

  const payInstallment = useMutation({
    mutationFn: async ({ financingId, installmentNumber }: { financingId: number; installmentNumber: number }) => {
      await apiClient.post(
        `/workspaces/${currentWorkspaceId}/financing/${financingId}/installments/${installmentNumber}/pay`
      );
    },
    onSuccess: invalidate,
  });

  return {
    financings: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    payInstallment: payInstallment.mutateAsync,
  };
}

export function useFinancingSchedule(financingId: number | null) {
  const currentWorkspaceId = useWorkspaceId();

  const scheduleQuery = useQuery({
    queryKey: ['financing', currentWorkspaceId, financingId, 'schedule'],
    queryFn: async (): Promise<Installment[]> => {
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/financing/${financingId}/schedule`
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!financingId,
  });

  const settlementQuery = useQuery({
    queryKey: ['financing', currentWorkspaceId, financingId, 'settlement'],
    queryFn: async () => {
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/financing/${financingId}/early-settlement`,
        {}
      );
      return response.data as {
        total_to_pay: string;
        original_value: string;
        savings: string;
        installments_settled: number;
      };
    },
    enabled: !!currentWorkspaceId && !!financingId,
  });

  return {
    schedule: scheduleQuery.data ?? [],
    settlement: settlementQuery.data ?? null,
    isLoading: scheduleQuery.isLoading,
  };
}
