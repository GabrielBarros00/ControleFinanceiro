import { Link } from 'react-router-dom';
import { ArrowRight, Receipt } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { PeriodPicker } from '@/components/layout/PeriodPicker';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { SeuDinheiro } from '@/components/dashboard/SeuDinheiro';
import { PrecisaDeVoce } from '@/components/dashboard/PrecisaDeVoce';
import { useOverview, useMyActivity } from '@/hooks/use-overview';
import { useBalance } from '@/hooks/use-balance';
import { useAuth } from '@/hooks/use-auth';
import { useMonthParam } from '@/hooks/use-month-param';
import { formatMoney } from '@/lib/money';
import { parseApiDate } from '@/lib/date';

/**
 * A primeira tela: **saldo, pendências, mês, movimentos** — nessa ordem.
 *
 * ## O que ela era
 *
 * Seis blocos, ~14 números e **2.430px de altura** a 390px (medido pelo portão
 * de densidade em `e2e/larguras.spec.ts`), numa conta praticamente vazia. O
 * saldo aparecia três vezes: no quadro "Seu dinheiro", de novo como tile "Saldo
 * atual" logo abaixo, e uma terceira vez dentro do "Saldo projetado". Havia
 * "Resultado do mês" (4 tiles), "Caixa do mês" (3 tiles + detalhamento), "A
 * pagar/A receber", "Por espaço" e "Onde você está envolvido". Nenhum botão.
 *
 * O problema não era nenhum número em particular — todos estavam certos. Era o
 * conjunto: uma pessoa abrindo o app no domingo à noite quer saber *quanto
 * tenho, o que preciso resolver, como está o mês*. As três respostas existiam,
 * espalhadas por quatro seções e catorze valores, e a mais urgente delas
 * (pendências) era a única que não estava ali.
 *
 * ## O que ela é
 *
 *     Hoje
 *     ├── Seu dinheiro ....... um número + "se pagar o que vence, fica com X"
 *     ├── Precisa de você .... vencido e vencendo em 7 dias, COM ação
 *     ├── Este mês ........... uma linha: consumo × renda, com barra
 *     └── Últimos lançamentos  5 linhas + "ver tudo"
 *
 * ## Onde foi parar o que saiu
 *
 * Nada foi apagado — cada número foi para a tela que responde àquela pergunta,
 * e continua a um toque daqui:
 *
 * - **Caixa do mês** (entrou/saiu/saldo + detalhamento) → **Extrato**
 *   (`/me/ledger`), que já mostrava exatamente esses três números no topo, com
 *   as linhas por trás deles. Era duplicata literal.
 * - **Resultado do mês** (renda, consumo, adiantado, resultado) → **Seus
 *   relatórios** (`/me/reports`), onde os mesmos valores viram série histórica.
 *   Aqui sobrou a linha "Este mês", que é a versão de uma frase.
 * - **A pagar / A receber** (acerto entre pessoas) → **Seus acertos**
 *   (`/me/settlements`). É outro eixo: dívida com gente, não com prazo.
 * - **Por espaço** → **Seus acertos** e os relatórios de cada espaço.
 * - **Saldo por conta** → **Contas** (`/me/accounts`), a um link do saldo.
 *
 * As invariantes que os testes desta tela protegiam (competência × caixa,
 * ADR 0022) continuam trancadas onde os números agora moram: no backend
 * (`tests/api/test_visao_global.py`) e em `GlobalLedgerPage.test.tsx`.
 */
