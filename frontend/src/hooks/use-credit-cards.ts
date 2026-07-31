import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';

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

/** Fatura que pede atenção: a NÃO paga mais antiga com valor > 0 (ou null). */
export interface CardNextDue {
  statement_id: number;
  month: string;
  status: 'open' | 'closed' | 'paid' | 'overdue';
  closing_date: string;
  due_date: string;
  amount: string;
  is_overdue: boolean;
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
  next_due: CardNextDue | null;
}

/** Destino de uma compra: em qual fatura ela cai (derivado no servidor). */
export interface StatementTarget {
  month: string;
  closing_date: string;
  due_date: string;
  /** false = a fatura ainda não existe; nasce no primeiro lançamento. */
  exists: boolean;
  /** true = rolou para frente porque a fatura do mês da compra já estava fechada. */
  rolled_forward: boolean;
}

/**
 * Em qual fatura a compra vai cair, perguntando ao SERVIDOR (ADR 0002: o cliente
 * nunca escolhe a fatura). A regra tem duas partes que ninguém adivinha olhando o
 * formulário — a partir do dia de fechamento a compra vai para o mês seguinte, e
 * se aquela fatura já estiver fechada ela rola para frente — e o usuário só
 * descobria o resultado depois de salvar.
 *
 * Reimplementar a regra aqui seria uma segunda cópia dela, que divergiria na
 * primeira mudança; a rota é só leitura e não cria fatura nenhuma.
 */
export function useStatementTarget(cardId?: number | null, date?: string | null) {
  const query = useQuery({
    queryKey: ['statement-target', cardId, date],
    queryFn: async (): Promise<StatementTarget> => {
      const response = await apiClient.get(
        `/me/credit-cards/${cardId}/statement-for`,
        { params: { on: date } },
      );
      return response.data;
    },
    enabled: cardId != null && !!date,
  });
  return { target: query.data ?? null, isLoading: query.isLoading };
}

export function useCreditCards() {
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ['credit-cards'],
    queryFn: async () => {
      const response = await apiClient.get(`/me/credit-cards/`);
      return response.data;
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data: { name: string; limit: number; closing_day: number; due_day: number }) => {
      const response = await apiClient.post(`/me/credit-cards/`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-cards'] });
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
      const response = await apiClient.put(`/me/credit-cards/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-cards'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/me/credit-cards/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-cards'] });
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

  const statementsQuery = useQuery({
    queryKey: ['statements', cardId],
    queryFn: async (): Promise<CardStatement[]> => {
      const response = await apiClient.get(
        `/me/credit-cards/${cardId}/statements`
      );
      return response.data;
    },
    enabled: !!cardId,
  });

  return {
    statements: statementsQuery.data ?? [],
    isLoading: statementsQuery.isLoading,
  };
}

export function useStatementDetail(cardId: number | null, statementId: number | null) {

  const detailQuery = useQuery({
    queryKey: ['statements', cardId, statementId],
    queryFn: async () => {
      const response = await apiClient.get(
        `/me/credit-cards/${cardId}/statements/${statementId}`
      );
      return response.data;
    },
    enabled: !!cardId && !!statementId,
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
export function useStatementActions(cardId: number | null) {
  const queryClient = useQueryClient();

  const base = `/me/credit-cards/${cardId}/statements`;

  // Passa pelo contrato único (`ws-events`) em vez de invalidar só a fatura
  // aberta. Pagar uma fatura muda o limite disponível do cartão, sai dos
  // Compromissos e — desde o ADR 0022 — é saída de caixa do mês na Visão
  // global. Invalidar `['statements', cardId]` sozinho deixava as três telas
  // com o número velho até um F5.
  const invalidate = () => {
    invalidateForEvent(queryClient, 'credit_card.statement_paid', null);
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
