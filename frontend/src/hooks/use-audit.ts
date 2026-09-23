import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

export type AuditAction = 'create' | 'update' | 'delete' | 'login' | 'logout';

export interface AuditEntry {
  id: number;
  action: AuditAction;
  resource_type?: string | null;
  resource_id?: number | null;
  user_id?: number | null;
  workspace_id?: number | null;
  created_at: string;
  /** `mcp:<cliente>` quando a mudança veio de um agente de IA (ADR 0035). */
  origin?: string | null;
}

/**
 * "via IA · ChatGPT" para o que um agente fez em nome da pessoa; `null` para o
 * que ela fez pelo app. A pessoa continua sendo quem fez — o agente age com a
 * permissão dela —, então isto complementa o "Quem", não o substitui.
 */
export function origemDaAcao(origin?: string | null): string | null {
  if (!origin || !origin.startsWith('mcp:')) return null;
  const cliente = origin.slice(4).trim();
  return cliente ? `via IA · ${cliente}` : 'via IA';
}

// Trilha de auditoria do workspace (admin+). `enabled` deixa o chamador segurar
// a consulta até a aba estar ativa — evita 403 desnecessário para não-admin.
export function useAudit(enabled = true) {
  const currentWorkspaceId = useWorkspaceId();

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
