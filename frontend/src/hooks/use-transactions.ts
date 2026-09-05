import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { TransactionRead } from '@/types/transaction';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/**
 * O corpo de criação/edição de lançamento, vindo do OpenAPI.
 *
 * Era `Record<string, unknown>` nas três mutações de escrita — o NÚCLEO do app
 * sem checagem nenhuma: um campo renomeado no backend, ou um typo no nome de uma
 * chave, chegava ao servidor sem que o `tsc` piscasse. O mesmo corpo serve ao
 * grupo de parcelas: editar uma compra parcelada é editar a definição da COMPRA,
 * não a da parcela.
 */
type ApiTransactionCreate = components['schemas']['TransactionCreate'];

/**
 * Campos que o OpenAPI marca como `required` de verdade. O resto tem default no
 * servidor (`status: confirmed`, `split_mode: transaction`, `currency`…).
 *
 * A distinção precisa ser feita aqui porque o `openapi-typescript` roda com
 * `default-non-nullable` (o padrão dele): campo COM default vira obrigatório no
 * tipo gerado. Isso está certo para uma RESPOSTA — o servidor sempre devolve o
 * campo — e errado para um CORPO DE REQUISIÇÃO, onde omiti-lo é justamente o que
 * aciona o default. Sem esta correção, o tipo obrigaria a tela a reenviar o
 * mundo em cada edição.
 */
type ObrigatoriosNaCriacao = 'title' | 'total_amount' | 'transaction_date' | 'payers';

export type TransactionPayload =
  Pick<ApiTransactionCreate, ObrigatoriosNaCriacao> &
  Partial<Omit<ApiTransactionCreate, ObrigatoriosNaCriacao>>;

/**
 * O corpo da EDIÇÃO de um lançamento — parcial, e é outro schema de propósito.
 *
 * `PUT /transactions/{id}` aceita `TransactionUpdate` (todo campo opcional):
 * mudar só o título não obriga a reenviar a divisão inteira. Já o PUT do GRUPO
 * de parcelas usa `TransactionCreate`, porque ali se envia a definição completa
 * da compra para ela ser refatiada.
 */
export type TransactionUpdatePayload = components['schemas']['TransactionUpdate'];

export interface TransactionFilters {
  page?: number;
  limit?: number;
  month?: string;
  search?: string;
  category_id?: number;
  payment_method?: string;
  tag_id?: number;
  /**
   * Liquidação (ADR 0029): `false` traz só o que ainda não saiu do caixa.
   * `undefined` = tudo, que é a leitura padrão do extrato.
   */
  settled?: boolean;
  /** Só o que ainda não foi categorizado — destino do convite dos Relatórios. */
  uncategorized?: boolean;
}

export interface TransactionListResponse {
  items: TransactionRead[];
  total: number;
  /** Soma do filtro inteiro, não só da página que veio. */
  total_amount: string | number;
  page: number;
  limit: number;
  total_pages: number;
}

