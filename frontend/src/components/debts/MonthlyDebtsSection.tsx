import { useMonthlyDebts } from '@/hooks/use-monthly-debts';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import type { SettlementDraft } from '@/components/debts/SettlementDialog';
import {
  MonthlyLedgerBody,
  MonthlyLedgerTotals,
  type MemberLike,
} from '@/components/debts/MonthlyLedgerBody';

/**
 * O retrato mensal DESTA casa: busca o ledger e o desenha.
 *
 * A casca encolheu no redesenho por abas. O `Card`, o título e o navegador de
 * mês saíram daqui: a aba "Por mês" já É o título, e o mês agora é da PÁGINA —
 * o bloco "de onde vem esse saldo" precisa poder abrir um mês específico, e um
 * navegador escondido dentro deste componente não teria como ser comandado de
 * fora sem virar estado duplicado.
 *
 * A tabela em si continua sendo `MonthlyLedgerBody`, compartilhada com a tela
 * global de acertos (ADR 0027), onde ela aparece uma vez por casa.
 */
interface MonthlyDebtsSectionProps {
  month: string;
  members: MemberLike[];
  currentUserId?: number;
  canWrite: boolean;
  onSettle: (draft: SettlementDraft) => void;
  onOpenHistory?: () => void;
}

export function MonthlyDebtsSection({
  month,
  members,
  currentUserId,
  canWrite,
  onSettle,
  onOpenHistory,
}: MonthlyDebtsSectionProps) {
  // Moeda-base do workspace: o backend soma nela e devolve `base_currency` em
  // todo endpoint agregado — a tela formatava com "R$" fixo no código.
  const baseCurrency = useBaseCurrency();
  const { ledger, isLoading } = useMonthlyDebts(month);

  return (
    <div className="space-y-4">
      <MonthlyLedgerTotals ledger={ledger} currency={baseCurrency} currentUserId={currentUserId} />
      <MonthlyLedgerBody
        ledger={ledger}
        members={members}
        currentUserId={currentUserId}
        canWrite={canWrite}
        currency={baseCurrency}
        month={month}
        isLoading={isLoading}
        onSettle={onSettle}
        onOpenHistory={onOpenHistory}
      />
    </div>
  );
}
