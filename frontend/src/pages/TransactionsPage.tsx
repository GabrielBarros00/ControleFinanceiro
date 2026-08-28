import * as React from 'react';
import { Search, Plus, ChevronLeft, ChevronRight, Receipt, FilterX } from 'lucide-react';
import { useTransactions, type TransactionFilters } from '@/hooks/use-transactions';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { useMonthParam } from '@/hooks/use-month-param';
import { useNewTxStore, useTxDetailStore, useUIStore } from '@/stores';
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
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { PAYMENT_METHOD_OPTIONS } from '@/lib/payment-methods';
import { useCategories } from '@/hooks/use-categories';
import { useTags } from '@/hooks/use-tags';
import { FilterBar } from '@/components/layout/FilterBar';


const SEARCH_DEBOUNCE_MS = 300;

export function TransactionsPage() {
  // O mês mora na URL (sobrevive a reload/voltar e dá para compartilhar); o resto
  // do filtro é estado de tela.
  const [month, setMonth] = useMonthParam();
  const [filters, setFilters] = React.useState<Omit<TransactionFilters, 'month'>>({
    page: 1,
    limit: 15,
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
    useTransactions({ ...filters, month });
  const { currentWorkspaceId } = useUIStore();
  const { canWrite } = useWorkspaceRole();
  const baseCurrency = useBaseCurrency();
  const { categories } = useCategories();
  const { tags } = useTags();
  const setNewTxOpen = useNewTxStore((s) => s.setOpen);
  const openDetail = useTxDetailStore((s) => s.open);
  const confirm = useConfirm();

  const patch = (p: Partial<Omit<TransactionFilters, 'month'>>) =>
    setFilters((f) => ({ ...f, ...p, page: p.page ?? 1 }));

  // Categoria e tag são IDs de UM workspace. Ao trocar de workspace eles não
  // existem do outro lado: a lista voltava VAZIA e o select ficava com um rótulo
  // que não correspondia a nada — parecia que o workspace novo não tinha
  // lançamento nenhum. (O CardsPage já zerava o cartão selecionado por isso.)
  React.useEffect(() => {
    setSearchInput('');
    setFilters((f) => ({
      ...f,
      page: 1,
      search: '',
      category_id: undefined,
      payment_method: undefined,
      tag_id: undefined,
    }));
  }, [currentWorkspaceId]);

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
  const categoryOptions = React.useMemo(
    () => categories.map((c) => ({ value: String(c.id), label: c.name })),
    [categories],
  );
  const tagOptions = React.useMemo(
    () => tags.map((t) => ({ value: String(t.id), label: t.name })),
    [tags],
  );

  const hasFilters =
    !!searchInput || !!filters.payment_method || !!filters.category_id ||
    !!filters.tag_id || filters.settled !== undefined;

  return (
    <div className="space-y-6">
      {/* `scope`: "Lançamentos" era o único título do espaço sem nenhuma marca
          de escopo, e é a tela mais visitada — quem chega por ela não tem como
          saber que está vendo um espaço e não o próprio total. */}
      <PageHeader
        title="Lançamentos"
        subtitle="Tudo que entrou e saiu."
        scope="workspace"
        period={
          <PeriodPicker value={month} onChange={setMonth} />
        }
        action={
          <Button onClick={() => setNewTxOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" /> Nova despesa
          </Button>
        }
      />

      <FilterBar
        ativos={
          [filters.payment_method, filters.category_id, filters.tag_id, filters.settled]
            .filter((f) => f !== undefined && f !== null && f !== '')
            .length
        }
        onLimpar={() => {
          setSearchInput('');
          patch({
            search: '', payment_method: undefined, category_id: undefined,
            tag_id: undefined, settled: undefined,
          });
        }}
        destaque={
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Buscar por descrição..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-9"
            />
          </div>
        }
      >
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
        {/* Categoria e tag: o backend implementa os dois filtros
            (routes/transactions.py) e o hook já os enviava — faltava só o
            controle na tela. */}
        <Select
          items={[{ value: 'all', label: 'Toda categoria' }, ...categoryOptions]}
          value={filters.category_id ? String(filters.category_id) : 'all'}
          onValueChange={(v: string | null) =>
            patch({ category_id: v && v !== 'all' ? Number(v) : undefined })
          }
        >
          <SelectTrigger className="w-full sm:w-[184px]">
            <SelectValue placeholder="Categoria" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Toda categoria</SelectItem>
            {categoryOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {/* Liquidação (ADR 0029) — outro eixo, ao lado de "Todo pagamento".
            "A pagar" é o mesmo recorte da tela de Contas a pagar, aqui dentro do
            extrato para quem já está olhando o mês. */}
        <Select
          items={[
            { value: 'all', label: 'Pagas e a pagar' },
            { value: 'unsettled', label: 'Só a pagar' },
            { value: 'settled', label: 'Só pagas' },
          ]}
          value={filters.settled === undefined ? 'all' : filters.settled ? 'settled' : 'unsettled'}
          onValueChange={(v: string | null) =>
            patch({ settled: v === 'settled' ? true : v === 'unsettled' ? false : undefined })
          }
        >
          <SelectTrigger className="w-full sm:w-[176px]">
            <SelectValue placeholder="Liquidação" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Pagas e a pagar</SelectItem>
            <SelectItem value="unsettled">Só a pagar</SelectItem>
            <SelectItem value="settled">Só pagas</SelectItem>
          </SelectContent>
        </Select>
        <Select
          items={[{ value: 'all', label: 'Toda tag' }, ...tagOptions]}
          value={filters.tag_id ? String(filters.tag_id) : 'all'}
          onValueChange={(v: string | null) =>
            patch({ tag_id: v && v !== 'all' ? Number(v) : undefined })
          }
        >
          <SelectTrigger className="w-full sm:w-[160px]">
            <SelectValue placeholder="Tag" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Toda tag</SelectItem>
            {tagOptions.map((o) => (
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
            className="hidden sm:inline-flex"
            onClick={() => {
              setSearchInput('');
              patch({
                search: '',
                payment_method: undefined,
                category_id: undefined,
                tag_id: undefined,
              });
            }}
          >
            <FilterX className="h-4 w-4" />
          </Button>
        )}
      </FilterBar>

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
                saídas <span className="tabular font-medium text-expense">{formatMoney(totalSpent, { currency: baseCurrency })}</span>
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
