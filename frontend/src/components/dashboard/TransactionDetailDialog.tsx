import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Calendar, Pencil, Trash2 } from 'lucide-react';
import type { TransactionRead, TransactionStatus } from '@/types/transaction';
import { MoneyText } from '@/components/money/MoneyText';
import { TransactionSummary } from './TransactionSummary';
import { StatementMover } from './StatementMover';
import { useCategories } from '@/hooks/use-categories';
import { paymentMethodLabel } from '@/lib/payment-methods';
import { formatCurrency } from '@/lib/money';
import { parseApiDate } from '@/lib/date';

const STATUS_STYLES: Record<TransactionStatus, { label: string; className: string }> = {
  draft: { label: 'Rascunho', className: 'bg-muted text-muted-foreground border-border' },
  pending: { label: 'Pendente', className: 'bg-warning-subtle text-warning border-warning/20' },
  confirmed: { label: 'Confirmada', className: 'bg-primary/10 text-primary border-primary/20' },
  paid: { label: 'Paga', className: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' },
  cancelled: { label: 'Cancelada', className: 'bg-destructive/10 text-destructive border-destructive/20' },
};

interface TransactionDetailDialogProps {
  transaction: TransactionRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canWrite?: boolean;
  onEdit?: () => void;
  onDelete?: (id: number) => void;
  /** Move a compra de fatura (ADR 0032). Ausente = o seletor não aparece. */
  onMoveStatement?: (shift: number) => Promise<unknown>;
}

// Preview read-only do lançamento — abre rápido de qualquer lugar que o
// referencia. Mostra o resumo (quem pagou, divisão, ajustes, parcela) e um
// botão "Editar" que leva ao form completo. Detalhes de edição ficam no
// TransactionDialog; aqui é só leitura.
export function TransactionDetailDialog({
  transaction,
  open,
  onOpenChange,
  // Fail-closed, como em TransactionItem: sem a prop, sem escrita
  canWrite = false,
  onEdit,
  onDelete,
  onMoveStatement,
}: TransactionDetailDialogProps) {
  const { categories } = useCategories();
  if (!transaction) return null;

  const amount = parseFloat(transaction.total_amount);
  const kind = amount < 0 ? 'income' : 'expense';
  const categoryId = transaction.items?.[0]?.category_id;
  const categoryName = categoryId != null ? categories.find((c) => c.id === categoryId)?.name : undefined;
  const isPaid = transaction.status === 'paid';
  const status = STATUS_STYLES[transaction.status];
  const dateLabel = parseApiDate(transaction.transaction_date).toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] max-h-[90vh] overflow-y-auto bg-card border-border shadow-2xl">
        {/* `min-w-0` no CABEÇALHO, que é quem precisa dele: o `DialogContent` é
            um grid, e item de grid nasce com `min-width: auto` — recusa-se a
            encolher abaixo do conteúdo. O `truncate` do span não tinha efeito
            nenhum contra isso: medido, este header ficava com 592px dentro de um
            diálogo de 480 e ESTICAVA a coluna do grid, então o resumo, o bloco
            de fatura e os botões saíam todos cortados à direita, sem rolagem que
            os alcançasse.
            Defeito antigo — qualquer lançamento de título longo o reproduzia —,
            invisível até esta tela ganhar uma captura no catálogo. */}
        <DialogHeader className="min-w-0">
          <DialogTitle className="flex min-w-0 items-start justify-between gap-3">
            <span className="min-w-0 truncate">{transaction.title}</span>
            <MoneyText value={amount} kind={kind} currency={transaction.currency} className="shrink-0 text-lg font-bold" />
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-1">
            <span className="inline-flex items-center gap-1">
              <Calendar className="h-3.5 w-3.5" /> {dateLabel}
            </span>
            <span>· {paymentMethodLabel(transaction.payment_method, transaction.credit_card_id)}</span>
            {categoryName && <span>· {categoryName}</span>}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-tighter ${status.className}`}>
            {status.label}
          </span>
          {(transaction.tags ?? []).map((t) => (
            <span key={t.id} className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {t.name}
            </span>
          ))}
        </div>

        {transaction.original_currency && transaction.original_amount && (
          <div className="rounded-lg border border-border bg-accent/30 p-3 text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">
              {formatCurrency(parseFloat(transaction.original_amount), transaction.original_currency)}
            </span>{' '}
            convertido para <span className="font-semibold text-foreground">{formatCurrency(amount)}</span>
            {transaction.exchange_rate && ` · câmbio ${parseFloat(transaction.exchange_rate).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`}
            {transaction.iof_rate && parseFloat(transaction.iof_rate) > 0 &&
              ` + IOF ${(parseFloat(transaction.iof_rate) * 100).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`}
            {transaction.rate_source === 'ptax' && ' · PTAX oficial'}
            {transaction.rate_source === 'market' && ' · câmbio de mercado (referência)'}
          </div>
        )}

        {/* Antes do resumo da divisão: a pergunta "esta compra está na fatura
            certa?" é sobre o lançamento, e quem abre este preview vindo da tela
            da fatura está justamente conferindo isso. Uma despesa paga fica de
            fora — o `status = paid` congela o lançamento (ADR 0029), e mover
            aceitaria uma escrita que a rota recusaria. */}
        {onMoveStatement && !isPaid && (
          <StatementMover
            transaction={transaction}
            canWrite={canWrite}
            onMove={onMoveStatement}
          />
        )}

        <TransactionSummary transaction={transaction} />

        {(onEdit || onDelete) && (
          <DialogFooter className="gap-2 sm:justify-between">
            {onDelete && (
              <Button
                type="button"
                variant="ghost"
                className="gap-2 text-destructive hover:bg-destructive/10"
                disabled={!canWrite || isPaid}
                onClick={() => onDelete(transaction.id)}
              >
                <Trash2 className="h-4 w-4" /> Excluir
              </Button>
            )}
            {onEdit && (
              <Button type="button" className="gap-2 px-6 font-bold" disabled={!canWrite} onClick={onEdit}>
                <Pencil className="h-4 w-4" /> Editar
              </Button>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
