import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AlertCircle, CreditCard, Loader2, LockOpen } from 'lucide-react';
import type { TransactionRead } from '@/types/transaction';
import { getApiErrorMessage } from '@/lib/api-error';
import { TransactionForm, type TransactionApiPayload } from './transaction-form/TransactionForm';
import { fromApiTransaction } from './transaction-form/schema';
import { AttachmentsSection } from './AttachmentsSection';
import { TransactionSummary } from './TransactionSummary';

interface TransactionDialogProps {
  transaction: TransactionRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Duas formas, e a diferença é o que o host usa para decidir o caminho: o
   * formulário manda a definição COMPLETA (com `payers`), e a reabertura manda
   * só `{status: 'confirmed'}`. Era `Record<string, unknown>`, que apagava as
   * duas.
   */
  onSave: (data: TransactionApiPayload | { status: 'confirmed' }) => Promise<void> | void;
  onDelete: (id: number) => void;
  // Compra parcelada: definição INTEIRA (agregada) para editar o grupo todo, e
  // quantas parcelas já estão pagas (mostrado no aviso).
  installmentWhole?: TransactionRead | null;
  paidCount?: number;
}

// Edição COMPLETA da despesa (campos, pagamento, divisão/itens) — o mesmo form
// da criação, pré-preenchido. Também serve de tela de detalhe da divisão.
export function TransactionDialog({
  transaction,
  open,
  onOpenChange,
  onSave,
  onDelete,
  installmentWhole = null,
  paidCount = 0,
}: TransactionDialogProps) {
  const [reopenError, setReopenError] = React.useState<string | null>(null);

  if (!transaction) return null;

  const isPaid = transaction.status === 'paid';
  // Compra parcelada: o form edita a COMPRA INTEIRA (total cheio + nº de parcelas)
  const isGroup = (transaction.installments_of ?? 0) > 1;

  const handleSubmit = async (payload: TransactionApiPayload) => {
    // PUT full: payers + splits/items completos — o backend recria tudo
    // atomicamente e mantém as somas consistentes
    await onSave(payload);
  };

  const handleReopen = async () => {
    setReopenError(null);
    try {
      await onSave({ status: 'confirmed' });
    } catch (err) {
      setReopenError(getApiErrorMessage(err, 'Erro ao reabrir a despesa.'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[640px] max-h-[90vh] overflow-y-auto bg-card border-border shadow-2xl">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold flex items-center gap-2">
            <span className="w-1.5 h-6 bg-primary rounded-full" />
            Editar Transação
          </DialogTitle>
          <DialogDescription className="text-muted-foreground">
            Altere os detalhes, a forma de pagamento e a divisão da despesa.
          </DialogDescription>
        </DialogHeader>

        {isPaid ? (
          <div className="space-y-4 py-4">
            <TransactionSummary transaction={transaction} />
            <div className="p-4 rounded-lg bg-warning-subtle border border-warning/20 flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-warning mt-0.5" />
              <div className="space-y-1">
                <p className="text-sm font-bold text-warning">Despesa paga</p>
                <p className="text-xs text-muted-foreground">
                  Despesas pagas ficam travadas para proteger o histórico de acertos.
                  Reabra para poder editar ou excluir.
                </p>
              </div>
            </div>
            <Button
              type="button"
              onClick={handleReopen}
              className="w-full gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-bold"
            >
              <LockOpen className="h-4 w-4" /> Reabrir despesa
            </Button>
            {reopenError && (
              <p role="alert" className="text-sm text-destructive font-medium">{reopenError}</p>
            )}
          </div>
        ) : isGroup && !installmentWhole ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : (
          <div className="py-2">
            {isGroup ? (
              <div className="mb-4 flex items-start gap-3 rounded-lg border border-primary/20 bg-primary/10 p-3">
                <CreditCard className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                <div className="space-y-0.5">
                  <p className="text-sm font-bold text-primary">
                    Compra parcelada em {installmentWhole!.installments_of}×
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Alterar o valor, o número de parcelas ou a divisão vale para todas as parcelas.
                    {paidCount > 0 && ` ${paidCount} parcela(s) já paga(s) serão mantidas e as em aberto recalculadas.`}
                  </p>
                </div>
              </div>
            ) : (
              <TransactionSummary transaction={transaction} />
            )}
            <TransactionForm
              // updated_at na key: quando o refetch chega com dados novos, o
              // form REMONTA com defaultValues frescos (o backend garante
              // updated_at a cada edição) — sem isso a reabertura mostrava
              // a divisão antiga. No grupo, a chave segue a definição inteira.
              key={
                isGroup
                  ? `group-${installmentWhole!.id}-${installmentWhole!.updated_at}`
                  : `${transaction.id}-${transaction.updated_at}`
              }
              initialValues={
                isGroup
                  ? { ...fromApiTransaction(installmentWhole!), installments: installmentWhole!.installments_of ?? 1 }
                  : fromApiTransaction(transaction)
              }
              onSubmit={handleSubmit}
              submitLabel="Salvar Alterações"
              allowInstallments={isGroup}
            />

            {/* Compra parcelada: os recibos ficam na 1ª parcela viva (a âncora
                do grupo), então abrir qualquer parcela mostra os mesmos anexos. */}
            <AttachmentsSection transactionId={isGroup ? installmentWhole!.id : transaction.id} />

            <div className="mt-6 p-4 rounded-lg bg-destructive/10 border border-destructive/20 flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
              <div className="space-y-1">
                <p className="text-sm font-bold text-destructive">Zona de Perigo</p>
                <p className="text-xs text-destructive/80">Esta ação não pode ser desfeita. A transação será marcada como removida.</p>
                <Button
                  type="button"
                  variant="link"
                  className="p-0 h-auto text-xs text-destructive font-bold hover:underline"
                  onClick={() => onDelete(transaction.id)}
                >
                  Remover transação permanentemente
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
