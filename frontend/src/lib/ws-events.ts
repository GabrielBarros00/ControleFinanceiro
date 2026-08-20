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
 * Famílias GLOBAIS — a queryKey delas NÃO leva workspace.
 *
 * Depois do ADR 0021 cartão, conta, financiamento e renda são da pessoa e a
 * acompanham em todo workspace; as chaves passaram a ser `['credit-cards']`,
 * `['payment-accounts']`, `['financing']`, `['income', mês]`, `['statements',
 * cardId]` e as `['me-*']`. Este mapa continuava anexando `workspaceId` a TUDO, e
 * o resultado é que nenhuma delas era invalidada: o TanStack casa por PREFIXO, e
 * `['credit-cards', 7]` não é prefixo de `['credit-cards']` — é o contrário.
 * `['statements', 7]` era pior que inócuo: acertava por acaso o cartão de id 7.
 *
 * Consequência prática, antes desta correção: criar um lançamento não atualizava
 * a Visão global, a atividade recente, o limite do cartão nem os compromissos.
 */
export const GLOBAIS = new Set([
  'credit-cards', 'statements', 'payment-accounts', 'financing', 'income',
  'recurring-income', 'me-overview', 'me-commitments', 'me-activity', 'me-reports',
  'me-ledger', 'statement-target', 'workspaces',
  // Contas a pagar (ADR 0029). A da PESSOA soma todos os espaços dela e por isso
  // não leva workspace na chave; a do espaço (`payables`) leva e fica de fora
  // deste conjunto — mesmo par de `me-debts`/`debts`.
  'me-payables',
  // Acertos na camada global (ADR 0027). Vêm de `/me/*` e por isso NÃO levam
  // workspace na chave — ao contrário de `debts`/`debts-monthly`/`settlements`,
  // que são as famílias equivalentes do workspace e ficam de fora deste conjunto.
  'me-debts', 'me-debts-monthly', 'me-debts-by-month', 'me-settlements',
]);

/**
 * Famílias de query afetadas por prefixo de evento. Os nomes são o PRIMEIRO
 * elemento da queryKey; o workspace entra depois SE a família for do workspace
 * (o TanStack casa por prefixo, então ['reports', wsId] invalida
 * ['reports', wsId, month]). Ver `GLOBAIS` acima.
 */
