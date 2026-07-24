import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useTransactions } from '@/hooks/use-transactions';
import { useAuthStore } from '@/stores';
import { toast } from '@/stores/toast';
import { TransactionForm, type TransactionApiPayload } from './transaction-form/TransactionForm';
import { todayLocalISO, type TransactionFormValues } from './transaction-form/schema';

interface NewTransactionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Criação de despesa em modal (padrão do app, ver IncomePage). O form slim é o
// mesmo da edição — aqui pré-preenchido com os defaults de uma nova despesa.
export function NewTransactionDialog({ open, onOpenChange }: NewTransactionDialogProps) {
  const { user } = useAuthStore();
  const { create } = useTransactions();

  const initialValues: TransactionFormValues = {
    title: '',
    total_amount: 0,
    currency: 'BRL',
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
    await create({ ...payload, status: 'confirmed' });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
          onSuccess={() => {
            toast.success('Despesa adicionada');
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
