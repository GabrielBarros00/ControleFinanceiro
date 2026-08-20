import { useWorkspaces } from './use-workspaces';

/**
 * Este espaço controla o pagamento das contas? (ADR 0029)
 *
 * Quando ligado, o lançamento fora do cartão só vira saída de caixa depois de
 * marcado como pago, e até lá aparece em Contas a pagar. Desligado, o dinheiro
 * sai na data do lançamento — o comportamento anterior ao ADR, preservado para
 * quem lança tudo depois de pagar e não quer a etapa a mais.
 *
 * `true` como fallback (mesmo default do modelo) e não `false`: enquanto a lista
 * de espaços carrega, esconder a caixa "Já foi paga" faria o formulário salvar
 * sem ela — e o palpite pela data decidiria em silêncio o que a pessoa não teve
 * como dizer.
 */
export function useSettlementTracking(): boolean {
  const { currentWorkspace } = useWorkspaces();
  return currentWorkspace?.settlement_tracking ?? true;
}
