import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';

// Tipos GERADOS do OpenAPI (npm run typegen) — nunca espelhados à mão.
export type BalanceRead = components['schemas']['BalanceRead'];
export type AccountBalanceRead = components['schemas']['AccountBalanceRead'];
export type AccountStatementRead = components['schemas']['AccountStatementRead'];
export type AdjustmentRead = components['schemas']['AdjustmentRead'];
export type ProjectionLine = components['schemas']['ProjectionLine'];

/** Rótulo de cada origem do extrato da conta.
 *
 * Vem do backend como string estável (`CashFlowService.CASH_SOURCES` mais as três
 * origens de saldo). Traduzir aqui, e não lá, é a mesma divisão de sempre: o
 * servidor manda o fato, a tela escolhe a palavra. */
export const SOURCE_LABELS: Record<string, string> = {
  opening_balance: 'Saldo inicial',
  adjustment: 'Ajuste de saldo',
  transfer_in: 'Transferência recebida',
  transfer_out: 'Transferência enviada',
  transaction: 'Lançamento pago',
  statement_payment: 'Pagamento de fatura',
  settlement_sent: 'Acerto enviado',
  settlement_received: 'Acerto recebido',
  financing_installment: 'Parcela de financiamento',
  income: 'Renda recebida',
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/** Saldo por conta + projeção até o fim do mês (ADR 0034).
 *
 * Família `me-balance`, GLOBAL: conta é recurso pessoal e não leva `workspaceId`
 * na chave (ver `GLOBAIS` em lib/ws-events.ts). */
export function useBalance(month?: string) {
  const query = useQuery({
    queryKey: ['me-balance', month ?? null],
    queryFn: async (): Promise<BalanceRead> => {
      const response = await apiClient.get('/me/balance', {
        params: month ? { month } : undefined,
      });
      return response.data;
    },
  });

  return {
    balance: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}

/** Extrato de UMA conta, com saldo corrente linha a linha. */
export function useAccountStatement(accountId: number | null, month?: string) {
  const query = useQuery({
    queryKey: ['account-statement', accountId, month ?? null],
    // `enabled` e não um id falso: uma query desabilitada não é refeita por
    // `refetchQueries`, e disparar com `null` renderia um 404 no console.
    enabled: accountId !== null,
    queryFn: async (): Promise<AccountStatementRead> => {
      const response = await apiClient.get(
        `/me/payment-accounts/${accountId}/statement`,
        { params: month ? { month } : undefined },
      );
      return response.data;
    },
  });

  return {
    statement: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}

/** Saldo inicial e conciliação — as duas escritas que só o saldo tem. */
export function useAccountBalanceActions() {
  const queryClient = useQueryClient();

  // Saldo mexe em tudo que depende de dinheiro: o saldo em si, o extrato da
  // conta e a lista de contas (que mostra o número).
  const invalidate = () => {
    for (const key of ['me-balance', 'account-statement', 'payment-accounts']) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const setOpeningBalance = useMutation({
    mutationFn: async ({
      accountId,
      amount,
      asOf,
    }: {
      accountId: number;
      amount: string;
      asOf: string;
    }) => {
      const response = await apiClient.put(
        `/me/payment-accounts/${accountId}/opening-balance`,
        { amount, as_of: asOf },
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  const adjust = useMutation({
    mutationFn: async ({
      accountId,
      realBalance,
      occurredOn,
      note,
    }: {
      accountId: number;
      realBalance: string;
      occurredOn?: string;
      note?: string;
    }) => {
      const response = await apiClient.post(
        `/me/payment-accounts/${accountId}/adjustment`,
        { real_balance: realBalance, occurred_on: occurredOn, note },
      );
      return response.data as AdjustmentRead;
    },
    onSuccess: invalidate,
  });

  return {
    setOpeningBalance: setOpeningBalance.mutateAsync,
    adjust: adjust.mutateAsync,
    isSaving: setOpeningBalance.isPending || adjust.isPending,
  };
}
