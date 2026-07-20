import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export interface Category {
  id: number;
  name: string;
  color?: string | null;
  icon?: string | null;
}

export function useCategories() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['categories', currentWorkspaceId],
    queryFn: async (): Promise<Category[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/categories`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['categories', currentWorkspaceId] });

  const createMutation = useMutation({
    mutationFn: async (data: { name: string; color?: string; icon?: string }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/categories`, data);
      return response.data as Category;
    },
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: { name?: string; color?: string } }) => {
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/categories/${id}`, data);
      return response.data as Category;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/categories/${id}`);
    },
    onSuccess: invalidate,
  });

  const categoryName = (id: number | null | undefined): string =>
    (listQuery.data ?? []).find((c) => c.id === id)?.name ?? 'Geral';

  return {
    categories: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    categoryName,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}
