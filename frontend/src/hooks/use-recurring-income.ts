import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { MaterializeScope } from '@/lib/recurrence';

export interface RecurringIncome {
  id: number;
  title: string;
  description?: string | null;
  base_amount: string;
  currency: string;
  category?: string | null;
  frequency: 'daily' | 'weekly' | 'monthly' | 'yearly';
  interval: number;
  start_date?: string | null;
  day_of_month: number;
  day_of_week?: number | null;
  month_of_year?: number | null;
  is_active: boolean;
  user_id: number;
}

export function useRecurringIncome() {
  const queryClient = useQueryClient();

  const queryKey = ['recurring-income'];

  const listQuery = useQuery({
    queryKey,
    queryFn: async (): Promise<RecurringIncome[]> => {
      const response = await apiClient.get(`/me/recurring-income`);
      return response.data;
    },
  });

  const invalidateList = () => queryClient.invalidateQueries({ queryKey });

  // Pelo contrato único (`ws-events`), não à mão: a lista escrita aqui parava em
  // `income` + `me-overview` e deixava "Seus relatórios" e a previsão com o
  // número velho. `BY_PREFIX.recurring_income` já dizia quais famílias mexem.
  const invalidateIncome = () => {
    invalidateForEvent(queryClient, 'recurring_income.changed', null);
  };

  // Criar/editar/excluir template pode materializar (ou re-sincronizar) a renda
  // do mês corrente no backend — refaz a lista de rendas e os relatórios também.
  const invalidateAll = () => {
    invalidateList();
    invalidateIncome();
  };

  // materialize decide o alcance quando a start_date é retroativa:
  // 'current' (só o mês corrente, padrão), 'past' (lança o histórico),
  // 'future' (nada agora; empurra a start_date para a próxima ocorrência)
  const createMutation = useMutation({
    mutationFn: async ({ data, materialize }: { data: Record<string, unknown>; materialize?: MaterializeScope }) => {
      const response = await apiClient.post(
        `/me/recurring-income`,
        data,
        { params: materialize ? { materialize } : undefined },
      );
      return response.data as RecurringIncome;
    },
    onSuccess: invalidateAll,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data, materialize }: { id: number; data: Record<string, unknown>; materialize?: MaterializeScope }) => {
      const response = await apiClient.put(
        `/me/recurring-income/${id}`,
        data,
        { params: materialize ? { materialize } : undefined },
      );
      return response.data as RecurringIncome;
    },
    onSuccess: invalidateAll,
  });

  const removeMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/me/recurring-income/${id}`);
    },
    onSuccess: invalidateAll,
  });

  // Materializa as rendas recorrentes vencidas do mês (idempotente no backend)
  const generateMutation = useMutation({
    mutationFn: async (): Promise<{ created: number }> => {
      const response = await apiClient.post(`/me/recurring-income/generate`);
      return response.data;
    },
    onSuccess: (result) => {
      if (result.created > 0) invalidateIncome();
    },
  });

  return {
    recurringIncomes: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: removeMutation.mutateAsync,
    generate: generateMutation.mutateAsync,
    isGenerating: generateMutation.isPending,
  };
}
