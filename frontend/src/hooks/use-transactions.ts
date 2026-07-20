import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
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
  page: number;
  limit: number;
  total_pages: number;
}

export function useTransactions(filters: TransactionFilters = { page: 1, limit: 10 }) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();
  const { page = 1, limit = 10, month, search, category_id, payment_method, tag_id } = filters;

  // Fetch transactions
  const listQuery = useQuery({
    queryKey: ['transactions', currentWorkspaceId, page, limit, month, search, category_id, payment_method, tag_id],
    queryFn: async (): Promise<Pick<TransactionListResponse, 'items' | 'total' | 'total_pages'> & Partial<TransactionListResponse>> => {
      if (!currentWorkspaceId) return { items: [], total: 0, total_pages: 1 };
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
    enabled: !!currentWorkspaceId
  });

  // Create transaction
  const createMutation = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/transactions/`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions', currentWorkspaceId] });
      queryClient.invalidateQueries({ queryKey: ['analytics'] });
    }
  });

  // Update transaction
  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number, data: Record<string, unknown> }) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/transactions/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions', currentWorkspaceId] });
      queryClient.invalidateQueries({ queryKey: ['analytics'] });
    }
  });

  // Delete transaction
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/transactions/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions', currentWorkspaceId] });
      queryClient.invalidateQueries({ queryKey: ['analytics'] });
    }
  });

  return {
    transactions: listQuery.data?.items || [],
    total: listQuery.data?.total || 0,
    totalPages: listQuery.data?.total_pages || 1,
    currentPage: listQuery.data?.page || 1,
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    isMutating: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending
  };
}
