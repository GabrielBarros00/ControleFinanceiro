import * as React from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CalendarClock, Check, CheckCircle2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { formatMoney } from '@/lib/money';
import { parseApiDay } from '@/lib/date';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';
import { useMyPayables, useSettlePayables, type PayableEntry } from '@/hooks/use-payables';
import type { BalanceRead } from '@/hooks/use-balance';

/**
 * "Precisa de você" — o único bloco da primeira tela que pede uma ação.
 *
 * ## O problema que ele resolve
 *
 * A primeira tela tinha seis blocos, catorze números e **nenhum botão**. Ela
 * descrevia a situação com precisão e não oferecia saída nenhuma: para pagar
 * uma conta que vence amanhã, a pessoa lia o resumo, entendia que devia algo, e
 * então tinha de sair procurando em qual das quatro telas de dívida aquilo
 * mora. Um painel que informa sem permitir agir transfere o trabalho para quem
 * já chegou pedindo ajuda.
 *
 * ## O recorte
 *
 * Só o que tem **prazo curto**: o que já venceu e o que vence nos próximos sete
 * dias. Não é "tudo o que devo" — isso é a tela de Contas a pagar, e repeti-la
 * aqui seria trocar um resumo longo por outro. Sete dias porque é o horizonte
 * em que ainda dá para fazer alguma coisa a respeito.
 *
 * ## Quando não há nada
 *
 * O bloco **não some**: ele diz "tudo em dia". A ausência de aviso é ambígua —
 * pode significar que não há nada ou que a tela não carregou —, e a diferença
 * entre as duas é justamente o que deixa alguém tranquilo ou desconfiado.
 */
const DIAS_DE_HORIZONTE = 7;

/** Fatura e financiamento não são "conta a pagar" (ADR 0029) e vêm da projeção. */
const COMPROMISSOS: Record<string, { rotulo: string; para: string }> = {
  statement: { rotulo: 'Faturas de cartão', para: '/me/cards' },
  financing: { rotulo: 'Parcelas de financiamento', para: '/me/commitments' },
};

function diasAte(iso: string): number {
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const alvo = parseApiDay(iso);
  alvo.setHours(0, 0, 0, 0);
  return Math.round((alvo.getTime() - hoje.getTime()) / 86_400_000);
}

/** "venceu há 3 dias", "vence hoje", "vence em 2 dias" — nunca uma data ISO. */
function prazo(iso: string): string {
  const dias = diasAte(iso);
  if (dias === 0) return 'vence hoje';
  if (dias === 1) return 'vence amanhã';
  if (dias > 1) return `vence em ${dias} dias`;
  if (dias === -1) return 'venceu ontem';
  return `venceu há ${Math.abs(dias)} dias`;
}

function LinhaDeConta(
  { conta, moeda, onPagar, pagando }:
  { conta: PayableEntry; moeda: string; onPagar: () => void; pagando: boolean },
) {
  const vencida = conta.is_overdue;
  return (
    <li className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{conta.title}</p>
        <p className="text-xs text-muted-foreground">
          <span className={vencida ? 'font-semibold text-expense' : undefined}>
            {prazo(conta.due_date)}
          </span>
          {' · '}
          {conta.workspace_name}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="tabular text-sm text-foreground">
          {formatMoney(Number(conta.converted_amount ?? conta.amount), { currency: moeda })}
        </span>
        {/* A ação mora NA LINHA: é ela que a pessoa veio resolver, e mandá-la
            para outra tela para clicar de novo é o passo que faz desistir. */}
        <Button
          size="sm"
          variant="outline"
          className="h-8 gap-1.5 px-2.5"
          disabled={pagando}
          onClick={onPagar}
          aria-label={`Marcar "${conta.title}" como paga`}
        >
          <Check className="h-3.5 w-3.5" /> Pagar
        </Button>
      </div>
    </li>
  );
}

