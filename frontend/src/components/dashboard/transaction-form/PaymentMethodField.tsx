import * as React from 'react';
import { useFormContext } from 'react-hook-form';
import { CalendarClock } from 'lucide-react';
import { Label } from '@/components/ui/label';
import {
  naJanelaDeFechamento,
  useCreditCards,
  useStatementTarget,
} from '@/hooks/use-credit-cards';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { parseApiDay } from '@/lib/date';
import { formatCurrency } from '@/lib/money';
import { PAYMENT_METHOD_OPTIONS } from '@/lib/payment-methods';
import type { TransactionFormValues } from './schema';
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';

interface PaymentMethodFieldProps {
  allowInstallments?: boolean;
}

export function PaymentMethodField({ allowInstallments = false }: PaymentMethodFieldProps) {
  const { register, watch, setValue, getValues, trigger, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { cards } = useCreditCards();
  const { activeAccounts } = usePaymentAccounts();
  const paymentMethod = watch('payment_method');
  const creditCardId = watch('credit_card_id');
  const totalAmount = watch('total_amount');
  const transactionDate = watch('transaction_date');
  const singlePayer = (watch('payers') ?? []).length <= 1;

  // Revalida cruzado: escolher o cartão limpa na hora o erro "selecione o cartão"
  // (que pode ter sido disparado pela origem de um pagador). Corrige o caso em
  // que a mensagem ficava presa mesmo após preencher a Forma de pagamento.
  React.useEffect(() => {
    trigger(['credit_card_id', 'payers']);
  }, [creditCardId, trigger]);

  // Trocar de crédito para outro método descarta o cartão — o backend rejeita
  // (com razão) pix/dinheiro com credit_card_id preenchido — e volta à vista
  React.useEffect(() => {
    if (paymentMethod !== 'credit_card') {
      if (getValues('credit_card_id')) setValue('credit_card_id', '');
      if (getValues('installments') > 1) setValue('installments', 1);
    } else if (getValues('payers.0.account_id')) {
      // Crédito não sai de conta: limpa a origem do pagador único
      setValue('payers.0.account_id', '');
    }
  }, [paymentMethod, getValues, setValue]);

  return (
    <div className="space-y-2">
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
      <div className="space-y-2">
        <Label htmlFor="payment_method" className="text-sm font-semibold text-foreground">Forma de pagamento</Label>
        <select id="payment_method" className={selectClass} {...register('payment_method')}>
          <option value="" className="bg-card">Não informado</option>
          {PAYMENT_METHOD_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value} className="bg-card">{opt.label}</option>
          ))}
        </select>
      </div>
      {paymentMethod && paymentMethod !== 'credit_card' && singlePayer && activeAccounts.length > 0 && (
        <div className="space-y-2">
          <Label htmlFor="payer_account_id" className="text-sm font-semibold text-foreground">
            De qual conta? <span className="font-normal text-muted-foreground">(opcional)</span>
          </Label>
          <select id="payer_account_id" className={selectClass} {...register('payers.0.account_id')}>
            <option value="" className="bg-card">Não informado</option>
            {activeAccounts.map((a) => (
              <option key={a.id} value={a.id} className="bg-card">{a.name}</option>
            ))}
          </select>
        </div>
      )}
      {paymentMethod === 'credit_card' && (
        <div className="space-y-2">
          <Label htmlFor="credit_card_id" className="text-sm font-semibold text-foreground">Qual cartão?</Label>
          <select id="credit_card_id" className={selectClass} {...register('credit_card_id')}>
            <option value="" className="bg-card">Selecione...</option>
            {cards.map((card: { id: number; name: string }) => (
              <option key={card.id} value={card.id} className="bg-card">{card.name}</option>
            ))}
          </select>
          {errors.credit_card_id && (
            <p className="text-xs text-destructive font-medium">{errors.credit_card_id.message as string}</p>
          )}
        </div>
      )}
      {paymentMethod === 'credit_card' && allowInstallments && (
        <div className="space-y-2">
          <Label htmlFor="installments" className="text-sm font-semibold text-foreground">Parcelas</Label>
          <select
            id="installments"
            className={selectClass}
            {...register('installments', { valueAsNumber: true })}
          >
            <option value={1} className="bg-card">À vista</option>
            {Array.from({ length: 23 }, (_, i) => i + 2).map((n) => (
              <option key={n} value={n} className="bg-card">
                {n}x de {formatCurrency((totalAmount || 0) / n)}
              </option>
            ))}
          </select>
          {errors.installments && (
            <p className="text-xs text-destructive font-medium">{errors.installments.message as string}</p>
          )}
        </div>
      )}
    </div>
    <StatementTargetHint cardId={creditCardId} date={transactionDate} />
    </div>
  );
}

