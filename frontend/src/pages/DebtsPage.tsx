import * as React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { useDebts } from '@/hooks/use-debts';
import { useDebtsByMonth } from '@/hooks/use-debts-by-month';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { formatMoney } from '@/lib/money';
import { ArrowRight, Users, Loader2, RefreshCcw, Landmark, HandCoins, Globe } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { useMembers } from '@/hooks/use-members';
import { useSettlements } from '@/hooks/use-settlements';
import { SettlementDialog, type SettlementDraft } from '@/components/debts/SettlementDialog';
import { CounterpartyList } from '@/components/debts/CounterpartyList';
import { BalanceOrigin } from '@/components/debts/BalanceOrigin';
import { SettlementHistory, type HistoryRow } from '@/components/debts/SettlementHistory';
import { MonthNavigator } from '@/components/debts/MonthNavigator';
import { MonthlyDebtsSection } from '@/components/debts/MonthlyDebtsSection';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { PageHeader } from '@/components/layout/PageHeader';
import { useMonthParam } from '@/hooks/use-month-param';
import { useTabParam } from '@/hooks/use-tab-param';

/**
 * Acertos DESTA casa, em três abas.
 *
 * A tela empilhava quatro escopos na mesma rolagem — o acumulado de todos os
 * meses, o retrato de um mês, as despesas que originaram a dívida e o histórico
 * de pagamentos — sem dizer qual era qual. Cada aba responde UMA pergunta, e o
 * rótulo dela já é a resposta de escopo.
 *
 * O topo perdeu os três `StatTile`. Dentro de UM espaço, dois deles eram sempre
 * zero: o pareamento de `_settle_balances` põe cada pessoa em um lado só, então
 * quem deve não recebe de ninguém — e "Saldo líquido" era só o sinal do que
 * sobrava. Três números para um número.
 */
const ABAS = ['resumo', 'mes', 'historico'] as const;
type Aba = (typeof ABAS)[number];

interface Debt {
  debtor_id: number;
  creditor_id: number;
  amount: string;
}

