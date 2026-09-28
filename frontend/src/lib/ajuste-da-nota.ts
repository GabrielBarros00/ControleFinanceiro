/*
 * O ajuste da nota: desconto, frete, taxa… — a diferença entre a soma dos itens
 * e o total pago (`TransactionAdjustment`).
 *
 * O sinal vem do TIPO, como no backend (`TransactionAdjustmentCreate`) e no MCP
 * (`AdjustmentIn.signed`): desconto e cashback reduzem; taxa, gorjeta e frete
 * aumentam; arredondamento e "outro" vão para qualquer lado, e aí quem diz é a
 * pessoa. Na tela o valor é digitado sem sinal — o campo de dinheiro não aceita
 * "-" — e o sinal é posto aqui, na fronteira.
 */
import type { AdjustmentType } from '@/types/transaction';

export const TIPOS_DE_AJUSTE = [
  'discount', 'shipping', 'tax', 'tip', 'cashback', 'rounding', 'other',
] as const satisfies readonly AdjustmentType[];

export const AJUSTE_ROTULO: Record<AdjustmentType, string> = {
  discount: 'Desconto',
  tax: 'Taxa/Imposto',
  tip: 'Gorjeta',
  shipping: 'Frete',
  cashback: 'Cashback',
  rounding: 'Arredondamento',
  other: 'Ajuste',
};

const REDUZEM: ReadonlySet<AdjustmentType> = new Set(['discount', 'cashback']);
const AUMENTAM: ReadonlySet<AdjustmentType> = new Set(['tax', 'tip', 'shipping']);

/** O tipo já diz o sinal? Só arredondamento e "outro" perguntam à pessoa. */
export function sinalLivre(tipo: AdjustmentType): boolean {
  return !REDUZEM.has(tipo) && !AUMENTAM.has(tipo);
}

/** O valor com sinal, como a API grava: negativo reduz o total. */
export function ajusteComSinal(tipo: AdjustmentType, valor: number, reduz: boolean): number {
  const reduzOTotal = REDUZEM.has(tipo) || (sinalLivre(tipo) && reduz);
  return reduzOTotal ? -Math.abs(valor) : Math.abs(valor);
}
