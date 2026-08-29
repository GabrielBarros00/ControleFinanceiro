import * as React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { StatTile } from '@/components/ui/stat-tile';
import { PageHeader } from '@/components/layout/PageHeader';
import { ExcludedWorkspacesNotice } from '@/components/money/ExcludedWorkspacesNotice';
import { CounterpartyList } from '@/components/debts/CounterpartyList';
import { BalanceOrigin } from '@/components/debts/BalanceOrigin';
import { MonthNavigator } from '@/components/debts/MonthNavigator';
import { SettlementHistory, type HistoryRow } from '@/components/debts/SettlementHistory';
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
import { useMyDebtsByMonth } from '@/hooks/use-debts-by-month';
import { useAuth } from '@/hooks/use-auth';
import { useMonthParam } from '@/hooks/use-month-param';
import { useTabParam } from '@/hooks/use-tab-param';
import { ArrowRight, HandCoins, Landmark, Users } from 'lucide-react';

/**
 * Seus acertos — com quem eu me acerto, somando todas as casas (ADR 0027).
 *
 * Par de `DebtsPage`, que é de UMA casa, do mesmo jeito que `/me/reports` é par
 * de `/w/:id/reports`. A diferença de fundo não é o alcance, é o recorte: aqui a
 * visão é sempre a da PESSOA (`involved_only` por construção), então dívida
 * entre terceiros — que a tela da casa mostra a quem tem acesso completo — não
 * aparece.
 *
 * **Nada é compensado entre casas.** Dever 100 na Casa e ter 100 a receber na
 * Viagem não é estar quitado: são pessoas e acordos diferentes. Por isso não há
 * "saldo líquido" aqui, só os dois números lado a lado — e é por isso que os
 * dois `StatTile` do topo sobreviveram ao redesenho, enquanto na tela da casa
 * eles saíram: lá um dos dois é sempre zero, aqui os dois somam casas distintas.
 *
 * As três abas são as mesmas de `DebtsPage`, e cada uma agrupa por casa. A
 * escrita não muda de lugar: `SettlementDialog` recebe o `workspace_id` da linha
 * e vai para `POST /workspaces/{ws}/settlements`, com o teto e a trava do ADR
 * 0009 intactos.
 */
const ABAS = ['resumo', 'mes', 'historico'] as const;
type Aba = (typeof ABAS)[number];

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

/**
 * A aba "Por mês" — e o motivo de ela ser um componente.
 *
 * `useMyMonthlyDebts` varre TODAS as casas e carrega as despesas de cada uma; é
 * a consulta mais cara desta tela. Vivendo no corpo da página, ela disparava a
 * cada abertura, inclusive para quem só queria o Resumo — o Radix desmonta a aba
 * inativa, então o hook aqui dentro só corre quando a aba está aberta. A
 * `DebtsPage` já ganhava isso de graça, porque lá o hook mora dentro de
 * `MonthlyDebtsSection`; a assimetria entre as duas telas é que denunciou o
 * desperdício.
 */
function AbaPorMes({
  month,
  setMonth,
  currentUserId,
  onSettle,
  onOpenHistory,
}: {
  month: string;
  setMonth: (m: string) => void;
  currentUserId?: number;
  onSettle: (casa: CasaDoDraft, pessoas: Pessoa[], base: SettlementDraft) => void;
  onOpenHistory: () => void;
}) {
  const { monthly, isLoading, isError, refetch } = useMyMonthlyDebts(month);

  return (
    <>
      {/* Um navegador só para todas as casas: o mês é a pergunta da aba, não de
          cada card. */}
      <MonthNavigator month={month} onChange={setMonth} />

      {isError ? (
        /* ERR-001: sem a resposta, "nenhuma despesa neste mês" seria uma
           afirmação sobre dados que ninguém leu. */
        <ErrorState
          title="Não foi possível carregar o mês."
          message="Tente de novo — o retrato do mês vem de todos os seus espaços de uma vez."
          onRetry={() => refetch()}
        />
      ) : isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : (monthly?.by_workspace.length ?? 0) === 0 ? (
        <p className="rounded-xl border border-border bg-card py-8 text-center text-sm text-muted-foreground">
          Nenhuma despesa em nenhum espaço neste mês.
        </p>
      ) : (
        monthly?.by_workspace.map((ws) => (
          <Card key={ws.workspace_id} className="bg-card border-border">
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
              <MonthlyLedgerTotals
                ledger={ws}
                currency={ws.base_currency}
                currentUserId={currentUserId}
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <MonthlyLedgerBody
                ledger={ws}
                members={ws.people}
                currentUserId={currentUserId}
                canWrite={ws.can_write}
                currency={ws.base_currency}
                month={month}
                onSettle={(d) => onSettle(ws, ws.people, d)}
                onOpenHistory={onOpenHistory}
              />
            </CardContent>
          </Card>
        ))
      )}
    </>
  );
}

