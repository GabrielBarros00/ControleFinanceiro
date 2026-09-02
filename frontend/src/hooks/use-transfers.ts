import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';

export type TransferRead = components['schemas']['TransferRead'];

/** Transferência entre contas da própria pessoa (ADR 0034).
 *
 * Não é renda nem despesa: o dinheiro muda de lugar e o total não se mexe. Uma
 * linha carrega as DUAS pernas, então não existe transferência pela metade. */
export function useTransfers() {
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ['transfers'],
    queryFn: async (): Promise<TransferRead[]> => {
      const response = await apiClient.get('/me/transfers');
      return response.data;
    },
  });

  const invalidate = () => {
    for (const key of ['transfers', 'me-balance', 'account-statement']) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const createMutation = useMutation({
    mutationFn: async (data: {
      from_account_id: number;
      to_account_id: number;
      from_amount: string;
      /** Obrigatório quando as contas estão em moedas diferentes — o servidor
       * recusa a conversão silenciosa. */
      to_amount?: string;
      occurred_on?: string;
      note?: string;
    }) => {
      const response = await apiClient.post('/me/transfers', data);
      return response.data as TransferRead;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/me/transfers/${id}`);
    },
    onSuccess: invalidate,
  });

  return {
    transfers: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    isSaving: createMutation.isPending,
  };
}
