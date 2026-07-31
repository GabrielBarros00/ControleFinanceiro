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
  const daUrl = useWorkspaceIdFromUrl();
  const guardado = useUIStore((s) => s.currentWorkspaceId);
  const { workspaceId } = useParams<{ workspaceId?: string }>();

  // Dentro de `/w/:id` vale a URL — inclusive quando ela é inválida, caso em que
  // o resultado é `null` e não o guardado: mascarar um link quebrado carregando
  // dados de outro workspace é pior que uma tela vazia.
  if (workspaceId !== undefined) return daUrl;
  return guardado;
}

/**
 * Workspace da URL, **sem** o fallback para a store — `null` fora de `/w/:id`.
 *
 * Quem decide AGIR precisa deste, não do `useWorkspaceId`. O fallback existe para
 * telas que precisam de algum workspace para se orientar (o seletor da sidebar),
 * e é inofensivo aí; no botão "Nova despesa" ele é o contrário de inofensivo:
 * na Visão global o FAB abria o diálogo com o último workspace visitado, sem
 * dizer qual, e a despesa ia para a casa errada. O ADR 0020 define `/overview`
 * como somente leitura justamente por isso.
 */
export function useWorkspaceIdFromUrl(): number | null {
  const { workspaceId } = useParams<{ workspaceId?: string }>();
  if (workspaceId === undefined) return null;
  const id = Number(workspaceId);
  return Number.isInteger(id) && id > 0 ? id : null;
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
