import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import type { components } from '@/types/api.gen';

/**
 * Visão GLOBAL e pessoal (ADR 0020 + 0022).
 *
 * Note o que NÃO existe aqui: `workspaceId` na chave nem na URL. É o único grupo
 * de hooks do app assim, e de propósito — a pergunta é "como está o MEU mês",
 * somando todos os workspaces. Um recorte por workspace seria a dashboard da casa,
 * que é outra tela.
 *
 * Os tipos vêm do OpenAPI, não escritos à mão. As rotas `/me/*` devolviam
 * `Dict[str, Any]` e estas interfaces eram cópias mantidas por disciplina — o
 * mesmo arranjo que, em Configurações, fez a confirmação de uma operação
 * destrutiva imprimir `undefined` três vezes com o TypeScript verde. Agora
 * divergir é erro de compilação.
 */
export type Overview = components['schemas']['OverviewRead'];
export type OverviewWorkspace = components['schemas']['WorkspaceSlice'];

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
 * Extrato global: as LINHAS que compõem o caixa do mês (ADR 0022).
 *
 * A Visão global tinha bons totais e nenhuma forma de explicar cada número. Este
 * hook lê o mesmo `CashFlowService` que produz os totais — por isso o extrato
 * sempre fecha com eles, em vez de ser uma segunda consulta parecida que
 * diverge com o tempo.
 */
export type Ledger = components['schemas']['LedgerRead'];
export type LedgerEntry = components['schemas']['LedgerEntry'];

export interface LedgerFilters {
  month?: string;
  source?: string[];
  workspace_id?: number;
  card_id?: number;
  counterparty_id?: number;
  limit?: number;
  offset?: number;
}

export function useLedger(filters: LedgerFilters = {}, enabled = true) {
  const query = useQuery({
    // A chave carrega os filtros: cada recorte é uma resposta diferente, e o
    // drill-down troca de recorte sem sair da tela.
    queryKey: ['me-ledger', filters],
    queryFn: async (): Promise<Ledger> => {
      const res = await apiClient.get('/me/ledger', { params: filters });
      return res.data;
    },
    enabled,
  });
  return { ledger: query.data, isLoading: query.isLoading };
}

/**
 * Compromissos separados por PRAZO (ADR 0021).
 *
 * O `total` único que existia aqui somava a próxima fatura do cartão com o
 * principal inteiro de cada financiamento — juntava o que vence em cinco dias
 * com o que vence em quinze anos e não respondia nem "quanto preciso ter em
 * caixa este mês" nem "quanto devo ao todo". São cinco números agora.
 */
export type Commitments = components['schemas']['CommitmentsRead'];

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

export type ActivityItem = components['schemas']['ActivityRead'];

/**
 * Relatórios GLOBAIS: vários meses somando todos os workspaces.
 *
 * Par de `useReports` (que é do workspace) e não substituto dele: um responde
 * "quanto esta casa gastou", este responde "como está o meu período". Depois do
 * ADR 0021 o primeiro nem pode mais falar de renda.
 */
export type MyReports = components['schemas']['SeriesRead'];

export function useMyReports(months = 6) {
  const query = useQuery({
    queryKey: ['me-reports', months],
    queryFn: async (): Promise<MyReports> => {
      const res = await apiClient.get('/me/reports', { params: { months } });
      return res.data;
    },
  });
  return { reports: query.data, isLoading: query.isLoading };
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
