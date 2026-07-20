import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useTransactions } from '@/hooks/use-transactions';
import { useAuthStore } from '@/stores';
import { TransactionForm, type TransactionApiPayload } from './transaction-form/TransactionForm';
import { todayLocalISO, type TransactionFormValues } from './transaction-form/schema';

export function SplitEntryForm() {
  const { user } = useAuthStore();
  const { create } = useTransactions();

  const initialValues: TransactionFormValues = {
    title: '',
    total_amount: 0,
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
    <Card className="w-full max-w-2xl mx-auto bg-card border-border shadow-xl">
      <CardHeader className="pb-4">
        <CardTitle className="text-2xl font-bold text-foreground">Nova Despesa</CardTitle>
        <CardDescription className="text-muted-foreground">Adicione uma nova transação e defina como ela será dividida.</CardDescription>
      </CardHeader>
      <CardContent>
        <TransactionForm
          initialValues={initialValues}
          onSubmit={handleSubmit}
          submitLabel="Salvar Despesa"
          resetOnSuccess
          allowInstallments
        />
      </CardContent>
    </Card>
  );
}