export function DebtsPage() {
  // Moeda-base do workspace: o backend soma nela, a tela precisa dizer qual é.
  const baseCurrency = useBaseCurrency();
  const formatBRL = (value: string | number) => formatMoney(value, { currency: baseCurrency });
  const { debts, isLoading, isError, refetch } = useDebts();
  const {
    origem,
    isLoading: origemLoading,
    isError: origemError,
    refetch: refetchOrigem,
  } = useDebtsByMonth();
  const { user } = useAuth();
  const { canWrite } = useWorkspaceRole();  // viewer não registra/desfaz acertos (RBAC-FE-001)
  const { members } = useMembers();
  const { settlements, isLoading: histLoading, remove } = useSettlements();
  const confirm = useConfirm();
  const [aba, setAba] = useTabParam<Aba>(ABAS, 'resumo');
  const [month, setMonth] = useMonthParam();
  const [, setSearchParams] = useSearchParams();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<SettlementDraft | null>(null);

  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;

  /**
   * Abrir um mês a partir do Resumo: `tab` e `month` numa chamada SÓ.
   *
   * Dois `setSearchParams` no mesmo tick leem ambos o `searchParams` atual, e o
   * segundo sobrescreve o primeiro — a aba trocaria e o mês continuaria o de
   * antes (ou o contrário, a depender da ordem). Aqui o updater escreve os dois.
   */
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

  const openSettlement = (debt: { debtor_id: number; creditor_id: number; amount: string | number }) => {
    setDraft({
      from_user_id: debt.debtor_id,
      to_user_id: debt.creditor_id,
      amount: Number(debt.amount),
    });
    setDialogOpen(true);
  };

  const undoSettlement = async (id: number) => {
    const ok = await confirm({
      title: 'Desfazer acerto',
      description: 'Desfazer este acerto? A dívida correspondente volta ao balanço.',
      confirmLabel: 'Desfazer',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(id);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao desfazer o acerto.'));
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-[240px] items-center justify-center sm:h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Estado de erro explícito (ERR-001): falha não pode parecer "sem dívidas"
  if (isError) {
    return (
      <ErrorState
        title="Não foi possível carregar as dívidas."
        message="Sem esta resposta a tela mostraria zero, e zero aqui seria mentira."
        onRetry={() => refetch()}
      />
    );
  }

  const typedDebts = debts as Debt[];
  const otherDebts = typedDebts.filter((d) => d.debtor_id !== user?.id && d.creditor_id !== user?.id);

  const totalOwed = typedDebts
    .filter((d) => d.debtor_id === user?.id)
    .reduce((a, d) => a + parseFloat(d.amount), 0);
  const totalCredit = typedDebts
    .filter((d) => d.creditor_id === user?.id)
    .reduce((a, d) => a + parseFloat(d.amount), 0);
  const saldo = totalCredit - totalOwed;

  const historico: HistoryRow[] = settlements.map((s) => ({
    id: s.id,
    settledAt: s.settled_at,
    who: (
      <>
        <span className="font-bold">
          {s.from_user_id === user?.id ? 'Você' : memberName(s.from_user_id)}
        </span>
        <span className="text-muted-foreground"> pagou a </span>
        <span className="font-bold">
          {s.to_user_id === user?.id ? 'você' : memberName(s.to_user_id)}
        </span>
      </>
    ),
    billingMonth: s.billing_month,
    note: s.note,
    amount: s.amount,
    currency: baseCurrency,
    // Mesmo eixo da tela global: saiu de mim, entrou para mim, ou é entre
    // terceiros. Antes toda linha saía verde, inclusive as que eu paguei.
    kind:
      s.from_user_id === user?.id ? 'sent' : s.to_user_id === user?.id ? 'received' : 'neutral',
    onUndo: () => undoSettlement(s.id),
    canUndo: canWrite,
  }));

  return (
    <div className="space-y-6">
      {/* O ESCOPO tem de estar no cabeçalho: sem ele, quem participa de dois
          espaços lê estes números como se fossem o total dela — e eles nunca
          foram. O total mora em Seus acertos. */}
      <PageHeader
        title="Acertos"
        scope="workspace"
        subtitle="Somente este espaço. Seus acertos de todos os espaços ficam em Pessoal › Seus acertos."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/me/settlements">
              <Button variant="outline" className="gap-2">
                <Globe className="h-4 w-4" /> Ver todos os espaços
              </Button>
            </Link>
            <Button variant="outline" onClick={() => refetch()} className="gap-2">
              <RefreshCcw className="h-4 w-4" /> Atualizar
            </Button>
          </div>
        }
      />

      <Tabs value={aba} onValueChange={(v) => setAba(v as Aba)}>
        <TabsList>
          <TabsTrigger value="resumo">Resumo</TabsTrigger>
          <TabsTrigger value="mes">Por mês</TabsTrigger>
          <TabsTrigger value="historico">Histórico</TabsTrigger>
        </TabsList>

        {/* --- Resumo: com quem me acerto, e de onde vem o saldo ------------ */}
        <TabsContent value="resumo" className="space-y-6">
          <section className="space-y-3">
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-sm text-muted-foreground">
                {saldo === 0 ? 'Neste espaço' : saldo < 0 ? 'Você deve, no total' : 'Você tem a receber, no total'}
              </p>
              <p
                className={`mt-1 text-2xl font-semibold ${
                  saldo === 0 ? 'text-foreground' : saldo < 0 ? 'text-expense' : 'text-income'
                }`}
              >
                {saldo === 0 ? 'Tudo certo' : formatBRL(Math.abs(saldo))}
              </p>
              {/* A frase que o redesenho existe para dizer. O número é
                  cumulativo, e lido sozinho passava por cobrança do mês. */}
              <p className="mt-1 text-xs text-muted-foreground">
                Acumulado de todos os meses deste espaço — não é o do mês atual.
              </p>
            </div>

            <CounterpartyList
              debts={typedDebts}
              currentUserId={user?.id}
              members={members}
              canWrite={canWrite}
              currency={baseCurrency}
              onSettle={openSettlement}
            />
          </section>

          <section className="space-y-2">
            <div className="space-y-0.5">
              <h2 className="text-base font-semibold text-foreground">
                {/* Saldo zero com meses abertos é um estado real: devo maio e
                    tenho junho a receber. Chamar aquilo de "origem do saldo"
                    quando o saldo é zero seria uma frase sem referente.
                    Sem resposta (`origem` nulo) o título NÃO cai nesse ramo: o
                    `?? 0` diria "meses ainda não fechados" sobre uma falha de
                    rede, afirmando algo que ninguém verificou. */}
                {origem && Number(origem.balance) === 0
                  ? 'Meses ainda não fechados'
                  : 'De onde vem esse saldo'}
              </h2>
              <p className="text-sm text-muted-foreground">
                Cada mês se acerta sozinho. Toque num deles para ver o detalhe.
              </p>
            </div>
            {origemLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : origemError || !origem ? (
              /* ERR-001. Sem esta resposta a quebra sumiria da tela, e o
                 acumulado voltaria a ser um número sem origem — exatamente o
                 estado que este bloco existe para acabar. Pior que a tela
                 antiga: lá a ausência era o normal, aqui ela parece "não vem de
                 mês nenhum". */
              <ErrorState
                title="Não foi possível abrir a origem do saldo."
                message="O total acima continua correto; o que falhou foi a quebra mês a mês."
                onRetry={() => refetchOrigem()}
              />
            ) : (
              <BalanceOrigin origem={origem} currency={baseCurrency} onOpenMonth={abrirMes} />
            )}
          </section>

          {otherDebts.length > 0 && (
            <details className="group rounded-xl border border-border">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
                <Users className="h-4 w-4 shrink-0 text-muted-foreground" />
                Entre outras pessoas
                <span className="font-normal text-muted-foreground">({otherDebts.length})</span>
              </summary>
              <div className="border-t border-border">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      <TableHead className="text-xs font-semibold text-muted-foreground">Devedor</TableHead>
                      <TableHead className="w-12 text-center" />
                      <TableHead className="text-xs font-semibold text-muted-foreground">Credor</TableHead>
                      <TableHead className="text-right text-xs font-semibold text-muted-foreground">Valor</TableHead>
                      <TableHead className="w-32" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {otherDebts.map((debt) => (
                      <TableRow key={`${debt.debtor_id}-${debt.creditor_id}`} className="border-border hover:bg-accent/30">
                        <TableCell className="font-bold">{memberName(debt.debtor_id)}</TableCell>
                        <TableCell className="text-center">
                          <ArrowRight className="inline h-4 w-4 text-muted-foreground" />
                        </TableCell>
                        <TableCell className="font-bold">{memberName(debt.creditor_id)}</TableCell>
                        <TableCell className="whitespace-nowrap text-right font-semibold">{formatBRL(debt.amount)}</TableCell>
                        <TableCell className="text-right">
                          <Button size="sm" variant="ghost" disabled={!canWrite} onClick={() => openSettlement(debt)} className="gap-1.5 font-bold text-primary hover:bg-primary/10">
                            <HandCoins className="h-3.5 w-3.5" /> Registrar
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </details>
          )}

          <div className="flex items-start gap-4 rounded-2xl border border-primary/10 bg-primary/5 p-6">
            <div className="rounded-xl bg-primary/10 p-2">
              <Landmark className="h-6 w-6 text-primary" />
            </div>
            <div className="space-y-1">
              <h4 className="font-bold text-foreground">Como os acertos funcionam?</h4>
              <p className="text-sm leading-relaxed text-muted-foreground">
                O sistema calcula quem pagou a mais e quem pagou a menos pelas divisões de cada
                despesa. Faça o pagamento (Pix, dinheiro…) e registre aqui.{' '}
                {/* A distinção que a tela escondia — e que explica o saldo que
                    "cai sozinho" sem nenhum mês fechar. */}
                <strong className="text-foreground">Registrar por um mês</strong> (na aba Por mês)
                fecha aquele mês; <strong className="text-foreground">registrar por aqui</strong>{' '}
                abate o acumulado sem fechar mês nenhum — o histórico marca cada um com o mês dele.
              </p>
            </div>
          </div>
        </TabsContent>

        {/* --- Por mês: o retrato de um mês --------------------------------- */}
        <TabsContent value="mes" className="space-y-4">
          <MonthNavigator month={month} onChange={setMonth} />
          <MonthlyDebtsSection
            month={month}
            members={members}
            currentUserId={user?.id}
            canWrite={canWrite}
            onSettle={(d) => {
              setDraft(d);
              setDialogOpen(true);
            }}
            onOpenHistory={() => setAba('historico')}
          />
        </TabsContent>

        {/* --- Histórico: o único lugar que lista os acertos ---------------- */}
        <TabsContent value="historico">
          <Card className="bg-card border-border">
            <CardHeader>
              <CardTitle className="text-lg">Histórico de acertos</CardTitle>
              <CardDescription>
                Pagamentos já registrados neste espaço — desfaça um acerto para devolvê-lo ao
                balanço. A pílula diz qual mês cada um fecha.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {/* Enquanto carrega, a lista vazia diria "nenhum acerto
                  registrado ainda" — uma afirmação sobre dados que ainda não
                  chegaram. A tela global já fazia isso certo. */}
              {histLoading ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-10" />
                  ))}
                </div>
              ) : (
                <SettlementHistory rows={historico} whoLabel="Acerto" />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <SettlementDialog open={dialogOpen} onOpenChange={setDialogOpen} draft={draft} members={members} />
    </div>
  );
}
