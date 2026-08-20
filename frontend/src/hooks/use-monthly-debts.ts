import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/*
 * Derivados do OpenAPI, não escritos à mão.
 *
 * Estas cinco interfaces existiam manualmente com o aviso "os valores vêm da
 * rota Dict[str, Any] e coagimos com Number() para ser robusto a número OU
 * string" — ou seja, o cliente não sabia o formato do que recebia. Pior: a mesma
 * entidade tinha DUAS declarações divergentes (aqui `amount: number`, em
 * `DebtsPage.tsx` `amount: string`) e nada acusava.
 *
 * Agora a rota declara schema e o formato é o do resto do app: string decimal
 * (`docs/API.md`). O `Number()` na exibição continua correto — só deixou de ser
 * um chute.
 */
export type LedgerMember = components['schemas']['LedgerMember'];
export type LedgerExpense = components['schemas']['LedgerExpense'];
export type LedgerDebt = components['schemas']['DebtRow'];
export type LedgerSettlement = components['schemas']['LedgerSettlement'];
export type MonthlyLedger = components['schemas']['MonthlyLedgerRead'];

export function useMonthlyDebts(month: string) {
  const currentWorkspaceId = useWorkspaceId();

  const query = useQuery({
    queryKey: ['debts-monthly', currentWorkspaceId, month],
    queryFn: async (): Promise<MonthlyLedger | null> => {
      if (!currentWorkspaceId) return null;
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/debts/monthly`,
        { params: { month } },
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!month,
  });

  return {
    ledger: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}
