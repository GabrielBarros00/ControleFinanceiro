import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { components } from '@/types/api.gen';

/**
 * Acertos entre pessoas na camada GLOBAL (ADR 0027).
 *
 * Par de `use-debts`/`use-monthly-debts`/`use-settlements`, que são do workspace:
 * aqueles respondem "quem deve a quem NESTA casa", estes respondem "com quem eu
 * me acerto, somando todas". Como o resto de `/me/*`, a chave NÃO leva
 * `workspaceId` — o recorte é a pessoa (ver `use-overview.ts`).
 *
 * Leitura, mais o DESFAZER (`useDesfazerAcerto`). Registrar continua em
 * `useSettlements`, que fala com `/workspaces/{ws}/settlements`: é lá que vivem
 * a direção e o teto do ADR 0009 e a trava contra sobrepagamento, e a tela
 * global só informa de qual casa é a linha em que a pessoa clicou.
 *
 * Desfazer veio para cá porque a alternativa era pior: a tela global registrava
 * o acerto e mandava a pessoa a OUTRA tela para corrigi-lo. Quem errou o valor
 * teria de descobrir de qual espaço era a linha, navegar até lá e achar o
 * acerto de novo — e corrigir é o que se faz logo depois de errar.
 *
 * Os três devolvem `isError`/`refetch` (ERR-001): sem isso uma falha de API vira
 * `data === undefined`, os totais caem no `?? 0` e a tela anuncia "você não deve
 * nada" — que é uma informação financeira, e seria falsa.
 */
export type PersonalDebts = components['schemas']['PersonalDebtsRead'];
export type WorkspaceDebtGroup = components['schemas']['WorkspaceDebtGroup'];
export type PersonDebt = components['schemas']['PersonDebt'];
export type ExcludedWorkspace = components['schemas']['ExcludedWorkspace'];

export function useMyDebts() {
  const query = useQuery({
    queryKey: ['me-debts'],
    queryFn: async (): Promise<PersonalDebts> => {
      const res = await apiClient.get('/me/debts');
      return res.data;
    },
  });
  return {
    debts: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

export type PersonalMonthlyDebts = components['schemas']['PersonalMonthlyDebtsRead'];
export type WorkspaceMonthlyLedger = components['schemas']['WorkspaceMonthlyLedger'];

export function useMyMonthlyDebts(month?: string) {
  const query = useQuery({
    queryKey: ['me-debts-monthly', month],
    queryFn: async (): Promise<PersonalMonthlyDebts> => {
      const res = await apiClient.get('/me/debts/monthly', {
        params: month ? { month } : undefined,
      });
      return res.data;
    },
    enabled: !!month,
  });
  return {
    monthly: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

export type PersonalSettlements = components['schemas']['PersonalSettlementsRead'];
export type PersonalSettlementEntry = components['schemas']['PersonalSettlementEntry'];

export function useMySettlementsHistory(limit = 50) {
  const query = useQuery({
    queryKey: ['me-settlements', limit],
    queryFn: async (): Promise<PersonalSettlements> => {
      const res = await apiClient.get('/me/settlements', { params: { limit } });
      return res.data;
    },
  });
  return {
    settlements: query.data?.items ?? [],
    // Total ANTES da paginação: a tela precisa poder dizer que truncou, senão as
    // 50 primeiras linhas passam por "todas".
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

/**
 * Desfazer um acerto a partir da tela global.
 *
 * O espaço vem do PARÂMETRO, e não da URL ou de um "workspace atual": esta tela
 * lista acertos de vários, e o id do acerto sozinho não diz para qual rota ele
 * vai. Mandar para o espaço errado responderia 404 falando de um acerto que
 * existe.
 *
 * Não há edição de acerto no produto — corrigir é desfazer e registrar de novo.
 * É o mesmo efeito (um acerto não tem filhos) com metade da superfície.
 */
export function useDesfazerAcerto() {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async ({ workspaceId, id }: { workspaceId: number; id: number }) => {
      await apiClient.delete(`/workspaces/${workspaceId}/settlements/${id}`);
      return { workspaceId };
    },
    // Mesmo alcance de registrar: o acerto mexe no saldo global, no ledger do
    // mês e no histórico das duas telas.
    onSuccess: ({ workspaceId }) =>
      invalidateForEvent(queryClient, 'settlement.deleted', workspaceId),
  });

  return { desfazer: mutation.mutateAsync, isDesfazendo: mutation.isPending };
}
