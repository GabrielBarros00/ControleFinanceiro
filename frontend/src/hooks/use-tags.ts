import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

export interface WorkspaceTag {
  id: number;
  name: string;
  color?: string | null;
}

export function useTags() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();

  const listQuery = useQuery({
    queryKey: ['tags', currentWorkspaceId],
    queryFn: async (): Promise<WorkspaceTag[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/tags`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['tags', currentWorkspaceId] });

  const createMutation = useMutation({
    mutationFn: async (data: { name: string; color?: string }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/tags`, data);
      return response.data as WorkspaceTag;
    },
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: { name?: string; color?: string } }) => {
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/tags/${id}`, data);
      return response.data as WorkspaceTag;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/tags/${id}`);
    },
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['transactions', currentWorkspaceId] });
    },
  });

  return {
    tags: listQuery.data || [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}