/**
 * "Vai para a fatura de Agosto/2026 (vence 10/09)", mais o aviso e a correção.
 *
 * A fatura é derivada no SERVIDOR (ADR 0002) por uma regra que o formulário não
 * contava: a partir do dia de fechamento a compra vai para o mês SEGUINTE, e se
 * aquela fatura já estiver fechada ela rola para frente. O usuário só descobria
 * o destino depois de salvar — e "por que minha compra de hoje está na fatura de
 * setembro?" não tinha resposta em lugar nenhum da tela.
 *
 * Na janela de fechamento entra a segunda frase (ADR 0032): a fatura real é
 * composta pela data em que o EMISSOR processa a compra, então perto do
 * fechamento ela pode escorregar para o ciclo seguinte. É o único momento em que
 * dá para avisar ANTES do fato.
 *
 * **Sem cor de alerta, de propósito.** O que está sendo dito é uma
 * probabilidade, não um erro: a maioria das compras nesta janela cai onde a
 * regra diz. Gastar o vocabulário visual de alerta com algo que costuma estar
 * certo estragaria o alerta de verdade nas outras telas.
 */
function StatementTargetHint({
  cardId,
  date,
}: {
  cardId?: string | number | null;
  date?: string | null;
}) {
  const { watch, setValue } = useFormContext<TransactionFormValues>();
  const shift = watch('statement_shift') ?? 0;
  const id = cardId ? Number(cardId) : null;
  const { target } = useStatementTarget(id, date || null, shift);

  // Trocar de cartão ou de data pode tornar o deslocamento sem sentido (a
  // fatura de destino do cartão novo já está fechada, por exemplo). Voltar ao
  // natural é mais honesto que carregar um valor que o backend vai recusar com
  // um 409 que a pessoa não relacionaria com a troca de cartão.
  React.useEffect(() => {
    if (!id) setValue('statement_shift', 0);
  }, [id, setValue]);

  if (!target) return null;

  // parseApiDay: closing_date/due_date são DIAS de calendário serializados como
  // datetime à meia-noite — parseApiDate os atrasaria em um dia em fuso negativo.
  const vencimento = parseApiDay(target.due_date).toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
  });
  const avisar = naJanelaDeFechamento(target);
  const seguinte = target.options.find((o) => o.shift === shift + 1);

  return (
    <div className="space-y-1.5" data-testid="statement-target-hint">
      <p className="text-xs text-muted-foreground">
        <CalendarClock className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />
        Vai para a fatura de{' '}
        <span className="font-medium text-foreground">{monthLongLabel(target.month)}</span>
        {' '}(vence {vencimento})
        {target.rolled_forward && ' — a fatura do mês da compra já está fechada'}
      </p>

      {avisar && (
        <p className="text-xs text-muted-foreground" data-testid="closing-window-warning">
          {target.days_to_closing === 1
            ? 'Falta 1 dia para o fechamento'
            : `Faltam ${target.days_to_closing} dias para o fechamento`}
          {' '}— se o estabelecimento demorar a processar, o banco pode jogar esta
          compra para a fatura seguinte. Dá para ajustar depois, no lançamento.
        </p>
      )}

      {/* A caixa só aparece na janela (ou quando já está marcada, senão
          desmarcá-la a faria sumir antes de o efeito surtir). Fora dela seria
          ruído: o deslocamento não tem uso num lançamento no meio do ciclo.

          Ela é para quem SABE — restaurante, hotel, companhia aérea, aquele
          mercado que sempre demora. Não é o conserto do problema: o conserto é
          poder mover a compra depois, quando a fatura real chega e a dúvida
          virou fato. Marcar aqui é palpite, e o rótulo diz isso. */}
      {(avisar || shift > 0) && seguinte && (
        <label className="flex items-start gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-border accent-primary"
            checked={shift > 0}
            onChange={(e) => setValue('statement_shift', e.target.checked ? 1 : 0)}
            disabled={!seguinte.available && shift === 0}
          />
          <span>
            Esta loja costuma demorar — lançar na fatura de{' '}
            <span className="font-medium text-foreground">
              {monthLongLabel(seguinte.month)}
            </span>
            {/* A tranquilizada que faz a caixa ser usável: o medo legítimo de
                marcar isto é "vou tirar o gasto do mês em que ele aconteceu".
                A competência sai da DATA da compra e não se move — é o
                invariante do ADR 0032, dito onde a dúvida aparece. */}
            <span className="block text-[11px] opacity-80">
              A despesa continua sendo de {monthLongLabel(date!.slice(0, 7))}: muda
              a fatura, não o mês do gasto.
            </span>
          </span>
        </label>
      )}
    </div>
  );
}

function monthLongLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  if (!y || !m) return month;
  const rotulo = new Date(y, m - 1, 1).toLocaleDateString('pt-BR', {
    month: 'long',
    year: 'numeric',
  });
  return rotulo.charAt(0).toUpperCase() + rotulo.slice(1);
}
