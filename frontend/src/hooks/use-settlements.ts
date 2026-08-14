import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import { useWorkspaceId } from './use-workspace-id';

export interface Settlement {
  id: number;
  from_user_id: number;
  to_user_id: number;
  amount: string;
  note?: string | null;
  settled_at: string;
  created_by_user_id?: number | null;
}

export interface SettlementCreate {
  from_user_id: number;
  to_user_id: number;
  amount: number;
  note?: string;
  billing_month?: string;
}

/**
 * `workspaceId` explícito serve à tela GLOBAL de acertos (ADR 0027): lá a casa
 * não vem da URL, vem da linha em que a pessoa clicou. Sem parâmetro, o
 * comportamento é o de sempre — a casa aberta.
 *
 * A comparação é com `undefined`, não `??`: `useSettlements(null)` significa
 * "ainda não sei qual casa" e tem de continuar desabilitado, enquanto o `??`
 * cairia de volta na URL e mandaria o acerto para a casa errada.
 */
export function useSettlements(
  workspaceId?: number | null,
  { list = true }: { list?: boolean } = {},
) {
  const queryClient = useQueryClient();
  const daUrl = useWorkspaceId();
  const currentWorkspaceId = workspaceId !== undefined ? workspaceId : daUrl;

  const listQuery = useQuery({
    queryKey: ['settlements', currentWorkspaceId],
    queryFn: async (): Promise<Settlement[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/settlements`);
      return response.data;
    },
    // `list: false` para quem só escreve. O diálogo de acerto é um deles, e na
    // tela global ele muda de casa a cada linha clicada: sem isto, cada abertura
    // buscava o histórico de um workspace que aquela tela não desenha.
    enabled: list && !!currentWorkspaceId,
  });

  // Acerto muda o saldo global E o ledger do mês (que é ciente de acertos)
  const invalidate = () =>
    invalidateForEvent(queryClient, 'settlement.created', currentWorkspaceId);

  // Sem casa não há acerto: a URL viraria `/workspaces/null/settlements` e o
  // servidor responderia 422 falando de `workspace_id`, quando o problema é de
  // cá. Vale para as duas telas, mas nasceu da global — lá o id vem do draft, e
  // um draft incompleto tem de falhar rápido e claro.
  const exigeWorkspace = () => {
    if (!currentWorkspaceId) {
      throw new Error('Escolha em qual workspace o acerto será registrado.');
    }
    return currentWorkspaceId;
  };

  const createMutation = useMutation({
    mutationFn: async (data: SettlementCreate) => {
      const ws = exigeWorkspace();
      const response = await apiClient.post(`/workspaces/${ws}/settlements`, data);
      return response.data as Settlement;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const ws = exigeWorkspace();
      await apiClient.delete(`/workspaces/${ws}/settlements/${id}`);
    },
    onSuccess: invalidate,
  });

  return {
    settlements: listQuery.data || [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    isMutating: createMutation.isPending || deleteMutation.isPending,
  };
}
