import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/**
 * De quais MESES vem o saldo acumulado — a ponte entre `use-debts` ("quanto") e
 * `use-monthly-debts` ("como foi agosto").
 *
 * Existe porque o saldo de `/debts` é cumulativo e a tela mostrava só o total:
 * R$ 320 pode ser a soma de três meses que ninguém fechou, e lido sozinho vira
 * uma cobrança do mês corrente.
 *
 * A resposta reconcilia — `balance == Σ months + older + unassigned` — e é isso
 * que `BalanceOrigin` desenha. `isError`/`refetch` obrigatórios (ERR-001): sem
 * eles a falha vira `undefined`, a lista fica vazia e a tela diz "todo o saldo
 * vem de lugar nenhum".
 */
export type DebtsByMonth = components['schemas']['DebtsByMonthRead'];
export type MonthBalance = components['schemas']['MonthBalance'];
export type WorkspaceMonthsGroup = components['schemas']['WorkspaceMonthsGroup'];
export type PersonalDebtsByMonth = components['schemas']['PersonalDebtsByMonthRead'];

export function useDebtsByMonth() {
  const currentWorkspaceId = useWorkspaceId();

  const query = useQuery({
    queryKey: ['debts-by-month', currentWorkspaceId],
    queryFn: async (): Promise<DebtsByMonth | null> => {
      if (!currentWorkspaceId) return null;
      const res = await apiClient.get(`/workspaces/${currentWorkspaceId}/debts/by-month`);
      return res.data;
    },
    enabled: !!currentWorkspaceId,
  });

  return {
    origem: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

/** O par global: uma seção por casa, cada uma na moeda dela (ADR 0020 — não há
 *  total agregado a somar entre casas). */
export function useMyDebtsByMonth() {
  const query = useQuery({
    queryKey: ['me-debts-by-month'],
    queryFn: async (): Promise<PersonalDebtsByMonth> => {
      const res = await apiClient.get('/me/debts/by-month');
      return res.data;
    },
  });

  return {
    grupos: query.data?.by_workspace ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}
