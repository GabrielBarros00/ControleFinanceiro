import { useTxDetailStore } from '@/stores';
import { useTransaction, useTransactions, useInstallmentGroup } from '@/hooks/use-transactions';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { useConfirm } from '@/components/ui/confirm';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';
import { TransactionDetailDialog } from './TransactionDetailDialog';
import { TransactionDialog } from './TransactionDialog';

// Host global do detalhe/edição de lançamento (montado uma vez no AppShell).
// Abre por id via useTxDetailStore, busca o lançamento e alterna entre o preview
// read-only (view) e o form completo (edit) — sem diálogos aninhados.
export function TransactionDetailHost() {
  const { txId, mode, setMode, close } = useTxDetailStore();
  const { transaction } = useTransaction(txId);
  const { update, updateGroup, remove, removeGroup } = useTransactions();
  const { canWrite } = useWorkspaceRole();
  const confirm = useConfirm();

  // Compra parcelada: carrega a definição inteira (total cheio + nº + pagas).
  // Vale para editar E para excluir a compra inteira, então busca já no view.
  const isGroup = (transaction?.installments_of ?? 0) > 1;
  const { group } = useInstallmentGroup(txId, isGroup);
  const paidCount = group?.paid_count ?? 0;

  const handleDelete = async (id: number) => {
    // Compra parcelada é coesa: excluir remove a compra inteira (todas as
    // parcelas em aberto), simétrico à edição. O backend preserva as pagas.
    const isInstallment = !!transaction?.installment_group_id;
    const ok = await confirm({
      title: isInstallment ? 'Excluir compra parcelada' : 'Remover transação',
      description: isInstallment
        ? paidCount > 0
          ? `Isto remove todas as parcelas em aberto desta compra. ${paidCount} parcela(s) já paga(s) serão mantidas.`
          : 'Isto remove todas as parcelas desta compra.'
        : 'Tem certeza que deseja remover esta transação?',
      confirmLabel: isInstallment ? 'Excluir compra' : 'Remover',
      destructive: true,
    });
    if (!ok) return;
    try {
      if (isInstallment) {
        await removeGroup(id);
      } else {
        await remove(id);
      }
      close();
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao remover transação'));
    }
  };

  const handleSave = async (data: Record<string, unknown>) => {
    if (txId == null) return;

    // Compra parcelada: qualquer edição COMPLETA (com payers) vale para o grupo
    // inteiro — refatia total/nº e congela pagas. (Reabertura é só status, sem
    // payers, e segue pelo update normal.) O backend exige nº de parcelas ≥ 2.
    if (transaction?.installment_group_id && data.payers !== undefined) {
      const ok = await confirm({
        title: 'Editar compra parcelada',
        description:
          paidCount > 0
            ? `Isto atualiza todas as parcelas em aberto desta compra. ${paidCount} parcela(s) já paga(s) serão mantidas.`
            : 'Isto atualiza todas as parcelas desta compra (valor, número de parcelas e divisão).',
        confirmLabel: 'Salvar tudo',
      });
      if (!ok) return;
      await updateGroup({ id: txId, data });
      close();
      return;
    }

    await update({ id: txId, data });
    // Reabertura (só status) mantém o modal aberto: o refetch troca para o form.
    const isReopen = Object.keys(data).length === 1 && data.status === 'confirmed';
    if (!isReopen) close();
  };

  return (
    <>
      <TransactionDetailDialog
        transaction={mode === 'view' ? transaction : null}
        open={txId != null && mode === 'view'}
        onOpenChange={(o) => { if (!o) close(); }}
        canWrite={canWrite}
        onEdit={() => setMode('edit')}
        onDelete={handleDelete}
      />
      <TransactionDialog
        transaction={mode === 'edit' ? transaction : null}
        open={txId != null && mode === 'edit'}
        onOpenChange={(o) => { if (!o) close(); }}
        onSave={handleSave}
        onDelete={handleDelete}
        installmentWhole={group?.whole ?? null}
        paidCount={paidCount}
      />
    </>
  );
}
