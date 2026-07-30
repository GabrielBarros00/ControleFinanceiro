import type { QueryClient } from '@tanstack/react-query';

/*
 * Contrato de tempo real — fonte ÚNICA de "o que uma mudança de tipo X afeta".
 *
 * Usado nos DOIS caminhos:
 *   1. evento WebSocket vindo de outro membro (use-workspace-events);
 *   2. invalidação local logo após a própria mutação (hooks).
 * Com a mesma tabela nos dois, quem faz a ação vê exatamente o que os outros
 * veem — antes cada hook invalidava um subconjunto diferente e algumas telas
 * (Endividamento, previsão) não atualizavam por nenhum dos caminhos.
 *
 * `WS_EVENT_TYPES` é o contrato com o backend: um teste do pytest garante que
 * todo tipo publicado por publish_event() está aqui, e um teste do vitest
 * garante que todo tipo daqui invalida pelo menos uma query.
 */

export const WS_EVENT_TYPES = [
  'attachment.created',
  'attachment.deleted',
  'category.created',
  'category.deleted',
  'category.updated',
  'estimate.created',
  'estimate.deleted',
  'estimate.updated',
  'invite.accepted',
  'invite.created',
  'invite.revoked',
  'member.added',
  'member.removed',
  'member.updated',
  'recurring.created',
  'recurring.deleted',
  'recurring.updated',
  'settlement.created',
  'settlement.deleted',
  'tag.created',
  'tag.deleted',
  'tag.updated',
  'transaction.bulk_created',
  'transaction.bulk_updated',
  'transaction.created',
  'transaction.deleted',
  'transaction.updated',
  'workspace.currency_changed',
  'workspace.deleted',
  'workspace.updated',
] as const;

export type WsEventType = (typeof WS_EVENT_TYPES)[number];

/** Marcador de "invalida tudo" (mudanças que afetam toda agregação). */
export const FULL_RESYNC = '*';

// Toda mutação gera trilha de auditoria — a tela do admin acompanha junto.
const AUDIT = ['audit'];

/**
 * Famílias de query afetadas por prefixo de evento. Os nomes são o PRIMEIRO
 * elemento da queryKey; o workspace entra depois (o TanStack casa por prefixo,
 * então ['reports', wsId] invalida ['reports', wsId, month]).
 */
const BY_PREFIX: Record<string, string[]> = {
  // Um lançamento mexe no extrato, no detalhe aberto, no grupo de parcelas, nos
  // relatórios, na previsão, nas dívidas (global e do mês), no endividamento e
  // na fatura/limite do cartão.
  transaction: [
    'transactions', 'transaction', 'installment-group', 'reports', 'analytics-forecast',
    'debts', 'debts-monthly', 'liabilities', 'statements', 'credit-cards', 'attachments',
    ...AUDIT,
  ],
  income: ['income', 'reports', 'analytics-forecast', ...AUDIT],
  // Recorrente materializa lançamentos (possivelmente numa fatura de cartão)
  recurring: [
    'recurring', 'transactions', 'reports', 'analytics-forecast', 'debts', 'debts-monthly',
    'liabilities', 'statements', 'credit-cards', ...AUDIT,
  ],
  recurring_income: ['recurring-income', 'income', 'reports', 'analytics-forecast', ...AUDIT],
  // Fechar/pagar/reabrir fatura muda limite comprometido e endividamento
  credit_card: ['credit-cards', 'statements', 'liabilities', 'transactions', ...AUDIT],
  category: ['categories', 'reports', 'transactions', ...AUDIT],
  tag: ['tags', 'transactions', ...AUDIT],
  estimate: ['estimates', 'analytics-forecast', 'reports', ...AUDIT],
  financing: ['financing', 'liabilities', ...AUDIT],
  payment_account: ['payment-accounts', 'transactions', 'credit-cards', ...AUDIT],
  attachment: ['attachments', 'transactions', ...AUDIT],
  settlement: ['settlements', 'debts', 'debts-monthly', ...AUDIT],
  // Entrar/sair muda o rateio; renomear muda o nome exibido no extrato e nas dívidas
  member: [
    'members', 'invites', 'debts', 'debts-monthly', 'transactions', 'liabilities',
    'workspaces', ...AUDIT,
  ],
  invite: ['invites', 'members', ...AUDIT],
  workspace: ['workspaces', ...AUDIT],
};

/** Eventos que exigem resync completo (o tipo inteiro, não só o prefixo). */
const FULL_RESYNC_TYPES = new Set<string>([
  // Trocar a moeda-base reescreve TODA agregação do workspace
  'workspace.currency_changed',
  // Mudar papel ou ACESSO FINANCEIRO muda o que o servidor devolve em toda
  // consulta (ADR 0018). Invalidar só ['members'] deixaria em cache o extrato, os
  // relatórios e as dívidas que a pessoa acabou de perder o direito de ver — e
  // ela seguiria vendo até um F5. Rebaixar acesso tem de esvaziar a tela na hora.
  'member.updated',
]);

/**
 * Query keys a invalidar para um tipo de evento. `FULL_RESYNC` significa
 * "invalide tudo". Tipo desconhecido devolve resync completo em vez de lista
 * vazia: perder atualização em silêncio é pior que um refetch a mais.
 */
export function keysForEvent(type: string, workspaceId: number): unknown[][] | typeof FULL_RESYNC {
  if (FULL_RESYNC_TYPES.has(type)) return FULL_RESYNC;

  const prefix = type.split('.')[0];
  const families = BY_PREFIX[prefix];
  if (!families) return FULL_RESYNC;

  return families.map((family) =>
    // 'workspaces' é global (lista do switcher), não tem escopo de workspace
    family === 'workspaces' ? [family] : [family, workspaceId],
  );
}

/**
 * Invalida localmente o que um evento afeta — o mesmo que o WebSocket faria.
 * Os hooks chamam isto no onSuccess da mutação para que a tela de quem AGIU
 * atualize na hora, sem depender da volta do evento pela rede.
 */
export function invalidateForEvent(
  queryClient: QueryClient,
  type: string,
  workspaceId?: number | null,
): void {
  if (!workspaceId) return;
  const keys = keysForEvent(type, workspaceId);
  if (keys === FULL_RESYNC) {
    queryClient.invalidateQueries();
    return;
  }
  for (const key of keys) {
    queryClient.invalidateQueries({ queryKey: key });
  }
}
