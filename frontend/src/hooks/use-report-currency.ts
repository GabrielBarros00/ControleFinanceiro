import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useAuthStore, type AuthUser } from '@/stores';

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
  // Da SESSÃO, que o bootstrap já buscou (`/auth/me`). Antes era uma consulta
  // própria ao `/me/overview` inteiro — 64 consultas no servidor, ~95 ms — em
  // toda tela pessoal, só para ler um campo (auditoria 2026-09-26, P6).
  return useAuthStore((estado) => estado.user?.report_currency) ?? 'BRL';
}

export function useSetReportCurrency() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (report_currency: string) => {
      const res = await apiClient.patch('/me/report-currency', { report_currency });
      return res.data as { report_currency: string };
    },
    onSuccess: ({ report_currency }) => {
      // A sessão passa a dizer a moeda nova — na store (que o `useReportCurrency`
      // lê) e no cache da `auth-me`, para um refetch da sessão não voltar atrás.
      const { user, setUser } = useAuthStore.getState();
      if (user) setUser({ ...user, report_currency });
      queryClient.setQueryData<AuthUser | null>(['auth-me'], (atual) =>
        atual ? { ...atual, report_currency } : atual);
      // Tudo que é pessoal é expresso nesta moeda: a troca refaz o conjunto.
      queryClient.invalidateQueries({ queryKey: ['me-overview'] });
      queryClient.invalidateQueries({ queryKey: ['me-commitments'] });
      queryClient.invalidateQueries({ queryKey: ['income'] });
    },
  });
}
