import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';

/**
 * Visão GLOBAL e pessoal (ADR 0020).
 *
 * Note o que NÃO existe aqui: `workspaceId` na chave nem na URL. É o único grupo
 * de hooks do app assim, e de propósito — a pergunta é "como está o MEU mês",
 * somando todos os workspaces. Um recorte por workspace seria a dashboard da casa,
 * que é outra tela.
 */
export interface OverviewWorkspace {
  workspace_id: number;
  workspace_name: string;
  base_currency: string;
  consumption: string | number;
  cash_out: string | number;
  to_pay: string | number;
  to_receive: string | number;
}

export interface Overview {
  month: string;
  currency: string;
  income: string | number;
  consumption: string | number;
  cash_out: string | number;
  result: string | number;
  to_pay: string | number;
  to_receive: string | number;
  by_workspace: OverviewWorkspace[];
  excluded_foreign_count: number;
}

export function useOverview(month?: string) {
  const query = useQuery({
    queryKey: ['me-overview', month],
    queryFn: async (): Promise<Overview> => {
      const res = await apiClient.get('/me/overview', {
        params: month ? { month } : undefined,
      });
      return res.data;
    },
  });
  return { overview: query.data, isLoading: query.isLoading };
}

/**
 * Compromissos separados por PRAZO (ADR 0021).
 *
 * O `total` único que existia aqui somava a próxima fatura do cartão com o
 * principal inteiro de cada financiamento — juntava o que vence em cinco dias
 * com o que vence em quinze anos e não respondia nem "quanto preciso ter em
 * caixa este mês" nem "quanto devo ao todo". São cinco números agora.
 */
export interface Commitments {
  currency: string;
  /** Já venceu e não foi pago */
  overdue: string | number;
  /** Ainda vence dentro deste mês */
  due_this_month: string | number;
  /** Tamanho da dívida: principal em aberto + faturas não pagas */
  outstanding_total: string | number;
  /** Quanto do mês já está comprometido (uma parcela por financiamento ativo) */
  monthly_commitment: string | number;
  next_installments: {
    financing_id: number;
    title: string;
    installment_number: number;
    due_date: string;
    amount: string | number;
  }[];
  cards: {
    card_id: number;
    card_name: string;
    statement_id: number;
    month: string;
    due_date: string;
    amount: string | number;
    is_overdue: boolean;
  }[];
  financings: {
    financing_id: number;
    title: string;
    outstanding: string | number;
    next_due_date: string;
    remaining_installments: number;
  }[];
  excluded_foreign_count: number;
}

export function useCommitments() {
  const query = useQuery({
    queryKey: ['me-commitments'],
    queryFn: async (): Promise<Commitments> => {
      const res = await apiClient.get('/me/commitments');
      return res.data;
    },
  });
  return { commitments: query.data, isLoading: query.isLoading };
}

export interface ActivityItem {
  id: number;
  workspace_id: number;
  workspace_name: string;
  title: string;
  total_amount: string | number;
  currency: string;
  transaction_date: string;
  status: string;
}

export function useMyActivity(limit = 8) {
  const query = useQuery({
    queryKey: ['me-activity', limit],
    queryFn: async (): Promise<ActivityItem[]> => {
      const res = await apiClient.get('/me/activity', { params: { limit } });
      return res.data;
    },
  });
  return { activity: query.data ?? [], isLoading: query.isLoading };
}
