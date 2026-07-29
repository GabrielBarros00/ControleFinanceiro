import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useTransactions } from '@/hooks/use-transactions';
import { useAttachmentUploader } from '@/hooks/use-attachments';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { useAuthStore } from '@/stores';
import { toast } from '@/stores/toast';
import { TransactionForm, type TransactionApiPayload } from './transaction-form/TransactionForm';
import { todayLocalISO, type TransactionFormValues } from './transaction-form/schema';
import { AttachmentsSection } from './AttachmentsSection';

interface NewTransactionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Criação de despesa em modal (padrão do app, ver IncomePage). O form slim é o
// mesmo da edição — aqui pré-preenchido com os defaults de uma nova despesa.
export function NewTransactionDialog({ open, onOpenChange }: NewTransactionDialogProps) {
  const { user } = useAuthStore();
  const { create } = useTransactions();
  const baseCurrency = useBaseCurrency();
  // Anexos escolhidos antes de existir id: esperam aqui e sobem no submit
  const [pendingFiles, setPendingFiles] = React.useState<File[]>([]);
  const uploadAttachments = useAttachmentUploader();

  const initialValues: TransactionFormValues = {
    title: '',
    total_amount: 0,
    // Moeda-base do workspace, não 'BRL' fixo: num workspace em USD o default
    // fazia o backend tratar toda despesa comum como ESTRANGEIRA e "converter"
    // com taxa 1 — o valor digitado virava o mesmo número em dólar.
    currency: baseCurrency,
    transaction_date: todayLocalISO(),
    payers: user ? [{ user_id: String(user.id), amount: 0, payment_method: '', account_id: '' }] : [],
    payment_method: '',
    credit_card_id: '',
    installments: 1,
    category_id: '',
    tag_ids: [],
    split_mode: 'transaction',
    split_method: 'equal',
    splits: user ? [{ user_id: String(user.id), value: 0 }] : [],
    items: [],
  };

  const handleSubmit = async (payload: TransactionApiPayload) => {
    const created = await create({ ...payload, status: 'confirmed' });
    // Parcelada: o POST devolve a 1ª parcela — os recibos ficam nela, que é a
    // âncora do grupo (a mesma que a edição da compra inteira abre).
    const createdId = (created as { id?: number } | undefined)?.id;
    if (pendingFiles.length > 0 && createdId) {
      const failures = await uploadAttachments(createdId, pendingFiles);
      if (failures.length > 0) {
        // A despesa já está salva: anexo que falha vira aviso, não desfaz nada
        toast.error(
          failures.length === 1 ? 'Um anexo não foi enviado' : `${failures.length} anexos não foram enviados`,
          failures.map((f) => `${f.filename}: ${f.message}`).join(' · '),
        );
      }
    }
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) setPendingFiles([]);
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[680px] max-h-[90vh] overflow-y-auto bg-card border-border shadow-2xl">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold flex items-center gap-2">
            <span className="w-1.5 h-6 bg-primary rounded-full" />
            Nova Despesa
          </DialogTitle>
          <DialogDescription className="text-muted-foreground">
            Adicione uma transação e defina como ela será dividida.
          </DialogDescription>
        </DialogHeader>
        <TransactionForm
          initialValues={initialValues}
          onSubmit={handleSubmit}
          submitLabel="Salvar Despesa"
          allowInstallments
          extraFields={
            <AttachmentsSection pendingFiles={pendingFiles} onPendingFilesChange={setPendingFiles} />
          }
          onSuccess={() => {
            toast.success('Despesa adicionada');
            setPendingFiles([]);
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
