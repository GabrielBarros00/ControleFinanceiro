import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useUIStore } from '@/stores';

/** `workspace` = meta da CASA; `personal` = meta do membro (a parte dele). */
export type EstimateScope = 'workspace' | 'personal';

export interface Estimate {
  id: number;
  category: string;
  amount: string;
  month: string; // YYYY-MM
  description?: string | null;
  /** Referência real da categoria (BUD-001); nulo em "Geral" e em metas antigas. */
  category_id?: number | null;
  /** null = meta da casa; preenchido = meta pessoal daquele membro. */
  owner_user_id?: number | null;
  scope?: EstimateScope;
}

const escopoDe = (e: Estimate): EstimateScope =>
  e.scope ?? (e.owner_user_id != null ? 'personal' : 'workspace');

/** Orçamento mensal (estimates). O forecast usa a soma do mês como total_budget. */
export function useEstimates(month: string) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['estimates', currentWorkspaceId, month],
    queryFn: async (): Promise<Estimate[]> => {
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/analytics/estimates`,
        { params: { month } }
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['estimates', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['analytics-forecast', currentWorkspaceId] });
  };

  const upsertMutation = useMutation({
    mutationFn: async (amount: number) => {
      const existing = (listQuery.data ?? []).find(
        (e) => e.category === 'Geral' && escopoDe(e) === 'workspace',
      );
      const payload = { category: 'Geral', amount: String(amount), month, scope: 'workspace' };
      if (existing) {
        const response = await apiClient.put(
          `/workspaces/${currentWorkspaceId}/analytics/estimates/${existing.id}`,
          payload
        );
        return response.data as Estimate;
      }
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/analytics/estimates`,
        payload
      );
      return response.data as Estimate;
    },
    onSuccess: invalidate,
  });

  // Orçamento POR CATEGORIA (a soma do mês continua sendo o total_budget).
  // `categoryId` é o que casa a meta com o gasto — o nome vai junto só como
  // rótulo, porque renomear a categoria não pode zerar o consumo (BUD-001).
  const upsertCategoryMutation = useMutation({
    mutationFn: async ({
      category,
      categoryId,
      amount,
      scope = 'workspace',
    }: {
      category: string;
      categoryId?: number | null;
      amount: number;
      scope?: EstimateScope;
    }) => {
      // O escopo entra na busca: definir a MINHA meta de Mercado não pode
      // sobrescrever a meta da CASA na mesma categoria (elas convivem).
      const existing = (listQuery.data ?? []).find(
        (e) => e.category === category && escopoDe(e) === scope,
      );
      const payload = {
        category,
        category_id: categoryId ?? null,
        amount: String(amount),
        month,
        scope,
      };
      if (existing) {
        const response = await apiClient.put(
          `/workspaces/${currentWorkspaceId}/analytics/estimates/${existing.id}`,
          payload
        );
        return response.data as Estimate;
      }
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/analytics/estimates`,
        payload
      );
      return response.data as Estimate;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/analytics/estimates/${id}`);
    },
    onSuccess: invalidate,
  });

  const todas = listQuery.data ?? [];
  return {
    estimates: todas,
    // A API só devolve as metas da casa + as PESSOAIS de quem pediu, então
    // filtrar por escopo aqui é suficiente (nunca chega a meta de outro membro).
    estimatesByScope: (scope: EstimateScope) =>
      todas.filter((e) => escopoDe(e) === scope),
    isLoading: listQuery.isLoading,
    setBudget: upsertMutation.mutateAsync,
    isSaving: upsertMutation.isPending,
    setCategoryBudget: upsertCategoryMutation.mutateAsync,
    removeEstimate: deleteMutation.mutateAsync,
  };
}
