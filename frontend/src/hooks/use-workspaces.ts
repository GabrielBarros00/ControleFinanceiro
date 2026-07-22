import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export interface Workspace {
  id: number;
  name: string;
  description?: string | null;
  owner_user_id?: number | null;
  owner_name?: string | null;
  member_count?: number;
}

export function useWorkspaces() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId, setCurrentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: async (): Promise<Workspace[]> => {
      const response = await apiClient.get('/workspaces/');
      return response.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data: { name: string; description?: string }) => {
      const response = await apiClient.post('/workspaces/', data);
      return response.data as Workspace;
    },
    onSuccess: (ws) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
      setCurrentWorkspaceId(ws.id);
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: { name?: string; description?: string } }) => {
      const response = await apiClient.put(`/workspaces/${id}`, data);
      return response.data as Workspace;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${id}`);
    },
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
      if (currentWorkspaceId === deletedId) {
        setCurrentWorkspaceId(null);
      }
    },
  });

  const switchWorkspace = (id: number) => {
    setCurrentWorkspaceId(id);
    // Dados de todos os hooks são keyed por workspaceId; invalidar garante refetch limpo
    queryClient.invalidateQueries();
  };

  return {
    workspaces: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    currentWorkspaceId,
    currentWorkspace: (listQuery.data ?? []).find((w) => w.id === currentWorkspaceId) ?? null,
    switchWorkspace,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}
