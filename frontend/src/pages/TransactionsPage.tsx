import * as React from 'react';
import { Search, Plus, ChevronLeft, ChevronRight, Receipt, FilterX } from 'lucide-react';
import { useTransactions, type TransactionFilters } from '@/hooks/use-transactions';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { useSearchParams } from 'react-router-dom';
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
  /*
   * TODO o recorte mora na URL — mês, busca e os quatro filtros.
   *
   * O mês já morava; o resto era `useState`, e a diferença aparecia no uso: com
   * "Café" digitado na busca, um F5 devolvia a lista inteira com o campo vazio,
   * e não havia como mandar a alguém "olha estes lançamentos". Duas metades do
   * mesmo recorte, guardadas em lugares diferentes.
   *
   * `replace: true` (dentro do `useSearchParams`) porque filtrar é ajuste de
   * visualização e não navegação: com `push`, sair da tela exigiria um "voltar"
   * por tecla digitada.
   */
  const [month, setMonth] = useMonthParam();
  const [searchParams, setSearchParams] = useSearchParams();

  const filtroDaUrl = (nome: string) => searchParams.get(nome) ?? undefined;
  const numeroDaUrl = (nome: string) => {
    const bruto = searchParams.get(nome);
    const n = bruto == null ? NaN : Number(bruto);
    return Number.isInteger(n) && n > 0 ? n : undefined;
  };
  const filters: Omit<TransactionFilters, 'month'> = {
    page: numeroDaUrl('page') ?? 1,
    limit: 15,
    search: searchParams.get('q') ?? '',
    payment_method: filtroDaUrl('pagamento'),
    category_id: numeroDaUrl('categoria'),
    // Chega dos Relatórios: "categorize estas". Um booleano na URL, para o
    // link ser compartilhável e o voltar do navegador não perder o recorte.
    uncategorized: searchParams.get('semcategoria') === 'sim' || undefined,
    tag_id: numeroDaUrl('tag'),
    // `settled` é booleano de três estados: ausente = "pagas e a pagar".
    settled: searchParams.has('pagas') ? searchParams.get('pagas') === 'sim' : undefined,
  };

  const escreverNaUrl = React.useCallback(
    (mudancas: Record<string, string | number | undefined>) => {
      setSearchParams((anterior) => {
        const proximo = new URLSearchParams(anterior);
        for (const [chave, valor] of Object.entries(mudancas)) {
          if (valor === undefined || valor === '') proximo.delete(chave);
          else proximo.set(chave, String(valor));
        }
        return proximo;
      }, { replace: true });
    },
    [setSearchParams],
  );

  // O campo responde a cada tecla, mas a query só sai quando o usuário para de
  // digitar — antes "supermercado" disparava 12 requisições. O estado local
  // continua existindo por isso: é o texto EM DIGITAÇÃO, e só o texto assentado
  // vai para a URL.
  const [searchInput, setSearchInput] = React.useState(() => searchParams.get('q') ?? '');
  React.useEffect(() => {
    const id = setTimeout(() => {
      if ((searchParams.get('q') ?? '') === searchInput) return;
      escreverNaUrl({ q: searchInput || undefined, page: undefined });
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [searchInput, searchParams, escreverNaUrl]);

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

  // Tradução entre o vocabulário do hook de dados e os nomes CURTOS da URL —
  // que são o que a pessoa vê e eventualmente copia.
  const patch = (p: Partial<Omit<TransactionFilters, 'month'>>) =>
    escreverNaUrl({
      ...('search' in p ? { q: p.search || undefined } : {}),
      ...('payment_method' in p ? { pagamento: p.payment_method } : {}),
      ...('category_id' in p ? { categoria: p.category_id } : {}),
      ...('uncategorized' in p ? { semcategoria: p.uncategorized ? 'sim' : undefined } : {}),
      ...('tag_id' in p ? { tag: p.tag_id } : {}),
      ...('settled' in p ? { pagas: p.settled === undefined ? undefined : (p.settled ? 'sim' : 'nao') } : {}),
      page: p.page ?? undefined,
    });

  // Categoria e tag são IDs de UM workspace. Ao trocar de workspace eles não
  // existem do outro lado: a lista voltava VAZIA e o select ficava com um rótulo
  // que não correspondia a nada — parecia que o workspace novo não tinha
  // lançamento nenhum. (O CardsPage já zerava o cartão selecionado por isso.)
  //
  // Só na TROCA, nunca na montagem — daí o `ref`.
  //
  // Enquanto o filtro era estado local, limpar na montagem não fazia diferença
  // (o estado já nascia vazio). Agora que ele mora na URL, o mesmo efeito
  // apagava o recorte que veio NO ENDEREÇO: abrir
  // `/w/1/transactions?q=Café` mostrava a lista inteira e a URL voltava limpa,
  // que é exatamente o contrário do que levar o filtro para a URL serve.
  //
  // Só o CAMPO de busca é zerado aqui; a URL não é tocada.
  //
  // Tocar na URL neste efeito é uma corrida com a própria troca de espaço: o
  // `ScopeSwitcher` navega para `/w/<novo>/transactions` e, no mesmo ciclo, o
  // store muda e este efeito dispara um `setSearchParams` — que se aplica à
  // localização ANTERIOR e desfaz a navegação. O E2E pegou exatamente isso:
  // trocar de espaço no celular deixava a URL em `/w/151/transactions` depois
  // de escolher o 152.
  //
  // E é desnecessário: o `workspacePath` monta o caminho novo SEM query string,
  // então os filtros já não atravessam a troca. O que sobra para limpar é o
  // texto em digitação, que vive fora da URL justamente por causa do debounce.
  const espacoAnterior = React.useRef(currentWorkspaceId);
  React.useEffect(() => {
    if (espacoAnterior.current === currentWorkspaceId) return;
    espacoAnterior.current = currentWorkspaceId;
    setSearchInput('');
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
          <SelectTrigger aria-label="Filtrar por forma de pagamento" className="w-full sm:w-[184px]">
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
        {/* "Sem categoria" é uma opção do MESMO seletor, e não um filtro à parte:
            é assim que ela fica ao alcance de quem nunca leu os Relatórios. Ela
            é a lista de trabalho de quem quer arrumar a casa — e o quadro "Maior
            categoria: Sem categoria", que antes só constatava o problema, agora
            aponta para cá. */}
        <Select
          items={[
            { value: 'all', label: 'Toda categoria' },
            { value: 'sem', label: 'Sem categoria' },
            ...categoryOptions,
          ]}
          value={filters.uncategorized ? 'sem' : filters.category_id ? String(filters.category_id) : 'all'}
          onValueChange={(v: string | null) =>
            patch(v === 'sem'
              ? { category_id: undefined, uncategorized: true }
              : { category_id: v && v !== 'all' ? Number(v) : undefined, uncategorized: false })
          }
        >
          <SelectTrigger aria-label="Filtrar por categoria" className="w-full sm:w-[184px]">
            <SelectValue placeholder="Categoria" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Toda categoria</SelectItem>
            <SelectItem value="sem">Sem categoria</SelectItem>
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
          <SelectTrigger aria-label="Filtrar por situação de pagamento" className="w-full sm:w-[176px]">
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
          <SelectTrigger aria-label="Filtrar por tag" className="w-full sm:w-[160px]">
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
