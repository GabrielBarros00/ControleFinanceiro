import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

// Tipos GERADOS do OpenAPI (npm run typegen) — nunca espelhados à mão
export type PaymentAccountRead = components['schemas']['PaymentAccountRead'];
export type PaymentAccountType = components['schemas']['PaymentAccountType'];

export const ACCOUNT_TYPE_OPTIONS: { value: PaymentAccountType; label: string }[] = [
  { value: 'checking', label: 'Conta corrente' },
  { value: 'savings', label: 'Poupança' },
  { value: 'cash', label: 'Dinheiro' },
  { value: 'digital_wallet', label: 'Carteira digital' },
  { value: 'other', label: 'Outra' },
];

export function accountTypeLabel(type: PaymentAccountType): string {
  return ACCOUNT_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type;
}

export function usePaymentAccounts() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();

  const listQuery = useQuery({
    queryKey: ['payment-accounts', currentWorkspaceId],
    queryFn: async (): Promise<PaymentAccountRead[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/payment-accounts`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['payment-accounts', currentWorkspaceId] });

  const createMutation = useMutation({
    mutationFn: async (data: { name: string; type: PaymentAccountType; owner_user_id?: number | null }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/payment-accounts`, data);
      return response.data as PaymentAccountRead;
    },
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<PaymentAccountRead> }) => {
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/payment-accounts/${id}`, data);
      return response.data as PaymentAccountRead;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/payment-accounts/${id}`);
    },
    onSuccess: invalidate,
  });

  const accounts = listQuery.data ?? [];
  return {
    accounts,
    activeAccounts: accounts.filter((a) => a.active),
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}
