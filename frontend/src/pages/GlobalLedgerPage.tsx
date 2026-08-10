import { useSearchParams } from 'react-router-dom';
import { ArrowDownLeft, ArrowUpRight, Wallet } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile } from '@/components/ui/stat-tile';
import { MoneyText } from '@/components/money/MoneyText';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { useMonthParam } from '@/hooks/use-month-param';
import { useLedger, type LedgerEntry } from '@/hooks/use-overview';
import { useCreditCards, type CreditCardSummary } from '@/hooks/use-credit-cards';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { parseApiDay } from '@/lib/date';
import { formatMoney } from '@/lib/money';
import { cn } from '@/lib/utils';

/**
 * Extrato global consolidado.
 *
 * A Visão global respondia "saiu R$ 4.200" e mostrava de que ORIGEM — mas não
 * havia como chegar às linhas. Esta tela é o mesmo `CashFlowService` que produz
 * aqueles totais, listando os movimentos em vez de somá-los: o extrato fecha com
 * a Visão global por construção, não por disciplina.
 *
 * Cada linha traz a data EFETIVA (quando o dinheiro se moveu, ADR 0022), a
 * origem, o workspace quando existe, e o valor original quando o movimento foi
 * em outra moeda.
 */
const ORIGENS: { value: string; label: string }[] = [
  { value: 'transaction', label: 'Despesas' },
  { value: 'statement_payment', label: 'Faturas' },
  { value: 'settlement_sent', label: 'Acertos enviados' },
  { value: 'settlement_received', label: 'Acertos recebidos' },
  { value: 'financing_installment', label: 'Financiamentos' },
  { value: 'income', label: 'Rendas' },
];

const ROTULO_ORIGEM: Record<string, string> = Object.fromEntries(
  ORIGENS.map((o) => [o.value, o.label]),
);

/**
 * Movimentos por página.
 *
 * A tela pedia 200 de uma vez e, passando disso, só mandava "use os filtros para
 * estreitar o recorte" — o que não é resposta para quem simplesmente tem mais de
 * 200 movimentos no mês: o resto do extrato ficava inalcançável. O backend
 * sempre aceitou `limit`/`offset` e devolve `total`; faltava a tela usar.
 */
const POR_PAGINA = 100;

