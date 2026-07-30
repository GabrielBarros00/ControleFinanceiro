import { useParams } from 'react-router-dom';
import { useUIStore } from '@/stores';

/**
 * Workspace ATUAL — lido da URL (ADR 0020).
 *
 * Antes vinha só do `localStorage` (`useUIStore.currentWorkspaceId`), e o mesmo
 * caminho `/income` significava coisas diferentes conforme um estado invisível:
 *
 * - link compartilhado abria no workspace errado de quem clicou;
 * - duas abas disputavam a MESMA chave, então trocar de workspace numa mexia na
 *   outra — e a despesa ia parar na casa errada;
 * - o botão "voltar" não voltava para o workspace anterior, porque a troca nunca
 *   entrou no histórico.
 *
 * Este hook é o ÚNICO ponto de leitura: os ~25 hooks de dados trocaram
 * `useUIStore()` por ele numa linha cada, e as query keys, os guards `enabled` e
 * o contrato de `lib/ws-events.ts` continuaram idênticos.
 *
 * O fallback para a store existe para o que vive FORA de `/w/:workspaceId` e
 * ainda precisa de um workspace — o seletor da sidebar, o centro de notificações
 * — e para a transição das rotas antigas.
 */
export function useWorkspaceId(): number | null {
  const { workspaceId } = useParams<{ workspaceId?: string }>();
  const guardado = useUIStore((s) => s.currentWorkspaceId);

  if (workspaceId !== undefined) {
    const daUrl = Number(workspaceId);
    // Id inválido na URL não cai no guardado: isso mascararia um link quebrado
    // carregando dados de outro workspace, que é pior que uma tela vazia.
    return Number.isInteger(daUrl) && daUrl > 0 ? daUrl : null;
  }
  return guardado;
}

/**
 * Último workspace visitado — só para DECIDIR PARA ONDE IR (redirecionar `/` ou
 * uma rota antiga). Nunca para buscar dados: aí vale a URL.
 */
export function useLastWorkspaceId(): number | null {
  return useUIStore((s) => s.currentWorkspaceId);
}

/**
 * Caminho do workspace preservando a subrota atual: quem está em Lançamentos
 * continua em Lançamentos ao trocar de casa, em vez de cair no painel.
 */
export function workspacePath(id: number, pathnameAtual: string): string {
  const sub = pathnameAtual.match(/^\/w\/\d+(\/.*)?$/)?.[1] ?? '';
  return `/w/${id}${sub}`;
}
