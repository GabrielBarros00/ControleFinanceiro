/*
 * A linha da nota: quantidade, unidade, preço unitário e o total impresso (ADR 0040).
 *
 * Réplica de `backend/app/domain/item_da_nota.py` — o teste
 * `__tests__/item-da-nota.test.ts` roda a MESMA tabela de casos do backend e a
 * mesma varredura, para os dois lados nunca discordarem.
 *
 * **Sem ponto flutuante na conta.** A versão anterior fazia
 * `Math.round(qtd * Math.round(unit * 100)) / 100`, e 2,050 × 19,90 dava
 * 4079,4999… → R$ 40,79, que o servidor recusava. Aqui cada número vira inteiro
 * na sua escala (milésimos de quantidade, décimos de milésimo de preço, centavos
 * de total) e o produto é feito em `BigInt`.
 */

export const UNIDADES = ['un', 'kg', 'g', 'l', 'ml', 'm'] as const;
export type Unidade = (typeof UNIDADES)[number];

export const UNIDADE_ROTULO: Record<Unidade, string> = {
  un: 'un', kg: 'kg', g: 'g', l: 'L', ml: 'mL', m: 'm',
};

/** Casas aceitas no preço unitário (o litro custa R$ 5,899). */
export const CASAS_UNITARIO = 4;

// Produto quantidade (milésimos) × unitário (1/10.000) está em 1e-7; um centavo é 1e5 disso.
const UM_CENTAVO = 100_000n;

const escala = (valor: number, casas: number): bigint =>
  BigInt(Math.round((Number.isFinite(valor) ? valor : 0) * 10 ** casas));

/** O total derivado quando a nota não traz o da linha: arredondado ao centavo. */
export function totalDaLinha(quantidade: number, unitario: number): number {
  const produto = escala(quantidade, 3) * escala(unitario, CASAS_UNITARIO);
  return Number((produto + UM_CENTAVO / 2n) / UM_CENTAVO) / 100;
}

/**
 * A linha fecha? O total impresso é a verdade e pode diferir em até 1 centavo do
 * produto EXATO — balanças e caixas arredondam (ou truncam) de jeitos diferentes.
 */
export function linhaFecha(quantidade: number, unitario: number, total: number): boolean {
  const produto = escala(quantidade, 3) * escala(unitario, CASAS_UNITARIO);
  const impresso = escala(total, 2) * UM_CENTAVO;
  const diferenca = produto > impresso ? produto - impresso : impresso - produto;
  return diferenca <= UM_CENTAVO;
}

/** Casas decimais de um número digitado ("5,899" → 3). */
export function casasDecimais(texto: string): number {
  const [, fracao = ''] = texto.replace(',', '.').split('.');
  return fracao.length;
}

/**
 * Os itens da NOTA de um lançamento — vazio quando ele não foi detalhado.
 *
 * Todo lançamento simples com categoria guarda UM item, o **item-sombra**: título
 * e valor do próprio lançamento, só para a categoria morar em algum lugar. Ele não
 * é item da nota. A regra é a mesma do MCP (`_itens` em
 * `backend/app/mcp/serializers.py`): há nota quando há mais de um item, divisão
 * por item, ajustes, ou quando a única linha diz algo a mais que o lançamento
 * (quantidade, unidade, unitário, descrição).
 *
 * Sem ela, a tela tratava todo item da divisão "pela despesa" como sombra: a
 * nota que a IA lançou — um item com medida e três ajustes — não aparecia no
 * detalhe nem na edição, e salvar a edição a trocava pelo item-sombra.
 */
export function itensDaNota<T extends {
  quantity: string;
  unit?: string | null;
  unit_amount?: string | null;
  description?: string | null;
}>(tx: { split_mode: string; items?: T[] | null; adjustments?: unknown[] | null }): T[] {
  const itens = tx.items ?? [];
  const detalhado = itens.length > 1
    || tx.split_mode === 'item'
    || (tx.adjustments ?? []).length > 0
    || itens.some((i) => parseFloat(i.quantity) !== 1 || !!i.unit || i.unit_amount != null || !!i.description);
  return detalhado ? itens : [];
}