export function GlobalLedgerPage() {
  const [month, setMonth] = useMonthParam();
  const [params, setParams] = useSearchParams();
  const { workspaces } = useWorkspaces();
  const { cards } = useCreditCards();

  const origensAtivas = params.getAll('source');
  const workspaceFiltro = params.get('workspace_id');
  const cartaoFiltro = params.get('card_id');
  // A página vive na URL junto do resto do recorte: um extrato é coisa que se
  // manda para alguém, e o link tem de reabrir onde estava.
  const pagina = Math.max(0, Number(params.get('page') ?? '0') || 0);

  const { ledger, isLoading } = useLedger({
    month,
    source: origensAtivas.length ? origensAtivas : undefined,
    workspace_id: workspaceFiltro ? Number(workspaceFiltro) : undefined,
    card_id: cartaoFiltro ? Number(cartaoFiltro) : undefined,
    limit: POR_PAGINA,
    offset: pagina * POR_PAGINA,
  });

  const moeda = ledger?.currency ?? 'BRL';
  const n = (v: unknown) => Number(v ?? 0);

  const total = ledger?.total ?? 0;
  const nesta = ledger?.entries.length ?? 0;
  const ultimaPagina = Math.max(0, Math.ceil(total / POR_PAGINA) - 1);
  const primeiroDaPagina = pagina * POR_PAGINA + 1;

  /** Todo filtro reancora na página 1 — senão trocar o recorte cairia num offset
   *  que já não existe e a tela ficaria vazia sem explicação. */
  const aplicar = (mudar: (p: URLSearchParams) => void) => {
    const proximo = new URLSearchParams(params);
    mudar(proximo);
    proximo.delete('page');
    setParams(proximo, { replace: true });
  };

  const alternarOrigem = (valor: string) =>
    aplicar((proximo) => {
      const atuais = proximo.getAll('source');
      proximo.delete('source');
      const novo = atuais.includes(valor)
        ? atuais.filter((v) => v !== valor)
        : [...atuais, valor];
      novo.forEach((v) => proximo.append('source', v));
    });

  const definirWorkspace = (valor: string) =>
    aplicar((proximo) => {
      if (valor) proximo.set('workspace_id', valor);
      else proximo.delete('workspace_id');
    });

  const definirCartao = (valor: string) =>
    aplicar((proximo) => {
      if (valor) proximo.set('card_id', valor);
      else proximo.delete('card_id');
    });

  const limparFiltros = () =>
    aplicar((proximo) => {
      proximo.delete('source');
      proximo.delete('workspace_id');
      proximo.delete('card_id');
    });

  const irParaPagina = (alvo: number) => {
    const proximo = new URLSearchParams(params);
    if (alvo <= 0) proximo.delete('page');
    else proximo.set('page', String(alvo));
    setParams(proximo, { replace: true });
  };

  // Trocar de mês é trocar de recorte: a página tem de voltar ao início.
  const trocarMes = (novo: string) => {
    irParaPagina(0);
    setMonth(novo);
  };

  const temFiltro =
    origensAtivas.length > 0 || Boolean(workspaceFiltro) || Boolean(cartaoFiltro);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Extrato"
          subtitle="Cada movimento de caixa do mês, em todos os workspaces."
        />
        <PeriodPicker value={month} onChange={trocarMes} />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Entrou" value={n(ledger?.cash_in)} kind="income" icon={ArrowDownLeft} currency={moeda} />
        <StatTile label="Saiu" value={n(ledger?.cash_out)} kind="expense" icon={ArrowUpRight} currency={moeda} />
        <StatTile
          label="Saldo do mês"
          value={n(ledger?.net_cash)}
          kind={n(ledger?.net_cash) >= 0 ? 'income' : 'expense'}
          icon={Wallet}
          currency={moeda}
          hint="Entradas menos saídas — não é saldo bancário"
        />
      </div>

      <ExcludedForeignNotice count={ledger?.excluded_foreign_count ?? 0} baseCurrency={moeda} />

      <Card className="bg-card border-border">
        <CardContent className="space-y-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <div role="group" aria-label="Filtrar por origem" className="flex flex-wrap gap-2">
              {ORIGENS.map((o) => {
                const ativo = origensAtivas.includes(o.value);
                return (
                  <button
                    key={o.value}
                    type="button"
                    aria-pressed={ativo}
                    onClick={() => alternarOrigem(o.value)}
                    className={cn(
                      'rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors',
                      ativo
                        ? 'border-brand bg-brand text-primary-foreground'
                        : 'border-border text-muted-foreground hover:bg-muted',
                    )}
                  >
                    {o.label}
                  </button>
                );
              })}
            </div>
            {workspaces.length > 1 && (
              <select
                aria-label="Filtrar por workspace"
                value={workspaceFiltro ?? ''}
                onChange={(e) => definirWorkspace(e.target.value)}
                className="h-10 min-w-[10rem] rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Todos os workspaces</option>
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            )}
            {/* O backend já aceitava `card_id` e a tela não oferecia: quem tem
                dois cartões não tinha como perguntar "o que paguei no Nubank". */}
            {cards.length > 1 && (
              <select
                aria-label="Filtrar por cartão"
                value={cartaoFiltro ?? ''}
                onChange={(e) => definirCartao(e.target.value)}
                className="h-10 min-w-[10rem] rounded-md border border-border bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Todos os cartões</option>
                {(cards as CreditCardSummary[]).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            )}
            {temFiltro && (
              <Button type="button" variant="ghost" size="sm" onClick={limparFiltros}>
                Limpar filtros
              </Button>
            )}
          </div>

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (ledger?.entries.length ?? 0) === 0 ? (
            <EmptyState
              icon={Wallet}
              title="Nenhum movimento neste recorte"
              description={
                temFiltro
                  ? 'Nenhum movimento com estes filtros. Limpe-os para ver o mês inteiro.'
                  : 'Nada entrou nem saiu neste mês.'
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-border">
                    <TableHead className="text-xs font-semibold">Data</TableHead>
                    <TableHead className="text-xs font-semibold">Movimento</TableHead>
                    <TableHead className="text-xs font-semibold">Origem</TableHead>
                    <TableHead className="text-right text-xs font-semibold">Valor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ledger?.entries.map((e: LedgerEntry) => (
                    <TableRow key={`${e.source}-${e.reference_id}`} className="border-border">
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        {parseApiDay(e.occurred_on).toLocaleDateString('pt-BR', {
                          day: '2-digit',
                          month: '2-digit',
                        })}
                      </TableCell>
                      <TableCell className="text-sm">
                        <span className="font-medium">{e.title ?? '—'}</span>
                        {e.workspace_name && (
                          <span className="ml-2 text-xs text-muted-foreground">{e.workspace_name}</span>
                        )}
                        {e.counterparty_name && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            · {e.counterparty_name}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="border-border text-xs text-muted-foreground">
                          {ROTULO_ORIGEM[e.source] ?? e.source}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {e.converted_amount === null ? (
                          // Sem cotação para a data efetiva: a linha aparece
                          // marcada em vez de sumir ou virar zero (ADR 0006).
                          <span className="text-sm text-muted-foreground" title="Sem cotação para esta data">
                            {formatMoney(Number(e.amount), { currency: e.currency })} *
                          </span>
                        ) : (
                          <>
                            <MoneyText
                              value={e.converted_amount}
                              kind={e.direction === 'in' ? 'income' : 'expense'}
                              currency={moeda}
                              className="font-semibold"
                            />
                            {e.currency !== moeda && (
                              <span className="ml-2 text-xs text-muted-foreground">
                                {formatMoney(Number(e.amount), { currency: e.currency })}
                              </span>
                            )}
                          </>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {total > POR_PAGINA && (
                <nav
                  aria-label="Paginação do extrato"
                  className="mt-3 flex flex-wrap items-center justify-between gap-3"
                >
                  <p className="text-xs text-muted-foreground" aria-live="polite">
                    Mostrando {primeiroDaPagina}–{primeiroDaPagina + nesta - 1} de {total}{' '}
                    movimentos
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={pagina === 0}
                      onClick={() => irParaPagina(pagina - 1)}
                    >
                      Anterior
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={pagina >= ultimaPagina}
                      onClick={() => irParaPagina(pagina + 1)}
                    >
                      Próxima
                    </Button>
                  </div>
                </nav>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