export function PrecisaDeVoce({ month, balance }: { month: string; balance?: BalanceRead | null }) {
  const { payables, isLoading } = useMyPayables(month);
  const { settle, isSettling } = useSettlePayables();
  const [pagandoId, setPagandoId] = React.useState<number | null>(null);

  const moeda = payables?.currency ?? balance?.currency ?? 'BRL';
  const atrasado = Number(balance?.overdue_total ?? 0);

  /* O que é urgente: vencido, ou vencendo dentro do horizonte. `upcoming` traz
     o que vence até o fim do mês SEGUINTE, e a maior parte dele não é urgente —
     por isso os dois passam pelo mesmo filtro de dias. */
  const urgentes = React.useMemo(() => {
    const todas = [...(payables?.entries ?? []), ...(payables?.upcoming ?? [])];
    return todas
      .filter((e) => diasAte(e.due_date) <= DIAS_DE_HORIZONTE)
      .sort((a, b) => a.due_date.localeCompare(b.due_date))
      .slice(0, 5);
  }, [payables]);

  /* Fatura e parcela de financiamento não são "conta a pagar": elas não têm
     liquidação própria (quem se paga é a fatura) e vêm do detalhamento da
     projeção. Entram como aviso com caminho, não com botão — pagar uma fatura
     exige escolher a conta e o valor, que é uma decisão, não um toque. */
  const compromissos = (balance?.breakdown ?? [])
    .filter((l) => l.kind in COMPROMISSOS && Number(l.amount) > 0);

  const pagar = async (conta: PayableEntry) => {
    setPagandoId(conta.transaction_id);
    try {
      await settle({
        workspaceId: conta.workspace_id,
        transactionIds: [conta.transaction_id],
        settled: true,
      });
      toast.success(`"${conta.title}" marcada como paga.`);
    } catch (erro) {
      toast.error(getApiErrorMessage(erro, 'Não foi possível marcar como paga.'));
    } finally {
      setPagandoId(null);
    }
  };

  if (isLoading) return <Skeleton className="h-32 w-full" />;

  const temAlgo = atrasado > 0 || urgentes.length > 0 || compromissos.length > 0;

  return (
    <section className="rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-foreground">Precisa de você</h2>
        {temAlgo && (
          <Link
            to="/me/payables"
            className="shrink-0 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Ver tudo
          </Link>
        )}
      </div>

      {!temAlgo ? (
        /* O silêncio informado: "não há avisos" e "não carregou" se parecem
           demais para deixar a ausência falar sozinha. */
        <div className="flex items-center gap-3 px-4 py-5">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-income" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-foreground">Tudo em dia</p>
            <p className="text-xs text-muted-foreground">
              Nada vencido e nada vencendo nos próximos {DIAS_DE_HORIZONTE} dias.
            </p>
          </div>
        </div>
      ) : (
        <>
          {atrasado > 0 && (
            <Link
              to="/me/payables"
              className="flex items-center justify-between gap-3 border-b border-border bg-warning-subtle px-4 py-3 transition-colors hover:bg-warning-subtle/70"
            >
              <span className="flex min-w-0 items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-foreground">
                    {formatMoney(atrasado, { currency: moeda })} já venceu e continua em aberto
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    Fora da previsão do mês, porque não é deste mês. Toque para resolver.
                  </span>
                </span>
              </span>
              <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            </Link>
          )}

          {urgentes.length > 0 && (
            <ul className="divide-y divide-border" aria-label="Contas com prazo curto">
              {urgentes.map((conta) => (
                <LinhaDeConta
                  key={`${conta.workspace_id}-${conta.transaction_id}`}
                  conta={conta}
                  moeda={moeda}
                  pagando={isSettling && pagandoId === conta.transaction_id}
                  onPagar={() => pagar(conta)}
                />
              ))}
            </ul>
          )}

          {compromissos.map((linha) => (
            <Link
              key={linha.kind}
              to={COMPROMISSOS[linha.kind].para}
              className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm hover:bg-muted/50"
            >
              <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                <CalendarClock className="h-4 w-4 shrink-0" aria-hidden="true" />
                {COMPROMISSOS[linha.kind].rotulo}
                {linha.count > 0 && <span className="text-xs">({linha.count})</span>}
              </span>
              <span className="flex shrink-0 items-center gap-1.5 tabular text-foreground">
                {formatMoney(Number(linha.amount), { currency: moeda })}
                <ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              </span>
            </Link>
          ))}
        </>
      )}
    </section>
  );
}
