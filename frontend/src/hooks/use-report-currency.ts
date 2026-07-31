import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';

/**
 * Moeda em que os números PESSOAIS são expressos (ADR 0020 + 0021).
 *
 * Par de `useBaseCurrency`, e a distinção importa: a moeda-base é do WORKSPACE e
 * vale para o que a casa mede (lançamentos, orçamento, acertos); esta é da
 * PESSOA e vale para o que a acompanha (renda, cartão, conta, financiamento) e
 * para a Visão global, que soma workspaces de bases diferentes.
 *
 * Antes esses cadastros herdavam a moeda-base do workspace ABERTO no navegador,
 * então a mesma renda nascia em USD ou em BRL conforme a tela por onde foi
 * criada — e depois entrava ou saía dos totais conforme a moeda de quem olhasse.
 */
export function useReportCurrency(): string {
  const { data } = useQuery({
    queryKey: ['me-report-currency'],
    queryFn: async (): Promise<{ report_currency: string }> => {
      const res = await apiClient.get('/me/overview');
      return { report_currency: res.data.currency };
    },
    // A moeda de relatório muda por ação explícita do usuário; refazer a
    // consulta a cada montagem só custaria rede.
    staleTime: 5 * 60_000,
  });
  return data?.report_currency ?? 'BRL';
}

export function useSetReportCurrency() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (report_currency: string) => {
      const res = await apiClient.patch('/me/report-currency', { report_currency });
      return res.data as { report_currency: string };
    },
    onSuccess: () => {
      // Tudo que é pessoal é expresso nesta moeda: a troca refaz o conjunto.
      queryClient.invalidateQueries({ queryKey: ['me-report-currency'] });
      queryClient.invalidateQueries({ queryKey: ['me-overview'] });
      queryClient.invalidateQueries({ queryKey: ['me-commitments'] });
      queryClient.invalidateQueries({ queryKey: ['income'] });
    },
  });
}
