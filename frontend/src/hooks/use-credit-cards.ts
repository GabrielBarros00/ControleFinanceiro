import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import { useUIStore } from '@/stores';

export interface CardStatement {
  id: number;
  month: string;
  closing_date: string;
  due_date: string;
  status: 'open' | 'closed' | 'paid' | 'overdue';
  computed_total: string;
  closed_at: string | null;
  paid_at: string | null;
  is_overdue: boolean;
  // Ciclo aberto de hoje (calculado no backend a partir do dia de fechamento).
  // Não é o mesmo que "a mais recente": compra com data futura cria fatura à frente.
  is_current: boolean;
}

export interface CreditCardSummary {
  id: number;
  name: string;
  limit: string;
  closing_day: number;
  due_day: number;
  currency: string;
  committed_amount: string;
  available_limit: string;
}

export function useCreditCards() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['credit-cards', currentWorkspaceId],
    queryFn: async () => {
      if (!currentWorkspaceId) return [];
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/credit-cards/`);
      return response.data;
    },
    enabled: !!currentWorkspaceId
  });

  const createMutation = useMutation({
    mutationFn: async (data: { name: string; limit: number; closing_day: number; due_day: number }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/credit-cards/`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-cards', currentWorkspaceId] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: Partial<{ name: string; limit: number; closing_day: number; due_day: number }>;
    }) => {
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/credit-cards/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-cards', currentWorkspaceId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/credit-cards/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-cards', currentWorkspaceId] });
    },
  });

  return {
    cards: listQuery.data || [],
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
  };
}

export function useCardStatements(cardId: number | null) {
  const { currentWorkspaceId } = useUIStore();

  const statementsQuery = useQuery({
    queryKey: ['statements', currentWorkspaceId, cardId],
    queryFn: async (): Promise<CardStatement[]> => {
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/credit-cards/${cardId}/statements`
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!cardId,
  });

  return {
    statements: statementsQuery.data ?? [],
    isLoading: statementsQuery.isLoading,
  };
}

export function useStatementDetail(cardId: number | null, statementId: number | null) {
  const { currentWorkspaceId } = useUIStore();

  const detailQuery = useQuery({
    queryKey: ['statements', currentWorkspaceId, cardId, statementId],
    queryFn: async () => {
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/credit-cards/${cardId}/statements/${statementId}`
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!cardId && !!statementId,
  });

  return {
    statement: detailQuery.data ?? null,
    isLoading: detailQuery.isLoading,
  };
}

export interface PayStatementInput {
  account_id?: number | null;
  amount?: number;
  note?: string;
}

// Ações do ciclo da fatura (ADR 0011): fechar → pagar (com conta) → reabrir.
// Todas invalidam faturas E cartões (o limite disponível muda quando paga).
export function useStatementActions(cardId: number | null) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const base = `/workspaces/${currentWorkspaceId}/credit-cards/${cardId}/statements`;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['statements', currentWorkspaceId, cardId] });
    // Fechar/pagar fatura muda limite comprometido e Endividamento
    invalidateForEvent(queryClient, 'credit_card.statement_paid', currentWorkspaceId);
  };

  const close = useMutation({
    mutationFn: async (statementId: number) => {
      const res = await apiClient.post(`${base}/${statementId}/close`);
      return res.data;
    },
    onSuccess: invalidate,
  });

  const pay = useMutation({
    mutationFn: async ({ statementId, ...body }: PayStatementInput & { statementId: number }) => {
      const res = await apiClient.post(`${base}/${statementId}/pay`, body);
      return res.data;
    },
    onSuccess: invalidate,
  });

  const reopen = useMutation({
    mutationFn: async (statementId: number) => {
      const res = await apiClient.post(`${base}/${statementId}/reopen`);
      return res.data;
    },
    onSuccess: invalidate,
  });

  return {
    close: close.mutateAsync,
    pay: pay.mutateAsync,
    reopen: reopen.mutateAsync,
    isPending: close.isPending || pay.isPending || reopen.isPending,
  };
}
