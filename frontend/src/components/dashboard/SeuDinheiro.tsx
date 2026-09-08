import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';

import { MoneyText } from '@/components/money/MoneyText';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { formatMoney } from '@/lib/money';
import { useBalance } from '@/hooks/use-balance';

/**
 * "Quanto eu tenho" — e, numa frase, "quanto sobra se eu pagar o mês".
 *
 * ## O que mudou, e por quê
 *
 * A versão anterior (`SaldoEProjecao`) gastava duas seções e sete blocos no
 * mesmo assunto: um quadro "Seu dinheiro" com o total e a lista de contas, e
 * outro "Até o fim do mês" com quatro tiles — *Saldo atual*, *A receber*, *A
 * pagar*, *Saldo projetado* — mais o detalhamento. O saldo aparecia **três
 * vezes** na mesma tela: no total, no tile "Saldo atual" e dentro do projetado.
 *
 * Nenhum dos números estava errado. O problema era a proporção: sete blocos para
 * responder uma pergunta que cabe em duas frases, ocupando a metade superior da
 * primeira tela do app.
 *
 * Aqui sobrou o que responde:
 *
 * - o **saldo**, grande, porque é a pergunta;
 * - a **projeção**, em uma linha, porque é a consequência dela;
 * - um link para **Contas**, porque "em quais contas" é a pergunta seguinte —
 *   e ela tem uma tela inteira, com extrato por conta.
 *
 * O que saiu daqui **não sumiu**: "a pagar" com prazo curto virou o bloco
 * "Precisa de você", logo abaixo e com ação; o detalhamento da projeção continua
 * em Contas a pagar; a lista de contas está em `/me/accounts`.
 *
 * ## O que NÃO mudou (e não pode mudar)
 *
 * Saldo ausente nunca vira zero. "Você não tem dinheiro" e "eu não sei quanto
 * você tem" são coisas diferentes, e a segunda pede o número em vez de inventar
 * um. Vale igual para a projeção, que depende do saldo.
 */
export function SeuDinheiro({ month }: { month: string }) {
  const { balance, isLoading, isError, refetch } = useBalance(month);

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  /*
   * O erro é DITO, não escondido (ERR-001). Havia aqui um `return null` com a
   * justificativa de que "o resto da tela continua útil"; o efeito era o bloco
   * mais importante do app desaparecer sem aviso e sem como tentar de novo.
   */
  if (isError) {
    return (
      <ErrorState
        message="Não foi possível carregar o seu saldo e a previsão do mês."
        onRetry={refetch}
      />
    );
  }
  if (!balance) return null;

  const moeda = balance.currency;
  const semSaldo = balance.total === null || balance.total === undefined;
  const projetado = balance.projected_balance;

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">Seu dinheiro</p>
          {semSaldo ? (
            <p className="mt-1 text-xl text-muted-foreground" aria-label="Saldo ainda não informado">
              —
            </p>
          ) : (
            <MoneyText
              value={balance.total as string}
              currency={moeda}
              className="mt-0.5 block text-3xl font-semibold"
            />
          )}
        </div>
        <Link
          to="/me/accounts"
          className="flex shrink-0 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Contas <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {semSaldo ? (
        <div className="mt-3 rounded-lg bg-muted p-3 text-sm">
          <p className="font-medium">Saldo ainda não configurado</p>
          <p className="mt-1 text-muted-foreground">
            Informe quanto há em cada conta e em que dia. Só a partir dessa data os
            movimentos passam a contar — o que veio antes já está dentro do número
            que você informar.
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
          {/* A projeção em UMA frase. Ela é a consequência do saldo, não um
              segundo assunto — e como frase ela diz o que quatro tiles não
              diziam: o que aquele número significa para o fim do mês. */}
          {projetado !== null && projetado !== undefined && (
            <p className="mt-2 text-sm text-muted-foreground">
              Pagando o que vence até o fim do mês, fica com{' '}
              <strong className={`font-semibold ${Number(projetado) >= 0 ? 'text-foreground' : 'text-expense'}`}>
                {formatMoney(Number(projetado), { currency: moeda })}
              </strong>
              .
            </p>
          )}
          {(balance.accounts_without_opening ?? 0) > 0 && (
            <p className="mt-1 text-xs text-muted-foreground">
              {balance.accounts_without_opening} conta(s) sem saldo configurado ficam de
              fora deste total.
            </p>
          )}
        </>
      )}
    </section>
  );
}
