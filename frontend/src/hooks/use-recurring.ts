import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { MaterializeScope } from '@/lib/recurrence';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/** Uma linha da revisão (ADR 0030): o lançamento e o que vai acontecer com ele. */
export type RecurringPlanItem = components['schemas']['RecurringPlanItem'];
export type RecurringPreviewAction = 'update' | 'deactivate' | 'delete';

interface PreviewArgs {
  id: number;
  action: RecurringPreviewAction;
  /** O MESMO corpo do PUT: a revisão planeja a partir do que está na tela. */
  changes?: Record<string, unknown> | null;
  since?: string;
}

/** As escolhas da revisão, viajando como query string no PUT/DELETE. */
export interface ApplyChoice {
  applyTo: number[];
  createOccurrences: string[];
  since?: string;
}

/**
 * `?apply_to=1&apply_to=2` — o formato que o FastAPI lê como `List[int]`.
 *
 * O axios serializa array como `apply_to[]=1`, que o FastAPI **não** casa: a
 * lista chega vazia, nada é aplicado, e a requisição responde 200 sem erro
 * nenhum. Mesma armadilha que o `paramsSerializer` do extrato já teve de fechar.
 */
function comEscolhas(base: string, escolha?: ApplyChoice): string {
  if (!escolha) return base;
  const params = new URLSearchParams();
  for (const id of escolha.applyTo) params.append('apply_to', String(id));
  for (const dia of escolha.createOccurrences) params.append('create_occurrence', dia);
  if (escolha.since) params.set('since', escolha.since);
  const query = params.toString();
  return query ? `${base}${base.includes('?') ? '&' : '?'}${query}` : base;
}

export function useRecurring() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();

  const queryKey = ['recurring', currentWorkspaceId];

  const recurringQuery = useQuery({
    queryKey,
    queryFn: async () => {
      if (!currentWorkspaceId) return [];
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/recurring`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  // Criar/editar/excluir template pode materializar (ou re-sincronizar) a despesa
  // do mês corrente no backend — refaz o extrato e os relatórios também.
  const invalidateAll = () =>
    invalidateForEvent(queryClient, 'recurring.updated', currentWorkspaceId);

  // materialize decide o alcance quando a start_date é retroativa:
  // 'current' (só o mês corrente, padrão), 'past' (lança o histórico),
  // 'future' (nada agora; empurra a start_date para a próxima ocorrência)
  const createMutation = useMutation({
    mutationFn: async ({ data, materialize }: { data: Record<string, unknown>; materialize?: MaterializeScope }) => {
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/recurring`,
        data,
        { params: materialize ? { materialize } : undefined },
      );
      return response.data;
    },
    onSuccess: invalidateAll,
  });

  // "O que acontece se eu salvar isto?" — read-only, e a MESMA função que a
  // escrita executa (ADR 0030). É `POST` porque leva corpo, não porque muda algo.
  const previewMutation = useMutation({
    mutationFn: async ({ id, action, changes, since }: PreviewArgs) => {
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/recurring/${id}/preview`,
        { action, changes: changes ?? null, since: since ?? null },
      );
      return (response.data as components['schemas']['RecurringPlanRead']).items;
    },
  });

  // `escolha` é o resultado da revisão. Sem ela, o backend cai no `scope`
  // legado — mês corrente em diante, e a data NÃO se move.
  const updateMutation = useMutation({
    mutationFn: async ({ id, data, scope, materialize, escolha }: {
      id: number;
      data: Record<string, unknown>;
      scope?: 'none' | 'future' | 'all';
      materialize?: MaterializeScope;
      escolha?: ApplyChoice;
    }) => {
      const base = new URLSearchParams();
      if (scope) base.set('scope', scope);
      if (materialize) base.set('materialize', materialize);
      const url = comEscolhas(
        `/workspaces/${currentWorkspaceId}/recurring/${id}${base.toString() ? `?${base}` : ''}`,
        escolha,
      );
      const response = await apiClient.put(url, data);
      return response.data;
    },
    onSuccess: invalidateAll,
  });

  // `cancelInstances`: os lançamentos que a revisão marcou para cancelar junto.
  // Vazio (ou ausente) mantém o comportamento de sempre — o template some e os
  // lançamentos ficam.
  const removeMutation = useMutation({
    mutationFn: async ({ id, cancelInstances }: { id: number; cancelInstances?: number[] }) => {
      const params = new URLSearchParams();
      for (const txId of cancelInstances ?? []) {
        params.append('cancel_instance', String(txId));
      }
      const query = params.toString();
      await apiClient.delete(
        `/workspaces/${currentWorkspaceId}/recurring/${id}${query ? `?${query}` : ''}`,
      );
    },
    onSuccess: invalidateAll,
  });

  // Materializa as instâncias vencidas do mês (idempotente no backend)
  const generateMutation = useMutation({
    mutationFn: async (): Promise<{ created: number }> => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/recurring/generate`);
      return response.data;
    },
    onSuccess: (result) => {
      if (result.created > 0) {
        // Materializar cria lançamentos de verdade: mesmo alcance de um
        // transaction.bulk_created vindo pelo WebSocket
        invalidateForEvent(queryClient, 'transaction.bulk_created', currentWorkspaceId);
      }
    },
  });

  return {
    recurring: recurringQuery.data || [],
    isLoading: recurringQuery.isLoading,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: removeMutation.mutateAsync,
    preview: previewMutation.mutateAsync,
    isPreviewing: previewMutation.isPending,
    generate: generateMutation.mutateAsync,
    isGenerating: generateMutation.isPending,
  };
}
