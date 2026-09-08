import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';

export interface Financing {
  id: number;
  title: string;
  description?: string | null;
  total_amount: string;
  interest_rate: string;
  start_date: string;
  installments_count: number;
  method: 'SAC' | 'PRICE';
  status: 'active' | 'settled' | 'simulated';
  // O backend sempre devolveu — a interface é que não declarava, e sem ela a
  // tela caía na moeda-base do WORKSPACE aberto. Um financiamento em USD
  // aparecia com saldo devedor e parcelas em R$ porque o último workspace
  // visitado era brasileiro.
  currency: string;
}

export interface Installment {
  id: number;
  installment_number: number;
  due_date: string;
  principal_amount: string;
  interest_amount: string;
  total_amount: string;
  remaining_balance: string;
  is_paid: boolean;
}

export function useFinancing() {
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ['financing'],
    queryFn: async (): Promise<Financing[]> => {
      const response = await apiClient.get(`/me/financing`);
      return response.data;
    },
  });

  // Pagar parcela muda o saldo devedor em Compromissos e o caixa do mês na Visão
  // global (ADR 0022). Pelo contrato único, para as três telas concordarem.
  const invalidate = () => {
    invalidateForEvent(queryClient, 'financing.updated', null);
  };

  const createMutation = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const response = await apiClient.post(`/me/financing`, data);
      return response.data as Financing;
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/me/financing/${id}`);
    },
    onSuccess: invalidate,
  });

  /**
   * Marca como pagas as parcelas que já venceram.
   *
   * Para quem cadastra um contrato que JÁ EXISTIA: o app gera o cronograma
   * inteiro e toda parcela nasce em aberto, então o financiamento entra no app
   * com meses de "atraso" que na vida real foram pagos. O backend é idempotente
   * (filtra por `is_paid=false`), então chamar duas vezes não faz mal.
   */
  const quitarAnteriores = useMutation({
    mutationFn: async (id: number) => {
      const response = await apiClient.post(
        `/me/financing/${id}/installments/settle-past`,
        {},
      );
      return response.data as { quitadas: number; em_aberto: number };
    },
    onSuccess: invalidate,
  });

  /**
   * Paga a parcela e, OPCIONALMENTE, lança a despesa num workspace.
   *
   * O backend aceita `workspace_id` desde sempre e o hook nunca o enviava: pela
   * interface, pagar uma parcela só reduzia Compromissos, e o gasto não aparecia
   * em lugar nenhum — a funcionalidade existia no servidor e não para o usuário.
   *
   * Sem workspace, o pagamento é puramente pessoal (o caso comum) e entra no
   * caixa pela própria parcela; com workspace, vira despesa e é ela que conta,
   * sem duplicar (ADR 0022).
   */
  const payInstallment = useMutation({
    mutationFn: async ({
      financingId,
      installmentNumber,
      workspaceId,
    }: {
      financingId: number;
      installmentNumber: number;
      workspaceId?: number | null;
    }) => {
      await apiClient.post(
        `/me/financing/${financingId}/installments/${installmentNumber}/pay`,
        workspaceId ? { workspace_id: workspaceId } : {},
      );
      return { workspaceId };
    },
    onSuccess: ({ workspaceId }) => {
      // Com workspace houve despesa nova: o extrato e os relatórios DELE também
      // mudaram, não só os Compromissos.
      invalidateForEvent(queryClient, 'financing.updated', null);
      if (workspaceId) {
        invalidateForEvent(queryClient, 'transaction.created', workspaceId);
      }
    },
  });

  return {
    financings: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    create: createMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    payInstallment: payInstallment.mutateAsync,
    quitarAnteriores: quitarAnteriores.mutateAsync,
  };
}

export function useFinancingSchedule(financingId: number | null) {

  const scheduleQuery = useQuery({
    queryKey: ['financing', financingId, 'schedule'],
    queryFn: async (): Promise<Installment[]> => {
      const response = await apiClient.get(
        `/me/financing/${financingId}/schedule`
      );
      return response.data;
    },
    enabled: !!financingId,
  });

  const settlementQuery = useQuery({
    queryKey: ['financing', financingId, 'settlement'],
    queryFn: async () => {
      const response = await apiClient.post(
        `/me/financing/${financingId}/early-settlement`,
        {}
      );
      return response.data as {
        total_to_pay: string;
        original_value: string;
        savings: string;
        installments_settled: number;
      };
    },
    enabled: !!financingId,
  });

  return {
    schedule: scheduleQuery.data ?? [],
    settlement: settlementQuery.data ?? null,
    isLoading: scheduleQuery.isLoading,
  };
}
