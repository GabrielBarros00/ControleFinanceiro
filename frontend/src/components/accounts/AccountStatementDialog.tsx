import { MoneyText } from '@/components/money/MoneyText';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { parseApiDay } from '@/lib/date';
import { formatMoney } from '@/lib/money';
import { sourceLabel, useAccountStatement } from '@/hooks/use-balance';
import { Receipt } from 'lucide-react';

/*
 * Extrato da conta — a resposta de "por que o saldo é exatamente esse valor?"
 * (última pergunta do §43 do pedido).
 *
 * Cada linha traz o quanto somou E quanto o saldo passou a ser depois dela, então
 * o número do topo é rastreável até o saldo inicial sem ninguém refazer conta. A
 * resposta nunca é "porque alguém digitou": a origem de cada linha está nomeada.
 */
export function AccountStatementDialog({
  accountId,
  accountName,
  onClose,
}: {
  accountId: number;
  accountName: string;
  onClose: () => void;
}) {
  const { statement, isLoading } = useAccountStatement(accountId);

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Extrato — {accountName}</DialogTitle>
          <DialogDescription>
            De onde vem cada centavo do saldo, do início até hoje.
          </DialogDescription>
        </DialogHeader>

        {isLoading && <Skeleton className="h-40 w-full" />}

        {!isLoading && statement && statement.entries.length === 0 && (
          <EmptyState
            icon={Receipt}
            title="Nenhum movimento"
            description="Assim que houver um pagamento, recebimento ou ajuste nesta conta, ele aparece aqui."
          />
        )}

        {!isLoading && statement && statement.entries.length > 0 && (
          <div className="max-h-[60vh] overflow-y-auto">
            {/* Rolagem própria: um extrato longo não pode empurrar o rodapé do
                diálogo para fora da tela. */}
            <ul className="divide-y divide-border">
              {statement.entries.map((linha, i) => (
                <li
                  key={`${linha.source}-${linha.reference_id ?? i}`}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {linha.title || sourceLabel(linha.source)}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      {parseApiDay(linha.occurred_on).toLocaleDateString('pt-BR')} ·{' '}
                      {sourceLabel(linha.source)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <MoneyText
                      value={linha.amount}
                      kind={Number(linha.amount) < 0 ? 'expense' : 'income'}
                      currency={statement.currency}
                      className="block text-sm"
                    />
                    {/* Sem saldo inicial não há coluna de saldo: um "R$ 0,00"
                        aqui afirmaria que a conta estava zerada. Os movimentos
                        continuam listados — eles aconteceram; o que não se sabe é
                        o saldo. */}
                    {linha.running_balance !== null &&
                      linha.running_balance !== undefined && (
                        <p className="tabular text-[11px] text-muted-foreground">
                          saldo:{' '}
                          {formatMoney(Number(linha.running_balance), {
                            currency: statement.currency,
                          })}
                        </p>
                      )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
