import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { components } from '@/types/api.gen';

/**
 * Tipo GERADO do OpenAPI (npm run typegen). Era escrito à mão, e a divergência
 * apareceu na primeira mudança de contrato: `settled_at`, `cancelled_at`,
 * `account_id` e `status` chegariam do servidor sem existir aqui, e o TypeScript
 * ficaria verde enquanto a tela não mostrasse o estado da renda.
 */
export type Income = components['schemas']['IncomeRead'];

/** `expected | received | overdue | cancelled` — derivado no servidor (ADR 0034).
 *
 * Nunca recalcule no cliente: `overdue` depende de "hoje", e o fuso do navegador
 * dá outra resposta perto da meia-noite. */
export type IncomeStatus = 'expected' | 'received' | 'overdue' | 'cancelled';

export const INCOME_STATUS_LABEL: Record<string, string> = {
  expected: 'prevista',
  received: 'recebida',
  overdue: 'atrasada',
  cancelled: 'cancelada',
};

export function useIncome(month?: string) {
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ['income', month],
    queryFn: async (): Promise<Income[]> => {
      const response = await apiClient.get(`/me/income/`, {
        params: { month },
      });
      return response.data;
    },
  });

  // Pelo contrato único (`ws-events`), não à mão: a lista escrita aqui já tinha
  // divergido dele — faltavam `me-overview` e `me-reports`, que `BY_PREFIX.income`
  // inclui —, então lançar uma renda não atualizava a Visão global nem "Seus
  // relatórios" até um F5. Duas cópias da mesma regra divergem na primeira
  // mudança; foi essa a lição do `GLOBAIS`.
  const invalidate = () => {
    invalidateForEvent(queryClient, 'income.changed', null);
  };

  const createMutation = useMutation({
    mutationFn: async (data: { title: string; amount: number; received_at: string; description?: string; currency?: string }) => {
      const response = await apiClient.post(`/me/income/`, data);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<{ title: string; amount: number; received_at: string; description: string; currency: string }> }) => {
      const response = await apiClient.put(`/me/income/${id}`, data);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/me/income/${id}`);
    },
    onSuccess: invalidate,
  });

  // As três transições de ESTADO da renda (ADR 0034). Separadas do `update`
  // porque não são edição de cadastro: confirmar o recebimento é registrar um
  // fato de caixa, e ele tem data e conta próprias.
  const receiveMutation = useMutation({
    mutationFn: async ({
      id, receivedOn, accountId,
    }: { id: number; receivedOn?: string; accountId?: number | null }) => {
      const response = await apiClient.post(`/me/income/${id}/receive`, {
        received_on: receivedOn,
        account_id: accountId ?? null,
      });
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const unreceiveMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await apiClient.post(`/me/income/${id}/unreceive`);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  const cancelMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await apiClient.post(`/me/income/${id}/cancel`);
      return response.data as Income;
    },
    onSuccess: invalidate,
  });

  return {
    incomes: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    receive: receiveMutation.mutateAsync,
    unreceive: unreceiveMutation.mutateAsync,
    cancel: cancelMutation.mutateAsync,
    isChangingStatus:
      receiveMutation.isPending || unreceiveMutation.isPending || cancelMutation.isPending,
  };
}