export function useTransactions(
  filters: TransactionFilters = { page: 1, limit: 10 },
  // `false` desliga a listagem e deixa só as mutations. Existe porque o
  // TransactionDetailHost (montado no AppShell, ou seja, em TODAS as telas)
  // chamava este hook só para pegar create/update/delete — e disparava uma
  // requisição de extrato a mais em cada página, duas na Home.
  enableList = true,
) {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();
  const {
    page = 1, limit = 10, month, search, category_id, payment_method, tag_id, settled,
  } = filters;

  // Fetch transactions
  //
  // Filtro NOVO entra em DOIS lugares — a chave e os `params` —, e esquecer um
  // dos dois falha em silêncio: fora da chave, mudar o filtro não refaz a
  // consulta e a lista fica congelada; fora dos `params`, o backend devolve tudo
  // e o controle na tela vira decoração. Os dois casos parecem "o filtro não
  // funciona" e nenhum quebra teste de tipo.
  const listQuery = useQuery({
    queryKey: [
      'transactions', currentWorkspaceId, page, limit, month, search,
      category_id, payment_method, tag_id, settled,
    ],
    queryFn: async (): Promise<Pick<TransactionListResponse, 'items' | 'total' | 'total_pages'> & Partial<TransactionListResponse>> => {
      if (!currentWorkspaceId) return { items: [], total: 0, total_amount: 0, total_pages: 1 };
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/transactions/`, {
        params: {
          limit,
          page,
          month,
          search,
          category_id,
          payment_method: payment_method || undefined,
          tag_id: tag_id || undefined,
          // `?? undefined`, não `|| undefined`: `false` é uma resposta legítima
          // ("só a pagar") e o `||` a transformaria em "sem filtro".
          settled: settled ?? undefined,
        }
      });
      return response.data; // { items, total, page, limit, total_pages }
    },
    enabled: !!currentWorkspaceId && enableList
  });

  // Mesma tabela que o WebSocket usa: quem lança vê o mesmo que os outros
  // membros veem (extrato, detalhe, parcelas, relatórios, previsão, dívidas,
  // endividamento e fatura do cartão).
  const invalidateTransactionData = () =>
    invalidateForEvent(queryClient, 'transaction.updated', currentWorkspaceId);

  // Create transaction
  const createMutation = useMutation({
    mutationFn: async (data: TransactionPayload) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/transactions/`, data);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  // Update transaction
  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number, data: TransactionUpdatePayload }) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/transactions/${id}`, data);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  // Delete transaction (uma parcela avulsa ou lançamento comum)
  /*
   * Excluir devolve QUANTOS ANEXOS foram junto.
   *
   * A exclusão é soft e agora tem "desfazer" (`restoreMutation`), mas o anexo é
   * apagado de verdade — um recibo preso a uma despesa inalcançável ocuparia
   * cota para sempre. Restaurar traz a despesa SEM os recibos, e é este número
   * que permite ao aviso dizer isso em vez de deixar a pessoa descobrir quando
   * for procurar o comprovante.
   */
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const res = await apiClient.delete(`/workspaces/${currentWorkspaceId}/transactions/${id}`);
      return res.data as { status: string; attachments_removed?: number };
    },
    onSuccess: invalidateTransactionData
  });

  /** Desfazer a exclusão — o caminho de volta que o soft delete já permitia. */
  const restoreMutation = useMutation({
    mutationFn: async (id: number) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      await apiClient.post(`/workspaces/${currentWorkspaceId}/transactions/${id}/restore`);
    },
    onSuccess: invalidateTransactionData
  });

  // Excluir a COMPRA parcelada inteira: soft-delete de todas as parcelas vivas
  // do grupo de uma vez (backend preserva as já pagas).
  const deleteGroupMutation = useMutation({
    mutationFn: async (id: number): Promise<{ deleted: number; skipped_paid: number }> => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.delete(`/workspaces/${currentWorkspaceId}/transactions/${id}/installment-group`);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  // Editar a COMPRA parcelada inteira (refatia total/nº de parcelas; congela pagas)
  const updateGroupMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number, data: TransactionPayload }) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const response = await apiClient.put(`/workspaces/${currentWorkspaceId}/transactions/${id}/installment-group`, data);
      return response.data;
    },
    onSuccess: invalidateTransactionData
  });

  return {
    transactions: listQuery.data?.items || [],
    total: listQuery.data?.total || 0,
    // Soma do filtro inteiro (o backend agrega); Number() por vir como Decimal
    totalAmount: Number(listQuery.data?.total_amount ?? 0),
    totalPages: listQuery.data?.total_pages || 1,
    currentPage: listQuery.data?.page || 1,
    isLoading: listQuery.isLoading,
    isError: listQuery.isError,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    updateGroup: updateGroupMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    restore: restoreMutation.mutateAsync,
    removeGroup: deleteGroupMutation.mutateAsync,
    isMutating: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending
  };
}

// Busca um único lançamento pelo id (detalhe/preview). Sempre traz payers,
// splits, items e parcela — a mesma fonte do TransactionRead da lista.
export function useTransaction(id?: number | null) {
  const currentWorkspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: ['transaction', currentWorkspaceId, id],
    queryFn: async (): Promise<TransactionRead> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/transactions/${id}`);
      return response.data;
    },
    enabled: !!currentWorkspaceId && id != null,
  });

  return {
    transaction: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}

export interface InstallmentGroupSummary {
  installment_group_id: string;
  installments_of: number;
  count_live: number;
  paid_count: number;
  group_total: string | number;
  title: string;
  // Definição da compra INTEIRA (formato TransactionRead) p/ pré-preencher o form
  whole: TransactionRead;
}

// Resumo do grupo de parcelas (total da compra, nº, quantas pagas, definição
// inteira). Usado só ao editar uma compra parcelada.
export function useInstallmentGroup(id?: number | null, enabled = true) {
  const currentWorkspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: ['installment-group', currentWorkspaceId, id],
    queryFn: async (): Promise<InstallmentGroupSummary> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/transactions/${id}/installment-group`);
      return response.data;
    },
    enabled: !!currentWorkspaceId && id != null && enabled,
  });

  return { group: query.data ?? null, isLoading: query.isLoading };
}

/**
 * Categorizar várias despesas de uma vez.
 *
 * Hook próprio, e não mais um campo em `useTransactions`: aquele hook já
 * carrega a LISTA (com filtros, paginação e cache por mês), e quem só quer
 * disparar o lote não deveria assinar tudo isso. O `invalidate` é o mesmo
 * conjunto de chaves, porque categorizar muda relatório, extrato e a própria
 * lista.
 */
export function useBulkCategorize() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();

  const mutation = useMutation({
    mutationFn: async (
      { transactionIds, categoryId }: { transactionIds: number[]; categoryId: number },
    ) => {
      if (!currentWorkspaceId) throw new Error('Workspace not selected');
      const res = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/transactions/bulk-categorize`,
        { transaction_ids: transactionIds, category_id: categoryId },
      );
      return res.data as { status: string; updated: number; skipped: number };
    },
    onSuccess: () =>
      invalidateForEvent(queryClient, 'transaction.bulk_updated', currentWorkspaceId ?? undefined),
  });

  return {
    categorizarEmLote: mutation.mutateAsync,
    isCategorizando: mutation.isPending,
  };
}
