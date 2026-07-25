import * as React from 'react';
import { Search, Plus, ChevronLeft, ChevronRight, Receipt, FilterX } from 'lucide-react';
import { useTransactions, type TransactionFilters } from '@/hooks/use-transactions';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { useNewTxStore, useTxDetailStore } from '@/stores';
import { useConfirm } from '@/components/ui/confirm';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';
import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { TransactionLedger } from '@/components/money/TransactionLedger';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';
import { formatMoney } from '@/lib/money';
import { PAYMENT_METHOD_OPTIONS } from '@/lib/payment-methods';
import { currentMonthLocal } from '@/lib/date';


const SEARCH_DEBOUNCE_MS = 300;

export function TransactionsPage() {
  const [filters, setFilters] = React.useState<TransactionFilters>({
    page: 1,
    limit: 15,
    month: currentMonthLocal(),
    search: '',
  });
  // O campo responde a cada tecla, mas a query só sai quando o usuário para de
  // digitar — antes "supermercado" disparava 12 requisições.
  const [searchInput, setSearchInput] = React.useState('');
  React.useEffect(() => {
    const id = setTimeout(
      () => setFilters((f) => (f.search === searchInput ? f : { ...f, search: searchInput, page: 1 })),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(id);
  }, [searchInput]);

  const { transactions, total, totalAmount, totalPages, currentPage, isLoading, isError, remove } =
    useTransactions(filters);
  const { canWrite } = useWorkspaceRole();
  const setNewTxOpen = useNewTxStore((s) => s.setOpen);
  const openDetail = useTxDetailStore((s) => s.open);
  const confirm = useConfirm();

  const patch = (p: Partial<TransactionFilters>) =>
    setFilters((f) => ({ ...f, ...p, page: p.page ?? 1 }));

  const handleDelete = async (id: number) => {
    const ok = await confirm({
      title: 'Remover transação',
      description: 'Tem certeza que deseja remover esta transação?',
      confirmLabel: 'Remover',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(id);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao remover transação'));
    }
  };

  // Soma do FILTRO inteiro (vem do backend) — antes era só a página atual,
  // exibida ao lado de uma contagem global, o que não fechava
  const totalSpent = totalAmount;
  const hasFilters = !!searchInput || !!filters.payment_method;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lançamentos"
        subtitle="Tudo que entrou e saiu."
        period={
          <PeriodPicker value={filters.month!} max={currentMonthLocal()} onChange={(m) => patch({ month: m })} />
        }
        action={
          <Button onClick={() => setNewTxOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" /> Nova despesa
          </Button>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por descrição..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          items={[{ value: 'all', label: 'Todo pagamento' }, ...PAYMENT_METHOD_OPTIONS]}
          value={filters.payment_method || 'all'}
          onValueChange={(v: string | null) => patch({ payment_method: v && v !== 'all' ? v : undefined })}
        >
          <SelectTrigger className="w-full sm:w-[184px]">
            <SelectValue placeholder="Pagamento" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todo pagamento</SelectItem>
            {PAYMENT_METHOD_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {hasFilters && (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Limpar filtros"
            onClick={() => {
              setSearchInput('');
              patch({ search: '', payment_method: undefined });
            }}
          >
            <FilterX className="h-4 w-4" />
          </Button>
        )}
      </div>

      <div className="rounded-xl border border-border bg-card">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState message="Não foi possível carregar os lançamentos." />
        ) : transactions.length === 0 ? (
          <EmptyState
            icon={Receipt}
            title="Nenhum lançamento"
            description="Nada neste período com esses filtros. Que tal registrar um gasto?"
            action={
              <Button onClick={() => setNewTxOpen(true)} className="gap-2">
                <Plus className="h-4 w-4" /> Nova despesa
              </Button>
            }
          />
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-border px-4 py-3 text-sm">
              <span className="text-muted-foreground">
                {total} lançamento{total === 1 ? '' : 's'}
              </span>
              <span className="text-muted-foreground">
                saídas <span className="tabular font-medium text-expense">{formatMoney(totalSpent)}</span>
              </span>
            </div>
            <div className="p-2 sm:p-3">
              <TransactionLedger
                transactions={transactions}
                canWrite={canWrite}
                onSelect={(tx) => openDetail(tx.id)}
                onEdit={(tx) => openDetail(tx.id, 'edit')}
                onDelete={handleDelete}
              />
            </div>
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-border px-4 py-3">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage <= 1}
                  onClick={() => patch({ page: currentPage - 1 })}
                >
                  <ChevronLeft className="h-4 w-4" /> Anterior
                </Button>
                <span className="text-xs text-muted-foreground">
                  {currentPage} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={currentPage >= totalPages}
                  onClick={() => patch({ page: currentPage + 1 })}
                >
                  Próxima <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
