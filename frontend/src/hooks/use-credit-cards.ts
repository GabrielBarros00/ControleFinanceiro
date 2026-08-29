import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { components } from '@/types/api.gen';

/**
 * Derivado do OpenAPI, não escrito à mão: a interface manual daqui já divergiu do
 * backend em silêncio uma vez, e `paid_amount`/`remaining_amount` (pagamento
 * parcial) nasceriam invisíveis para o TypeScript pelo mesmo caminho.
 *
 * `is_current` marca o ciclo aberto de hoje — não é "a mais recente": compra com
 * data futura cria uma fatura à frente que não é a atual.
 */
export type CardStatement = components['schemas']['StatementListItemRead'];
export type CardStatementDetail = components['schemas']['StatementDetailRead'];
export type StatementTransaction = components['schemas']['StatementTransactionRead'];

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

/** Uma fatura para a qual a compra pode ser movida (ADR 0032). */
export interface StatementShiftOption {
  /** O deslocamento que alcança esta fatura. A tela devolve este número ao
   *  backend em vez de calcular a aritmética de ciclo — ela é do servidor. */
  shift: number;
  month: string;
  closing_date: string;
  due_date: string;
  exists: boolean;
  /** false = fechada/paga. A opção aparece desabilitada, com o motivo. */
  available: boolean;
  status: string | null;
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
  /** O deslocamento em vigor nesta consulta. */
  shift: number;
  /** Dias entre a compra e o fechamento da fatura de destino; `null` quando a
   *  pergunta não faz sentido (destino deslocado ou rolado). É o que sustenta o
   *  aviso da janela de fechamento. */
  days_to_closing: number | null;
  options: StatementShiftOption[];
}

/**
 * A janela em que vale avisar que a compra pode escorregar de fatura.
 *
 * TRÊS dias, não cinco. Num ciclo de ~30 dias, cinco fariam o aviso aparecer em
 * uma de cada seis compras no cartão, e a captura da maioria dos
 * estabelecimentos sai em até dois dias úteis — um aviso que quase sempre é
 * falso alarme fica invisível em duas semanas, e aí falha justamente na compra
 * em que importava.
 */
export const JANELA_DE_FECHAMENTO_DIAS = 3;

/**
 * "Esta compra pode cair na fatura seguinte."
 *
 * `days_to_closing` vem `null` quando o destino não é o ciclo natural da compra
 * (o usuário já deslocou, ou a fatura rolou por estar fechada) — nos dois casos
 * não há o que avisar, e é por isso que a checagem de nulo vem antes.
 */
export function naJanelaDeFechamento(target: StatementTarget | null): boolean {
  const dias = target?.days_to_closing;
  return dias != null && dias >= 1 && dias <= JANELA_DE_FECHAMENTO_DIAS;
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
export function useStatementTarget(
  cardId?: number | null,
  date?: string | null,
  shift = 0,
) {
  const query = useQuery({
    // `shift` na chave: sem ele, mudar o deslocamento devolvia a resposta
    // cacheada do anterior e o destino anunciado ficava um passo atrás do que a
    // pessoa acabou de marcar.
    queryKey: ['statement-target', cardId, date, shift],
    queryFn: async (): Promise<StatementTarget> => {
      const response = await apiClient.get(
        `/me/credit-cards/${cardId}/statement-for`,
        { params: { on: date, shift } },
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
    // `currency` opcional: omitida, o backend resolve para a moeda de relatório
    // do dono (`resolve_personal_currency`). O tipo não a tinha, então o formulário
    // não conseguia enviá-la nem que quisesse — e não havia como criar um cartão
    // em moeda diferente da que estivesse ativa no momento.
    mutationFn: async (data: {
      name: string; limit: number; closing_day: number; due_day: number; currency?: string;
    }) => {
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
    queryFn: async (): Promise<CardStatementDetail> => {
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
  /** Omitido = quita o saldo restante. Maior que o saldo é recusado (409). */
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
