import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

export type AuditAction = 'create' | 'update' | 'delete' | 'login' | 'logout';

export interface AuditEntry {
  id: number;
  action: AuditAction;
  resource_type?: string | null;
  resource_id?: number | null;
  user_id?: number | null;
  workspace_id?: number | null;
  created_at: string;
}

// Trilha de auditoria do workspace (admin+). `enabled` deixa o chamador segurar
// a consulta até a aba estar ativa — evita 403 desnecessário para não-admin.
export function useAudit(enabled = true) {
  const { currentWorkspaceId } = useUIStore();

  const query = useQuery({
    queryKey: ['audit', currentWorkspaceId],
    queryFn: async (): Promise<AuditEntry[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/audit`, {
        params: { limit: 100 },
      });
      return response.data;
    },
    enabled: !!currentWorkspaceId && enabled,
  });

  return {
    entries: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
