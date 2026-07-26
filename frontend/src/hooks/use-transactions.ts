import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import { useUIStore } from '@/stores';
import type { TransactionRead } from '@/types/transaction';

export interface TransactionFilters {
  page?: number;
  limit?: number;
  month?: string;
  search?: string;
  category_id?: number;
  payment_method?: string;
  tag_id?: number;
}

export interface TransactionListResponse {
  items: TransactionRead[];
  total: number;
  /** Soma do filtro inteiro, não só da página que veio. */
  total_amount: string | number;
  page: number;
  limit: number;
  total_pages: number;
}

export function useTransactions(
  filters: TransactionFilters = { page: 1, limit: 10 },
  // `false` desliga a listagem e deixa só as mutations. Existe porque o
  // TransactionDetailHost (montado no AppShell, ou seja, em TODAS as telas)
  // chamava este hook só para pegar create/update/delete — e disparava uma
  // requisição de extrato a mais em cada página, duas na Home.
  enableList = true,
) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();
  const { page = 1, limit = 10, month, search, category_id, payment_method, tag_id } = filters;

  // Fetch transactions
  const listQuery = useQuery({
    queryKey: ['transactions', currentWorkspaceId, page, limit, month, search, category_id, payment_method, tag_id],
    queryFn: async (): Promise<Pick<TransactionListResponse, 'items' | 'total' | 'total_pages'> & Partial<TransactionListResponse>> => {
      if (!currentWorkspaceId) return { items: [], total: 0, total_amount: 0, total_pages: 1 };
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/transactions/`, {
        params: {
          limit,
          page,
          month,
          search,
          category_id,
          payment_method: payment_method || undefined,
          tag_id: tag_id || undefined
        }
      });
      return response.data; // { items, total, page, limit, total_pages }
    },
    enabled: !!currentWorkspaceId && enableList
  });

  // Mesma tabela que o WebSocket usa: quem lança vê o mesmo que os outros
  // membros veem (extrato, detalhe, parcelas, relatórios, previsão, dívidas,
  // endividamento e fatura do cartão).
  const invalidateTransactionData = () =>
    invalidateForEvent(queryClient, 'transaction.updated', currentWorkspaceId);

  // Create transaction
  const createMutation = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/transactions/`, data);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  // Update transaction
  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number, data: Record<string, unknown> }) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/transactions/${id}`, data);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  // Delete transaction (uma parcela avulsa ou lançamento comum)
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/transactions/${id}`);
    },
    onSuccess: invalidateTransactionData
  });

  // Excluir a COMPRA parcelada inteira: soft-delete de todas as parcelas vivas
  // do grupo de uma vez (backend preserva as já pagas).
  const deleteGroupMutation = useMutation({
    mutationFn: async (id: number): Promise<{ deleted: number; skipped_paid: number }> => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.delete(`/workspaces/${currentWorkspaceId}/transactions/${id}/installment-group`);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  // Editar a COMPRA parcelada inteira (refatia total/nº de parcelas; congela pagas)
  const updateGroupMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number, data: Record<string, unknown> }) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/transactions/${id}/installment-group`, data);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  return {
    transactions: listQuery.data?.items || [],
    total: listQuery.data?.total || 0,
    // Soma do filtro inteiro (o backend agrega); Number() por vir como Decimal
    totalAmount: Number(listQuery.data?.total_amount ?? 0),
    totalPages: listQuery.data?.total_pages || 1,
    currentPage: listQuery.data?.page || 1,
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    updateGroup: updateGroupMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    removeGroup: deleteGroupMutation.mutateAsync,
    isMutating: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending
  };
}

// Busca um único lançamento pelo id (detalhe/preview). Sempre traz payers,
// splits, items e parcela — a mesma fonte do TransactionRead da lista.
export function useTransaction(id?: number | null) {
  const { currentWorkspaceId } = useUIStore();
  const query = useQuery({
    queryKey: ['transaction', currentWorkspaceId, id],
    queryFn: async (): Promise<TransactionRead> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/transactions/${id}`);
      return response.data;
    },
    enabled: !!currentWorkspaceId && id != null,
  });

  return {
    transaction: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}

export interface InstallmentGroupSummary {
  installment_group_id: string;
  installments_of: number;
  count_live: number;
  paid_count: number;
  group_total: string | number;
  title: string;
  // Definição da compra INTEIRA (formato TransactionRead) p/ pré-preencher o form
  whole: TransactionRead;
}

// Resumo do grupo de parcelas (total da compra, nº, quantas pagas, definição
// inteira). Usado só ao editar uma compra parcelada.
export function useInstallmentGroup(id?: number | null, enabled = true) {
  const { currentWorkspaceId } = useUIStore();
  const query = useQuery({
    queryKey: ['installment-group', currentWorkspaceId, id],
    queryFn: async (): Promise<InstallmentGroupSummary> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/transactions/${id}/installment-group`);
      return response.data;
    },
    enabled: !!currentWorkspaceId && id != null && enabled,
  });

  return { group: query.data ?? null, isLoading: query.isLoading };
}
