import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/**
 * Contas a pagar (ADR 0029): o lançamento que ainda não virou saída de caixa.
 *
 * Duas leituras, duas chaves. `me-payables` é GLOBAL — soma todos os espaços da
 * pessoa e por isso não leva workspace na chave (ver `GLOBAIS` em ws-events);
 * `payables` é do espaço e leva. Escrever é sempre pelo espaço: o lançamento
 * pertence a um, e quem pode marcá-lo como pago é quem pode editá-lo.
 *
 * Tipos do OpenAPI, não escritos à mão — divergir do backend é erro de compilação.
 */
export type Payables = components['schemas']['PayablesRead'];
export type PayableEntry = components['schemas']['PayableEntry'];

/** O que EU tenho a pagar, somando meus espaços. */
export function useMyPayables(month?: string) {
  const query = useQuery({
    queryKey: ['me-payables', month],
    queryFn: async (): Promise<Payables> => {
      const res = await apiClient.get('/me/payables', {
        params: month ? { month } : undefined,
      });
      return res.data;
    },
  });
  return {
    payables: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

/** O que ESTE espaço tem em aberto, de quem quer que vá pagar. */
export function useWorkspacePayables(month?: string) {
  const workspaceId = useWorkspaceId();
  const query = useQuery({
    queryKey: ['payables', workspaceId, month],
    queryFn: async (): Promise<Payables> => {
      const res = await apiClient.get(`/workspaces/${workspaceId}/payables`, {
        params: month ? { month } : undefined,
      });
      return res.data;
    },
    enabled: !!workspaceId,
  });
  return {
    payables: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

interface SettleArgs {
  /**
   * Sempre explícito, e por isso obrigatório: a tela GLOBAL lista contas de
   * espaços diferentes, e a escrita é por espaço. Deixá-lo cair no
   * `useWorkspaceId()` mandaria a conta da Casa para a rota da Viagem — a
   * requisição responderia 200 com `updated: 0`, e a linha continuaria na tela
   * sem nenhum erro.
   */
  workspaceId: number;
  transactionIds: number[];
  settled: boolean;
  /** Dia em que o dinheiro saiu (YYYY-MM-DD). Ausente = hoje. */
  settledOn?: string;
}

/** Marcar (ou desmarcar) o pagamento de várias contas de uma vez. */
export function useSettlePayables() {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async ({ workspaceId, transactionIds, settled, settledOn }: SettleArgs) => {
      const res = await apiClient.post(`/workspaces/${workspaceId}/payables/settle`, {
        transaction_ids: transactionIds,
        settled,
        ...(settledOn ? { settled_on: settledOn } : {}),
      });
      return res.data as components['schemas']['SettleResult'];
    },
    // Liquidar move dinheiro para o caixa do mês: mesmo alcance de um
    // `transaction.bulk_updated` vindo pelo WebSocket — extrato, relatórios,
    // Seu mês e as duas listas de contas a pagar.
    onSuccess: (_data, vars) =>
      invalidateForEvent(queryClient, 'transaction.bulk_updated', vars.workspaceId),
  });

  return { settle: mutation.mutateAsync, isSettling: mutation.isPending };
}
