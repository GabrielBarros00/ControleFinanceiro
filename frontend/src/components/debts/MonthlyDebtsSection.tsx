import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, CalendarDays } from 'lucide-react';
import { useMonthlyDebts } from '@/hooks/use-monthly-debts';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import type { SettlementDraft } from '@/components/debts/SettlementDialog';
import {
  MonthlyLedgerBody,
  MonthlyLedgerTotals,
  type MemberLike,
} from '@/components/debts/MonthlyLedgerBody';
import { currentMonthLocal, monthLabel, shiftMonth } from '@/lib/date';
import { useMonthParam } from '@/hooks/use-month-param';

interface MonthlyDebtsSectionProps {
  members: MemberLike[];
  currentUserId?: number;
  canWrite: boolean;
  onSettle: (draft: SettlementDraft) => void;
}

/**
 * O retrato mensal DESTA casa. A casca (título, navegador de mês, busca) mora
 * aqui; a tabela em si é `MonthlyLedgerBody`, compartilhada com a tela global de
 * acertos (ADR 0027), onde ela aparece uma vez por casa.
 */
export function MonthlyDebtsSection({ members, currentUserId, canWrite, onSettle }: MonthlyDebtsSectionProps) {
  // Moeda-base do workspace: o backend soma nela e devolve `base_currency` em
  // todo endpoint agregado — a tela formatava com "R$" fixo no código.
  const baseCurrency = useBaseCurrency();
  const [month, setMonth] = useMonthParam();
  const { ledger, isLoading } = useMonthlyDebts(month);

  const isCurrentMonth = month === currentMonthLocal();

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader className="space-y-4">
        <div className="flex flex-col gap-1">
          <CardTitle className="text-lg flex items-center gap-2">
            <CalendarDays className="h-5 w-5 text-primary" />
            Acertos do mês
          </CardTitle>
          <CardDescription>
            Só deste espaço. Cada parcela aparece no mês dela — veja o que cada um deve e se já foi pago.
          </CardDescription>
        </div>

        {/* Navegador de mês */}
        <div className="flex items-center justify-between rounded-xl bg-accent/30 border border-border p-2">
          <Button variant="ghost" size="icon" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="flex flex-col items-center">
            {/* Sem `capitalize`: a classe do CSS capitaliza cada palavra e
                produzia "Agosto De 2026". Quem capitaliza é o `monthLabel`. */}
            <span className="text-sm font-semibold text-foreground">{monthLabel(month)}</span>
            {!isCurrentMonth && (
              <button
                type="button"
                onClick={() => setMonth(currentMonthLocal())}
                className="text-[10px] font-bold text-primary hover:underline"
              >
                voltar para o mês atual
              </button>
            )}
          </div>
          <Button variant="ghost" size="icon" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        <MonthlyLedgerTotals ledger={ledger} currency={baseCurrency} />
      </CardHeader>

      <CardContent className="space-y-6">
        <MonthlyLedgerBody
          ledger={ledger}
          members={members}
          currentUserId={currentUserId}
          canWrite={canWrite}
          currency={baseCurrency}
          month={month}
          isLoading={isLoading}
          onSettle={onSettle}
        />
      </CardContent>
    </Card>
  );
}
