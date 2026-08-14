import * as React from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { StatTile } from '@/components/ui/stat-tile';
import { PageHeader } from '@/components/layout/PageHeader';
import { ExcludedWorkspacesNotice } from '@/components/money/ExcludedWorkspacesNotice';
import { BalanceCards } from '@/components/debts/BalanceCards';
import {
  MonthlyLedgerBody,
  MonthlyLedgerTotals,
} from '@/components/debts/MonthlyLedgerBody';
import { SettlementDialog, type SettlementDraft } from '@/components/debts/SettlementDialog';
import {
  useMyDebts,
  useMyMonthlyDebts,
  useMySettlementsHistory,
  type WorkspaceDebtGroup,
} from '@/hooks/use-my-settlements';
import { useAuth } from '@/hooks/use-auth';
import { useMonthParam } from '@/hooks/use-month-param';
import { currentMonthLocal, monthLabel, shiftMonth, parseApiDate } from '@/lib/date';
import { formatMoney } from '@/lib/money';
import {
  ArrowRight,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  HandCoins,
  History,
  Landmark,
  Users,
} from 'lucide-react';

/**
 * Seus acertos — com quem eu me acerto, somando todas as casas (ADR 0027).
 *
 * Par de `DebtsPage`, que é de UMA casa, do mesmo jeito que `/me/reports` é par
 * de `/w/:id/reports`. A diferença de fundo não é o alcance, é o recorte: aqui a
 * visão é sempre a da PESSOA (`involved_only` por construção), então dívida
 * entre terceiros — que a tela da casa mostra a quem tem acesso completo — não
 * aparece. É por isso que as duas telas convivem em vez de uma substituir a
 * outra.
 *
 * **Nada é compensado entre casas.** Dever 100 na Casa e ter 100 a receber na
 * Viagem não é estar quitado: são pessoas e acordos diferentes. Por isso não há
 * "saldo líquido" aqui, só os dois números lado a lado — o líquido continua
 * existindo DENTRO de cada casa, onde ele significa alguma coisa.
 *
 * A escrita não muda de lugar: `SettlementDialog` recebe o `workspace_id` da
 * linha e vai para `POST /workspaces/{ws}/settlements`, com o teto e a trava do
 * ADR 0009 intactos.
 */
interface Pessoa {
  user_id: number;
  user_name: string;
}

/** O mínimo que o draft precisa saber sobre a casa da linha clicada. Os dois
 *  endpoints devolvem estes três campos, então serve aos dois sem cast. */
interface CasaDoDraft {
  workspace_id: number;
  workspace_name: string;
  base_currency: string;
}

