import { daysUntil, parseApiDay } from '@/lib/date';
import { formatMoney } from '@/lib/money';

/*
 * Regra ÚNICA de "o que avisar sobre esta fatura".
 *
 * Existe porque o aviso aparece em dois lugares com formatos diferentes — o
 * selo compacto no cartão (CreditCardVisual) e a faixa na tela da fatura
 * (StatementView) — e eles não podem discordar: cartão dizendo "vence em 3
 * dias" e a fatura dizendo "fechada" seria a mesma dívida com dois estados.
 */

export type StatementAlertTone = 'danger' | 'warning' | 'info' | 'success';

export interface StatementAlertInput {
  status: 'open' | 'closed' | 'paid' | 'overdue';
  due_date: string;
  closing_date: string;
  /** total da fatura; 0 não gera aviso (fatura vazia é ruído) */
  amount: number;
  is_overdue?: boolean;
}

export interface StatementAlert {
  tone: StatementAlertTone;
  /** frase curta para o selo do cartão */
  short: string;
  /** título da faixa na tela da fatura */
  title: string;
  /** complemento com data e valor */
  detail: string;
}

/** Janela em que "vence logo" vira aviso âmbar (dá tempo de agendar o pagamento). */
const AVISO_VENCIMENTO_DIAS = 5;
/** Janela em que "vai fechar" vira aviso informativo. */
const AVISO_FECHAMENTO_DIAS = 3;

const dia = (iso: string) => parseApiDay(iso).toLocaleDateString('pt-BR');
/** dd/mm — o selo do cartão é estreito, o ano não cabe nem acrescenta nada. */
const diaCurto = (iso: string) =>
  parseApiDay(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });

function emDias(n: number): string {
  if (n === 0) return 'hoje';
  if (n === 1) return 'amanhã';
  return `em ${n} dias`;
}

/** `null` = nada a avisar (fatura aberta e longe do fechamento, ou zerada). */
export function statementAlert(
  stmt: StatementAlertInput,
  currency?: string,
): StatementAlert | null {
  const valor = formatMoney(stmt.amount, { currency });

  if (stmt.status === 'paid') {
    return {
      tone: 'success',
      short: 'Fatura paga',
      title: 'Fatura paga',
      detail: `${valor} quitados — o limite já voltou.`,
    };
  }

  // Fatura sem valor não vira alerta: o ciclo corrente é materializado mesmo sem
  // compras, e avisar sobre R$ 0,00 treinaria o usuário a ignorar os avisos.
  if (stmt.amount <= 0) return null;

  const paraVencer = daysUntil(stmt.due_date);

  if (stmt.is_overdue || paraVencer < 0) {
    const atraso = Math.abs(paraVencer);
    return {
      tone: 'danger',
      short: 'Fatura vencida',
      title: 'Fatura vencida e não paga',
      detail: `Venceu em ${dia(stmt.due_date)} (${atraso === 1 ? 'há 1 dia' : `há ${atraso} dias`}) com ${valor} em aberto.`,
    };
  }

  if (stmt.status === 'closed') {
    const proximo = paraVencer <= AVISO_VENCIMENTO_DIAS;
    return {
      tone: proximo ? 'warning' : 'info',
      short: proximo ? `Vence ${emDias(paraVencer)}` : `Fechada · vence ${diaCurto(stmt.due_date)}`,
      title: 'Fatura fechada e ainda não paga',
      detail: `${valor} vencendo ${emDias(paraVencer)} (${dia(stmt.due_date)}).`,
    };
  }

  // Aberta: só avisa quando o fechamento está logo ali — depois dele a compra
  // já cai na fatura seguinte, e é útil saber disso antes de comprar.
  const paraFechar = daysUntil(stmt.closing_date);
  if (paraFechar >= 0 && paraFechar <= AVISO_FECHAMENTO_DIAS) {
    return {
      tone: 'info',
      short: `Fecha ${emDias(paraFechar)}`,
      title: `Fatura fecha ${emDias(paraFechar)}`,
      detail: `${valor} até agora — compras depois de ${dia(stmt.closing_date)} entram na próxima fatura.`,
    };
  }

  return null;
}
