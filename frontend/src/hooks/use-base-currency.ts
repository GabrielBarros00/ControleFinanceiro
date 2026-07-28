import { useWorkspaces } from './use-workspaces';

/**
 * Moeda-base do workspace atual — a moeda em que TODOS os totais são somados
 * (ADR 0006).
 *
 * Existe porque a moeda-base era configurável no backend e invisível na UI:
 * `/debts/monthly`, `/liabilities/overview` e `/analytics/*` devolvem
 * `base_currency`, os hooks até o tipavam, e nenhuma tela o usava — três
 * componentes formatavam com `R$` fixo no código. Num workspace em USD, os
 * números vinham certos e o símbolo mentia.
 */
export function useBaseCurrency(): string {
  const { currentWorkspace } = useWorkspaces();
  return currentWorkspace?.base_currency || 'BRL';
}