export function MySettlementsPage() {
  const { user } = useAuth();
  const [month, setMonth] = useMonthParam();
  const { debts, isLoading, isError, refetch } = useMyDebts();
  const { monthly, isLoading: monthlyLoading } = useMyMonthlyDebts(month);
  const { settlements, total: totalHistorico, isLoading: histLoading } = useMySettlementsHistory();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<SettlementDraft | null>(null);

  // Moeda vem da RESPOSTA, não de `useBaseCurrency()` — esta tela não está
  // dentro de workspace nenhum, e a moeda-base da casa aberta seria a de uma
  // casa arbitrária.
  const moeda = debts?.currency ?? 'BRL';
  const isCurrentMonth = month === currentMonthLocal();

  const grupos = debts?.by_workspace ?? [];

  const [pessoasDoDraft, setPessoasDoDraft] = React.useState<Pessoa[]>([]);

  /** Ponto ÚNICO de abertura do diálogo: quem clicou diz só a dívida; a casa e as
   *  pessoas dela entram aqui. Sem isso, cada chamador montava o draft do seu
   *  jeito e um deles esqueceria o `workspace_id` — que é o que decide para onde
   *  o acerto vai. */
  const abrir = (casa: CasaDoDraft, pessoas: Pessoa[], base: SettlementDraft) => {
    setPessoasDoDraft(pessoas);
    setDraft({
      ...base,
      workspace_id: casa.workspace_id,
      workspace_name: casa.workspace_name,
      currency: casa.base_currency,
    });
    setDialogOpen(true);
  };

  // As pessoas de cada casa, para o diálogo nomear os selects sem chamar
  // `/{ws}/members` (que é por casa, e aqui há várias).
  const pessoasDoGrupo = (g: WorkspaceDebtGroup): Pessoa[] => {
    const vistos = new Map<number, string>();
    for (const d of g.net_debts) {
      vistos.set(d.debtor_id, d.debtor_name);
      vistos.set(d.creditor_id, d.creditor_name);
    }
    return [...vistos].map(([user_id, user_name]) => ({ user_id, user_name }));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Seus acertos"
        subtitle="Com quem você se acerta, somando todas as casas. Os saldos nunca se compensam entre elas."
      />

      {isError ? (
        <ErrorState
          title="Não foi possível carregar seus acertos."
          message="Sem esta resposta a tela mostraria zero, e zero aqui seria mentira."
          onRetry={() => refetch()}
        />
      ) : isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <StatTile
              label="Você deve"
              value={debts?.to_pay ?? 0}
              kind={Number(debts?.to_pay ?? 0) > 0 ? 'expense' : 'neutral'}
              currency={moeda}
              hint="Somando todas as casas"
            />
            <StatTile
              label="Você tem a receber"
              value={debts?.to_receive ?? 0}
              kind={Number(debts?.to_receive ?? 0) > 0 ? 'income' : 'neutral'}
              currency={moeda}
              hint="Somando todas as casas"
            />
          </div>

          <ExcludedWorkspacesNotice
            workspaces={debts?.excluded_workspaces ?? []}
            currency={moeda}
          />

          {/* --- O mês, uma seção por casa --------------------------------
              Independente do saldo consolidado, de propósito: `/me/debts` só
              lista casa COM saldo pendente, e a versão anterior aninhava esta
              seção dentro daquele `if`. Resultado: quitar o mês fazia o retrato
              dele desaparecer da tela — inclusive as despesas e o "tudo acertado
              ✅", que é justamente a confirmação que a pessoa foi procurar. */}
          <section className="space-y-3">
            <div className="flex flex-col gap-1">
              <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight text-foreground">
                <CalendarDays className="h-5 w-5 text-primary" /> Acertos do mês
              </h2>
              <p className="text-sm text-muted-foreground">
                O retrato de cada casa no mês escolhido. Parcelas aparecem só no mês delas.
              </p>
            </div>

            {/* Um navegador só para todas as casas: o mês é a pergunta da
                tela inteira, não de cada card. */}
            <div className="flex items-center justify-between rounded-xl border border-border bg-accent/30 p-2">
              <Button variant="ghost" size="icon" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(month, -1))}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="flex flex-col items-center">
                <span className="text-sm font-semibold capitalize text-foreground">{monthLabel(month)}</span>
                {!isCurrentMonth && (
                  <button
                    type="button"
                    onClick={() => setMonth(currentMonthLocal())}
                    className="text-[10px] font-bold text-primary hover:underline"
                  >
                    voltar para o mês atual
                  </button>
                )}
              </div>
              <Button variant="ghost" size="icon" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(month, 1))}>
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>

            {monthlyLoading ? (
              <Skeleton className="h-48 w-full" />
            ) : (monthly?.by_workspace.length ?? 0) === 0 ? (
              <p className="rounded-xl border border-border bg-card py-8 text-center text-sm text-muted-foreground">
                Nenhuma despesa em nenhuma casa neste mês.
              </p>
            ) : (
              monthly?.by_workspace.map((ws) => (
                <Card key={ws.workspace_id} className="bg-card border-border shadow-xl">
                  <CardHeader className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <CardTitle className="text-base">{ws.workspace_name}</CardTitle>
                      <Link
                        to={`/w/${ws.workspace_id}/debts`}
                        className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                      >
                        Abrir a casa <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>
                    <MonthlyLedgerTotals ledger={ws} currency={ws.base_currency} />
                  </CardHeader>
                  <CardContent className="space-y-6">
                    <MonthlyLedgerBody
                      ledger={ws}
                      members={ws.people}
                      currentUserId={user?.id}
                      canWrite={ws.can_write}
                      currency={ws.base_currency}
                      month={month}
                      onSettle={(d) => abrir(ws, ws.people, d)}
                    />
                  </CardContent>
                </Card>
              ))
            )}
          </section>

              {/* --- Saldo consolidado, uma seção por casa ------------------ */}
              <section className="space-y-4">
                <div className="space-y-1">
                  <h2 className="text-lg font-bold tracking-tight text-foreground">Saldo geral a acertar</h2>
                  <p className="text-sm text-muted-foreground">
                    Todos os meses de cada casa, já descontando os acertos. Cada casa na moeda dela.
                  </p>
                </div>

                {grupos.length === 0 && (
                  <EmptyState
                    icon={Users}
                    title="Nenhum acerto pendente"
                    description="Quando alguma despesa dividida deixar saldo entre você e outra pessoa, ela aparece aqui — separada por casa."
                  />
                )}

                {grupos.map((g) => {
                  const pessoas = pessoasDoGrupo(g);
                  return (
                    <div key={g.workspace_id} className="space-y-3">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h3 className="text-base font-semibold text-foreground">
                          {g.workspace_name}
                          <span className="ml-2 text-xs font-normal text-muted-foreground">
                            {g.base_currency}
                            {!g.converted && ' · fora do total acima'}
                          </span>
                        </h3>
                        <Link
                          to={`/w/${g.workspace_id}/debts`}
                          className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                        >
                          Abrir a casa <ArrowRight className="h-3 w-3" />
                        </Link>
                      </div>
                      <BalanceCards
                        debts={g.net_debts}
                        currentUserId={user?.id}
                        members={pessoas}
                        canWrite={g.can_write}
                        currency={g.base_currency}
                        escopo={g.workspace_name}
                        onSettle={(debt) =>
                          abrir(g, pessoas, {
                            from_user_id: debt.debtor_id,
                            to_user_id: debt.creditor_id,
                            amount: Number(debt.amount),
                          })
                        }
                      />
                    </div>
                  );
                })}
              </section>

          {/* --- Histórico, com a casa em cada linha ---------------------- */}
          <Card className="bg-card border-border shadow-xl">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <History className="h-5 w-5 text-muted-foreground" />
                Histórico de acertos
              </CardTitle>
              <CardDescription>
                Os acertos em que você é uma das pontas, em todas as casas. Para desfazer um,
                abra a casa dele.
                {/* Truncar em silêncio faria as primeiras linhas parecerem todas. */}
                {totalHistorico > settlements.length && (
                  <> Mostrando os {settlements.length} mais recentes de {totalHistorico}.</>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {histLoading ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-10" />
                  ))}
                </div>
              ) : settlements.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Nenhum acerto registrado ainda.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      <TableHead className="text-xs font-semibold text-muted-foreground">Data</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Casa</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Com quem</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Obs.</TableHead>
                      <TableHead className="text-right text-xs font-semibold text-muted-foreground">Valor</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {settlements.map((s) => (
                      <TableRow key={s.id} className="border-border hover:bg-accent/30">
                        <TableCell className="text-xs whitespace-nowrap">
                          {parseApiDate(s.settled_at).toLocaleDateString('pt-BR')}
                        </TableCell>
                        <TableCell className="text-xs">
                          <Link to={`/w/${s.workspace_id}/debts`} className="font-medium text-brand hover:underline">
                            {s.workspace_name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-sm">
                          {/* O eixo aqui sou eu: na tela da casa as colunas são
                              "Pagou"/"Recebeu" por nome, o que numa lista de
                              várias casas obriga a procurar o próprio nome em
                              toda linha. */}
                          <span className="font-bold">
                            {s.direction === 'sent' ? 'Você pagou' : 'Você recebeu de'}
                          </span>{' '}
                          {s.counterparty_name}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{s.note || '—'}</TableCell>
                        <TableCell
                          className={`text-right font-semibold whitespace-nowrap ${
                            s.direction === 'sent' ? 'text-destructive' : 'text-emerald-500'
                          }`}
                        >
                          {s.direction === 'sent' ? '−' : '+'}
                          {formatMoney(s.amount, { currency: s.currency })}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <div className="flex items-start gap-4 rounded-2xl border border-primary/10 bg-primary/5 p-6">
            <div className="rounded-xl bg-primary/10 p-2">
              <Landmark className="h-6 w-6 text-primary" />
            </div>
            <div className="space-y-1">
              <h4 className="font-bold text-foreground">Por que os saldos ficam separados por casa?</h4>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Dever R$ 100 numa casa e ter R$ 100 a receber noutra não é estar quitado — são
                pessoas e acordos diferentes. Por isso não existe um "saldo líquido" aqui: cada
                casa se resolve com um pagamento (Pix, dinheiro…) registrado nela.{' '}
                <HandCoins className="inline h-3.5 w-3.5" />
              </p>
            </div>
          </div>
        </>
      )}

      <SettlementDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        draft={draft}
        members={pessoasDoDraft}
      />
    </div>
  );
}