export function OverviewPage() {
  const { user } = useAuth();
  // Mês na URL, como no resto do app. Estava fixo em `currentMonthLocal()`: a
  // única tela que soma todos os workspaces não deixava olhar o mês passado, e
  // "como foi meu mês" só valia para o mês corrente.
  const [month, setMonth] = useMonthParam();
  const { overview, isLoading, isError, refetch } = useOverview(month);
  const { balance } = useBalance(month);
  // Cinco, não oito: é uma amostra com caminho para o resto, não uma lista.
  const { activity, isLoading: activityLoading } = useMyActivity(5);

  const firstName = user?.name?.split(' ')[0];
  const n = (v: unknown) => Number(v ?? 0);
  const moeda = overview?.currency ?? 'BRL';
  const fmt = (v: unknown) => formatMoney(n(v), { currency: moeda });

  const renda = n(overview?.income);
  const consumo = n(overview?.consumption);
  // Quanto do que entrou já foi comprometido. Acima de 100% a barra satura, e é
  // justamente aí que a cor precisa mudar: gastar mais do que entrou é o aviso.
  const proporcao = renda > 0 ? Math.min(consumo / renda, 1) : 0;
  const acimaDaRenda = renda > 0 && consumo > renda;

  return (
    <div className="space-y-4">
      {/* "Hoje" e não "Seu mês": a tela responde o agora — quanto tenho, o que
          preciso resolver — e o mês é só o recorte do resumo lá embaixo. O item
          de navegação acompanha, senão o título não bate com o caminho. */}
      <PageHeader
        title="Hoje"
        subtitle={firstName ? `Olá, ${firstName}.` : undefined}
        period={<PeriodPicker value={month} onChange={setMonth} />}
      />

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : isError ? (
        // Sem este ramo, a falha da API virava um mês inteiro de zeros: os
        // números abaixo leem `n(overview?.x)`, que é `Number(undefined ?? 0)`.
        // "Consumo R$ 0,00" é uma resposta, não um erro — e o usuário não teria
        // como saber que ela não foi calculada (regra ERR-001).
        <ErrorState
          message="Não foi possível carregar a sua visão do mês."
          onRetry={() => refetch()}
        />
      ) : (
        <>
          <SeuDinheiro month={month} />

          <PrecisaDeVoce month={month} balance={balance} />

          {/* ESTE MÊS — a competência inteira em uma linha.
              Eram quatro tiles ("Renda", "Consumo", "Adiantado", "Resultado")
              para dizer o que uma frase diz: quanto entrou, quanto da sua parte
              já foi. O resto — a série histórica, a composição por categoria —
              é a pergunta seguinte, e ela tem uma tela. */}
          <section className="rounded-xl border border-border bg-card">
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">Este mês</h2>
              <Link
                to="/me/reports"
                className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                Relatórios
              </Link>
            </div>
            <div className="p-4">
              <p className="text-sm text-foreground">
                Você consumiu{' '}
                <strong className="font-semibold text-expense">{fmt(consumo)}</strong>
                {renda > 0 ? (
                  <> de <strong className="font-semibold text-income">{fmt(renda)}</strong> que entraram.</>
                ) : (
                  <> este mês.</>
                )}
              </p>
              {renda > 0 && (
                <>
                  <div
                    className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-valuenow={Math.round(proporcao * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="Consumo em relação à renda do mês"
                  >
                    <div
                      className={`h-full rounded-full ${acimaDaRenda ? 'bg-expense' : 'bg-brand'}`}
                      style={{ width: `${proporcao * 100}%` }}
                    />
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    {acimaDaRenda
                      ? `Você consumiu ${fmt(consumo - renda)} a mais do que entrou.`
                      : `Sobraram ${fmt(renda - consumo)} de diferença entre renda e consumo.`}
                  </p>
                </>
              )}
            </div>
          </section>

          <ExcludedForeignNotice
            count={overview?.excluded_foreign_count}
            baseCurrency={moeda}
          />

          {/* ÚLTIMOS LANÇAMENTOS — a amostra que confirma que o app está vendo o
              que a pessoa fez. Cinco linhas e um caminho; a lista inteira é o
              Extrato. */}
          <section className="rounded-xl border border-border bg-card">
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold text-foreground">Últimos lançamentos</h2>
              <Link
                to="/me/ledger"
                className="flex shrink-0 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                Ver extrato <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="divide-y divide-border">
              {activityLoading ? (
                <div className="space-y-2 p-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-10" />
                  ))}
                </div>
              ) : activity.length === 0 ? (
                <div className="p-4">
                  <EmptyState
                    icon={Receipt}
                    title="Nada por aqui ainda"
                    description="Lançamentos em que você participa aparecem nesta lista."
                  />
                </div>
              ) : (
                activity.map((t) => (
                  <div key={t.id} className="flex items-center justify-between gap-4 px-4 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{t.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {t.workspace_name} ·{' '}
                        {parseApiDate(t.transaction_date).toLocaleDateString('pt-BR')}
                      </p>
                    </div>
                    {/* A PARTE da pessoa, não o total da despesa. Numa lista do
                        que a pessoa fez, mostrar o valor cheio fazia o jantar de
                        200 rateado 50/50 aparecer como 200 para quem consumiu
                        100. O total vem abaixo, como referência. Sem split
                        (entrou por ter criado ou pago), `my_share` é nulo e só o
                        total faz sentido. */}
                    <div className="shrink-0 text-right">
                      <span className="block text-sm tabular-nums text-foreground">
                        {formatMoney(n(t.my_share ?? t.total_amount), {
                          currency: t.currency,
                        })}
                      </span>
                      {t.my_share != null && n(t.my_share) !== n(t.total_amount) && (
                        <span className="block text-xs tabular-nums text-muted-foreground">
                          de {formatMoney(n(t.total_amount), { currency: t.currency })}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
