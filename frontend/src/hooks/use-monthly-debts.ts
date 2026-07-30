import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

// Valores vêm da rota Dict[str, Any] (jsonable_encoder → número), mas coagimos
// com Number() na exibição para ser robusto a número OU string.
export interface LedgerMember {
  user_id: number;
  paid: number;
  owed: number;
  balance: number;
}

export interface LedgerExpense {
  id: number;
  title: string;
  total_amount: number;
  status: string;
  is_paid: boolean;
  transaction_date: string;
  installment_no: number | null;
  installments_of: number | null;
  payers: { user_id: number; amount: number }[];
  splits: { user_id: number; computed_amount: number }[];
}

export interface LedgerDebt {
  debtor_id: number;
  creditor_id: number;
  amount: number;
}

export interface LedgerSettlement {
  id: number;
  from_user_id: number;
  to_user_id: number;
  amount: number;
  note?: string | null;
  settled_at: string;
}

export interface MonthlyLedger {
  month: string;
  base_currency: string;
  members: LedgerMember[];
  net_debts: LedgerDebt[];
  expenses: LedgerExpense[];
  settled_total: number;
  settlements: LedgerSettlement[];
  totals: { total: number; paid: number; open: number };
}

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