const BY_PREFIX: Record<string, string[]> = {
  // Um lançamento mexe no extrato, no detalhe aberto, no grupo de parcelas, nos
  // relatórios, na previsão, nas dívidas (global e do mês), na fatura/limite do
  // cartão — e na visão pessoal, que soma todos os workspaces.
  transaction: [
    'transactions', 'transaction', 'installment-group', 'reports', 'analytics-forecast',
    'debts', 'debts-monthly', 'debts-by-month', 'statements', 'credit-cards', 'attachments',
    'me-overview', 'me-ledger', 'me-reports', 'me-activity', 'me-commitments',
    'me-debts', 'me-debts-monthly', 'me-debts-by-month',
    // Criar, editar, excluir ou LIQUIDAR um lançamento muda a fila do que falta
    // pagar (ADR 0029) — nas duas camadas.
    'payables', 'me-payables',
    ...AUDIT,
  ],
  income: ['income', 'reports', 'analytics-forecast', 'me-overview', 'me-ledger', 'me-reports', ...AUDIT],
  // Recorrente materializa lançamentos (possivelmente numa fatura de cartão)
  recurring: [
    'recurring', 'transactions', 'reports', 'analytics-forecast', 'debts', 'debts-monthly', 'debts-by-month',
    'statements', 'credit-cards', 'me-overview', 'me-ledger', 'me-reports', 'me-activity', 'me-commitments',
    'me-debts', 'me-debts-monthly', 'me-debts-by-month',
    // A recorrência materializa lançamentos, e eles nascem A PAGAR quando o
    // template não tem débito automático — é a origem que mais alimenta a fila.
    'payables', 'me-payables',
    ...AUDIT,
  ],
  recurring_income: [
    'recurring-income', 'income', 'reports', 'analytics-forecast', 'me-overview', 'me-ledger', 'me-reports', ...AUDIT,
  ],
  // Fechar/pagar/reabrir fatura muda limite comprometido, compromissos e — desde
  // o ADR 0022 — o caixa efetivo do mês em que a fatura foi paga.
  credit_card: [
    'credit-cards', 'statements', 'transactions', 'me-commitments', 'me-overview', 'me-ledger',
    // Mudar dia de fechamento/vencimento — ou fechar a fatura do ciclo — muda
    // a resposta de "vai para a fatura de Agosto/2026" no formulário. Sem
    // isto o aviso ficava com a regra ANTIGA em cache, e ele existe
    // justamente porque ninguém adivinha a regra olhando a tela.
    'statement-target',
    'me-reports', ...AUDIT,
  ],
  category: ['categories', 'reports', 'transactions', ...AUDIT],
  tag: ['tags', 'transactions', ...AUDIT],
  estimate: ['estimates', 'analytics-forecast', 'reports', ...AUDIT],
  financing: ['financing', 'me-commitments', 'me-overview', 'me-ledger', 'me-reports', ...AUDIT],
  payment_account: ['payment-accounts', 'transactions', 'credit-cards', ...AUDIT],
  attachment: ['attachments', 'transactions', ...AUDIT],
  // O acerto mexe no saldo a pagar/receber E no caixa (é dinheiro que muda de mão)
  settlement: [
    'settlements', 'debts', 'debts-monthly', 'debts-by-month', 'me-overview', 'me-ledger', 'me-reports', 'reports',
    // A tela global mostra o MESMO acerto, agrupado por casa: quem registra por
    // lá precisa ver o saldo cair na hora, sem depender do evento voltar pela
    // rede (o WebSocket é por sala de workspace).
    'me-debts', 'me-debts-monthly', 'me-debts-by-month', 'me-settlements',
    ...AUDIT,
  ],
  // Entrar/sair muda o RATEIO — e o rateio é a base dos relatórios (totais por
  // categoria), da participação por workspace em `me-reports`, do `my_share` de
  // cada linha em `me-activity` e da previsão. A lista parava em `me-overview`,
  // então outra aba seguia exibindo consolidações calculadas com o quadro de
  // membros antigo.
  member: [
    'members', 'invites', 'debts', 'debts-monthly', 'debts-by-month', 'settlements', 'transactions',
    'reports', 'analytics-forecast', 'workspaces',
    'me-overview', 'me-ledger', 'me-reports', 'me-activity',
    // Entrar/sair muda o rateio, e o rateio é a base do pareamento de dívidas —
    // inclusive na tela global, onde a casa vira um grupo.
    'me-debts', 'me-debts-monthly', 'me-debts-by-month', 'me-settlements',
    // O acesso financeiro decide QUAIS contas em aberto o membro enxerga
    // (ADR 0018): rebaixar alguém tem de esvaziar a lista dele na hora.
    'payables', 'me-payables', ...AUDIT,
  ],
  invite: ['invites', 'members', ...AUDIT],
  // Renomear/excluir workspace: o NOME é renderizado em `me-reports`
  // (`by_workspace`) e em `me-activity` (`workspace_name`), e excluir deixa as
  // duas listas com linhas de um workspace que não existe mais.
  workspace: [
    'workspaces', 'transactions', 'reports',
    'me-overview', 'me-ledger', 'me-reports', 'me-activity', 'me-commitments',
    // O NOME da casa titula cada grupo da tela global de acertos, e excluir uma
    // deixaria um grupo de workspace que não existe mais.
    'me-debts', 'me-debts-monthly', 'me-debts-by-month', 'me-settlements',
    // Ligar/desligar o controle de pagamento (ADR 0029) muda o formulário e a
    // navegação — e o nome da casa é a coluna que distingue as contas na lista
    // pessoal.
    'payables', 'me-payables', ...AUDIT,
  ],
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
    // Família global (recurso pessoal, ADR 0021) não leva workspace na chave —
    // anexá-lo produzia uma chave que não casa com query nenhuma.
    GLOBAIS.has(family) ? [family] : [family, workspaceId],
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
  const keys = keysForEvent(type, workspaceId ?? -1);
  if (keys === FULL_RESYNC) {
    queryClient.invalidateQueries();
    return;
  }
  for (const key of keys) {
    // Sem workspace conhecido, a camada PESSOAL ainda precisa atualizar: pagar
    // uma fatura em `/me/cards` não acontece dentro de `/w/:id`, e o `return`
    // que existia aqui descartava a invalidação inteira. O que é do workspace
    // fica de fora, porque não há workspace a que se referir.
    if (!workspaceId && key.length > 1) continue;
    queryClient.invalidateQueries({ queryKey: key });
  }
}
