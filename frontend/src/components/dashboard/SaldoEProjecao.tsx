import { Link } from 'react-router-dom';
import { ArrowDownLeft, ArrowUpRight, PiggyBank, Wallet } from 'lucide-react';

import { MoneyText } from '@/components/money/MoneyText';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile } from '@/components/ui/stat-tile';
import { formatMoney } from '@/lib/money';
import { useBalance } from '@/hooks/use-balance';

/*
 * "Quanto eu tenho" e "quanto vou ter" (ADR 0034) — as duas perguntas que o app
 * não respondia.
 *
 * Dois quadros e não um, porque são eixos diferentes: **saldo** é um estoque que
 * atravessa os meses sem reset, e **projeção** é uma pergunta sobre um mês. Somar
 * os dois num quadro só reintroduziria a confusão que esta onda existe para
 * desfazer — o app já chamou de "Seu saldo" um número que era renda − consumo.
 *
 * Falha ou ausência de saldo NUNCA vira zero: conta sem saldo inicial mostra o
 * convite para informá-lo, e a projeção fica vazia em vez de inventar um número a
 * partir de um saldo que ninguém declarou.
 */
/** O tile de um número que o app NÃO SABE — e diz isso, em vez de dizer zero.
 *
 * Mesma moldura do `StatTile` para a grade não desalinhar; o que muda é que o
 * lugar do número traz um travessão. "R$ 0,00" ali seria uma resposta, e uma
 * resposta falsa: a diferença entre "você não tem dinheiro" e "eu não sei quanto
 * você tem" é exatamente o que esta onda existe para preservar.
 */
function TileDesconhecido({ label, hint }: { label: string; hint: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card p-3 sm:p-4">
      <p className="min-w-0 text-xs text-muted-foreground sm:text-sm">{label}</p>
      <p className="mt-1 text-xl text-muted-foreground sm:text-2xl" aria-label={hint}>
        —
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

export function SaldoEProjecao({ month }: { month: string }) {
  const { balance, isLoading, isError } = useBalance(month);

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  // Silencioso no erro: o resto do Seu mês continua útil, e um segundo bloco de
  // erro na mesma tela empurraria o conteúdo para baixo sem acrescentar ação.
  if (isError || !balance) return null;

  const moeda = balance.currency;
  const n = (v: unknown) => Number(v ?? 0);
  const semSaldo = balance.total === null || balance.total === undefined;
  const projetado = balance.projected_balance;

  return (
    <div className="space-y-4">
      {/* --- Seu dinheiro (saldo) ---------------------------------------- */}
      <section className="rounded-xl border border-border bg-card">
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-foreground">Seu dinheiro</h2>
            <p className="text-sm text-muted-foreground">
              O que existe agora nas suas contas. Não muda na virada do mês.
            </p>
          </div>
          <Link
            to="/me/accounts"
            className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Contas
          </Link>
        </div>

        <div className="p-4">
          {semSaldo ? (
            <div className="rounded-lg bg-muted p-3 text-sm">
              <p className="font-medium">Saldo ainda não configurado</p>
              <p className="mt-1 text-muted-foreground">
                Informe quanto há em cada conta e em que dia. Só a partir dessa data
                os movimentos passam a contar — o que veio antes já está dentro do
                número que você informar.
              </p>
              <Link
                to="/me/accounts"
                className="mt-2 inline-block font-medium text-primary underline-offset-4 hover:underline"
              >
                Informar saldo das contas →
              </Link>
            </div>
          ) : (
            <>
              <MoneyText
                value={balance.total as string}
                currency={moeda}
                className="block text-2xl font-semibold sm:text-3xl"
              />
              {/* Por conta: "onde está o meu dinheiro" é uma pergunta própria
                  (§43.2), e um total sozinho não a responde. */}
              <dl className="mt-3 divide-y divide-border">
                {balance.accounts
                  .filter((c) => c.balance !== null && c.balance !== undefined)
                  .map((conta) => (
                    <div
                      key={conta.account_id}
                      className="flex items-center justify-between gap-3 py-1.5"
                    >
                      <dt className="min-w-0 truncate text-sm text-muted-foreground">
                        {conta.name}
                      </dt>
                      <dd className="tabular shrink-0 text-sm">
                        {formatMoney(Number(conta.balance), { currency: conta.currency })}
                      </dd>
                    </div>
                  ))}
              </dl>
              {(balance.accounts_without_opening ?? 0) > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {balance.accounts_without_opening} conta(s) sem saldo configurado
                  ficam de fora deste total.
                </p>
              )}
            </>
          )}
        </div>
      </section>

      {/* --- Até o fim do mês (previsão) ---------------------------------- */}
      <section className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-base font-semibold text-foreground">Até o fim do mês</h2>
          <p className="text-sm text-muted-foreground">
            O saldo de hoje mais o que se sabe que ainda entra e sai — contas a
            pagar, faturas que vencem no mês e parcelas de financiamento.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 p-4 sm:gap-4 lg:grid-cols-4">
          {/* Sem saldo configurado o número é DESCONHECIDO, não zero. Um "R$ 0,00"
              aqui — logo abaixo de "saldo ainda não configurado" — é um valor
              errado com a mesma cara de um certo, que é o defeito que esta onda
              inteira existe para não cometer. */}
          {semSaldo ? (
            <TileDesconhecido label="Saldo atual" hint="Informe o saldo das contas" />
          ) : (
            <StatTile
              label="Saldo atual"
              value={balance.total as string}
              kind="neutral"
              icon={Wallet}
              currency={moeda}
            />
          )}
          <StatTile
            label="A receber"
            value={n(balance.receivable_total)}
            kind="income"
            icon={ArrowDownLeft}
            currency={moeda}
            hint="Rendas previstas ainda não recebidas"
          />
          <StatTile
            label="A pagar"
            value={n(balance.payable_total)}
            kind="expense"
            icon={ArrowUpRight}
            currency={moeda}
            hint="Obrigações conhecidas até o fim do mês"
          />
          {projetado === null || projetado === undefined ? (
            <TileDesconhecido
              label="Saldo projetado"
              hint="Depende do saldo atual"
            />
          ) : (
            <StatTile
              label="Saldo projetado"
              value={projetado}
              kind={n(projetado) >= 0 ? 'income' : 'expense'}
              icon={PiggyBank}
              currency={moeda}
              hint="Saldo atual + a receber − a pagar"
            />
          )}
        </div>

        {/* De onde vem "a pagar". Sem o detalhe, um total desses não é
            conferível — a pessoa não teria como saber se a fatura entrou. */}
        {balance.breakdown.length > 0 && (
          <dl className="divide-y divide-border border-t border-border px-4 pb-3">
            {balance.breakdown.map((linha) => (
              <div
                key={linha.kind}
                className="flex items-center justify-between gap-3 py-2"
              >
                <dt className="min-w-0 truncate text-sm text-muted-foreground">
                  {linha.label}
                  {linha.count > 0 && (
                    <span className="ml-1 text-xs">({linha.count})</span>
                  )}
                </dt>
                <dd className="tabular shrink-0 text-sm">
                  {formatMoney(
                    linha.kind === 'income'
                      ? Number(linha.amount)
                      : -Number(linha.amount),
                    { sign: true, currency: moeda },
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
    </div>
  );
}