export function MySettlementsPage() {
  const { user } = useAuth();
  const [aba, setAba] = useTabParam<Aba>(ABAS, 'resumo');
  const [month, setMonth] = useMonthParam();
  const [, setSearchParams] = useSearchParams();
  const { debts, isLoading, isError, refetch } = useMyDebts();
  const {
    grupos: origens,
    isLoading: origemLoading,
    isError: origemError,
    refetch: refetchOrigem,
  } = useMyDebtsByMonth();
  const { settlements, total: totalHistorico, isLoading: histLoading } = useMySettlementsHistory();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<SettlementDraft | null>(null);

  // Moeda vem da RESPOSTA, não de `useBaseCurrency()` — esta tela não está
  // dentro de workspace nenhum, e a moeda-base da casa aberta seria a de uma
  // casa arbitrária.
  const moeda = debts?.currency ?? 'BRL';
  const grupos = debts?.by_workspace ?? [];
  const origemPorCasa = new Map(origens.map((o) => [o.workspace_id, o]));

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

  /** Aba e mês numa chamada SÓ — dois `setSearchParams` no mesmo tick leem o
   *  mesmo estado anterior e o segundo apaga o primeiro. */
  const abrirMes = (mes: string) =>
    setSearchParams(
      (anterior) => {
        const proximo = new URLSearchParams(anterior);
        proximo.set('tab', 'mes');
        proximo.set('month', mes);
        return proximo;
      },
      { replace: true },
    );

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

  const historico: HistoryRow[] = settlements.map((s) => ({
    id: s.id,
    settledAt: s.settled_at,
    // O eixo aqui sou eu: na tela da casa as colunas são "Pagou"/"Recebeu" por
    // nome, o que numa lista de várias casas obriga a procurar o próprio nome em
    // toda linha.
    who: (
      <>
        <span className="font-bold">
          {s.direction === 'sent' ? 'Você pagou' : 'Você recebeu de'}
        </span>{' '}
        {s.counterparty_name}
      </>
    ),
    workspace: { id: s.workspace_id, name: s.workspace_name },
    billingMonth: s.billing_month,
    note: s.note,
    amount: s.amount,
    currency: s.currency,
    kind: s.direction === 'sent' ? 'sent' : 'received',
    // Sem desfazer: a escrita mora na casa, onde vivem a direção e o teto do
    // ADR 0009.
  }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Seus acertos"
        scope="personal"
        subtitle="Com quem você se acerta, somando todos os espaços. Os saldos nunca se compensam entre eles."
      />

      {isError ? (
        <ErrorState
          title="Não foi possível carregar seus acertos."
          message="Sem esta resposta a tela mostraria zero, e zero aqui seria mentira."
          onRetry={() => refetch()}
        />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <Tabs value={aba} onValueChange={(v) => setAba(v as Aba)}>
          <TabsList>
            <TabsTrigger value="resumo">Resumo</TabsTrigger>
            <TabsTrigger value="mes">Por mês</TabsTrigger>
            <TabsTrigger value="historico">Histórico</TabsTrigger>
          </TabsList>

          {/* --- Resumo: o acumulado, uma seção por casa -------------------- */}
          <TabsContent value="resumo" className="space-y-6">
            <div className="grid grid-cols-2 gap-3 sm:gap-4">
              <StatTile
                label="Você deve"
                value={debts?.to_pay ?? 0}
                kind={Number(debts?.to_pay ?? 0) > 0 ? 'expense' : 'neutral'}
                currency={moeda}
                hint="Acumulado, todos os espaços"
              />
              <StatTile
                label="Você tem a receber"
                value={debts?.to_receive ?? 0}
                kind={Number(debts?.to_receive ?? 0) > 0 ? 'income' : 'neutral'}
                currency={moeda}
                hint="Acumulado, todos os espaços"
              />
            </div>

            <ExcludedWorkspacesNotice
              workspaces={debts?.excluded_workspaces ?? []}
              currency={moeda}
            />

            {/* ERR-001, uma vez só: a origem de TODAS as casas vem de uma
                consulta, então um aviso por espaço repetiria a mesma falha N
                vezes. O que não pode é o bloco "de onde vem" simplesmente não
                aparecer — quem já o viu leria a ausência como "não vem de mês
                nenhum". */}
            {origemError && (
              <ErrorState
                title="Não foi possível abrir a origem dos saldos."
                message="Os totais acima continuam corretos; o que falhou foi a quebra mês a mês de cada espaço."
                onRetry={() => refetchOrigem()}
              />
            )}

            {grupos.length === 0 && (
              <EmptyState
                icon={Users}
                title="Nenhum acerto pendente"
                description="Quando alguma despesa dividida deixar saldo entre você e outra pessoa, ela aparece aqui — separada por espaço."
              />
            )}

            {grupos.map((g) => {
              const pessoas = pessoasDoGrupo(g);
              const origem = origemPorCasa.get(g.workspace_id);
              return (
                <section key={g.workspace_id} className="space-y-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="text-base font-semibold text-foreground">
                      {g.workspace_name}
                      <span className="ml-2 text-xs font-normal text-muted-foreground">
                        {g.base_currency}
                        {!g.converted && ' · fora do total acima'}
                      </span>
                    </h2>
                    <Link
                      to={`/w/${g.workspace_id}/debts`}
                      className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                    >
                      Abrir a casa <ArrowRight className="h-3 w-3" />
                    </Link>
                  </div>

                  <CounterpartyList
                    debts={g.net_debts}
                    currentUserId={user?.id}
                    members={pessoas}
                    canWrite={g.can_write}
                    currency={g.base_currency}
                    escopo={g.workspace_name}
                    compacto
                    onSettle={(debt) =>
                      abrir(g, pessoas, {
                        from_user_id: debt.debtor_id,
                        to_user_id: debt.creditor_id,
                        amount: Number(debt.amount),
                      })
                    }
                  />

                  {/* Recolhido: são N casas na mesma página, e a origem é o
                      detalhe de segunda ordem — a pergunta de primeira é com
                      quem eu me acerto. */}
                  {origemLoading ? (
                    <Skeleton className="h-10 w-full" />
                  ) : origem ? (
                    <details className="group rounded-xl border border-border">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
                        De onde vem esse saldo
                        <span className="font-normal text-muted-foreground">
                          ({origem.months.length}{' '}
                          {origem.months.length === 1 ? 'mês' : 'meses'})
                        </span>
                      </summary>
                      <div className="border-t border-border p-3">
                        <BalanceOrigin
                          origem={origem}
                          currency={g.base_currency}
                          onOpenMonth={abrirMes}
                        />
                      </div>
                    </details>
                  ) : null}
                </section>
              );
            })}

            <div className="flex items-start gap-4 rounded-2xl border border-primary/10 bg-primary/5 p-6">
              <div className="rounded-xl bg-primary/10 p-2">
                <Landmark className="h-6 w-6 text-primary" />
              </div>
              <div className="space-y-1">
                <h4 className="font-bold text-foreground">Por que os saldos ficam separados por espaço?</h4>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Dever R$ 100 numa casa e ter R$ 100 a receber noutra não é estar quitado — são
                  pessoas e acordos diferentes. Por isso não existe um "saldo líquido" aqui: cada
                  casa se resolve com um pagamento (Pix, dinheiro…) registrado nela.{' '}
                  <HandCoins className="inline h-3.5 w-3.5" />
                </p>
              </div>
            </div>
          </TabsContent>

          {/* --- Por mês: o retrato do mês, uma seção por casa --------------
              Independente do saldo consolidado, de propósito: `/me/debts` só
              lista casa COM saldo pendente, e a versão anterior aninhava esta
              seção dentro daquele `if`. Resultado: quitar o mês fazia o retrato
              dele desaparecer da tela — inclusive as despesas e o "tudo acertado
              ✅", que é justamente a confirmação que a pessoa foi procurar. */}
          <TabsContent value="mes" className="space-y-4">
            <AbaPorMes
              month={month}
              setMonth={setMonth}
              currentUserId={user?.id}
              onSettle={abrir}
              onOpenHistory={() => setAba('historico')}
            />
          </TabsContent>

          {/* --- Histórico, com a casa e o mês em cada linha ---------------- */}
          <TabsContent value="historico">
            <Card className="bg-card border-border">
              <CardHeader>
                <CardTitle className="text-lg">Histórico de acertos</CardTitle>
                <CardDescription>
                  Os acertos em que você é uma das pontas, em todas as casas. A pílula diz qual
                  mês cada um fecha; para desfazer um, abra a casa dele.
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
                ) : (
                  <SettlementHistory rows={historico} />
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
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
