import * as z from 'zod';
import { formatCurrency } from '@/lib/money';
import type { PaymentMethod, TransactionRead } from '@/types/transaction';
import { apiDateToInput, todayLocalISO } from '@/lib/date';
import { UNIDADES, UNIDADE_ROTULO, itensDaNota, linhaFecha, totalDaLinha, type Unidade } from '@/lib/item-da-nota';
import { TIPOS_DE_AJUSTE, ajusteComSinal } from '@/lib/ajuste-da-nota';

const formatPercent = (value: number) =>
  value.toLocaleString('pt-BR', { maximumFractionDigits: 2 });

const cents = (value: number) => Math.round((Number.isFinite(value) ? value : 0) * 100);

const shareSchema = z.object({
  user_id: z.string().min(1, 'Selecione o usuário'),
  value: z.number({ error: 'Informe o valor' }).min(0, 'Valor inválido'),
});

const payerSchema = z.object({
  user_id: z.string().min(1, 'Selecione quem pagou'),
  amount: z.number({ error: 'Informe o valor' }).min(0, 'Valor inválido'),
  // Origem por pagador (ADR 0004): '' = herda o método/conta da despesa
  payment_method: z.string(),
  account_id: z.string(),
});

const itemSchema = z.object({
  title: z.string().min(1, 'Informe o título do item').max(200, 'Título do item muito longo'),
  // O detalhe da linha ("combo com 2 sanduíches"). A tela não o edita, mas o
  // devolve: a edição é completa e, sem ele, salvar apagava o que a IA anotou.
  description: z.string(),
  quantity: z.number({ error: 'Informe a quantidade' }).gt(0, 'Quantidade inválida'),
  // A medida da nota (ADR 0040): unidade e preço unitário com até 4 casas.
  // `null` só em linha antiga, gravada antes de a medida existir.
  unit: z.enum(UNIDADES).nullable(),
  unit_amount: z.number().nullable(),
  amount: z.number({ error: 'Informe o valor' }).min(0.01, 'Valor do item inválido'),
  // Só do formulário, não vai à API: a linha nasceu AGORA, neste formulário.
  // A medida é obrigatória ao adicionar item (decisão do dono, ADR 0040) — e só
  // aí: editar um lançamento antigo não obriga a inventar a medida que ninguém
  // informou.
  nova: z.boolean(),
  category_id: z.string(),
  share_method: z.enum(['equal', 'percentage', 'fixed']),
  // Só a divisão POR ITEM usa: na divisão pela despesa o item é linha da nota,
  // sem participantes. O "pelo menos um" é conferido lá embaixo, por modo.
  shares: z.array(shareSchema),
});

// Ajuste da nota (desconto, frete, taxa…): o valor vai sem sinal, e o sinal
// sai do tipo — ou de `reduz`, no arredondamento e no "outro" (`ajuste-da-nota`).
const adjustmentSchema = z.object({
  type: z.enum(TIPOS_DE_AJUSTE),
  description: z.string().max(2000, 'Descrição do ajuste muito longa'),
  amount: z.number({ error: 'Informe o valor' }).min(0.01, 'Informe o valor do ajuste'),
  reduz: z.boolean(),
});

// Espelham TITLE_MAX e MAX_MONEY do backend (app/schemas/common.py). Sem eles o
// usuário só descobria o limite num 422 genérico depois de preencher tudo.
//
// O teto aqui é MENOR que o do backend de propósito: o MAX_MONEY de lá
// (9999999999999999.99) está acima de Number.MAX_SAFE_INTEGER e não é
// representável em JS sem perder precisão. 1e15 é seguro, folgadíssimo para
// finanças pessoais, e garante que nada que passe daqui seja recusado lá.
const TITLE_MAX = 200;
const DESCRIPTION_MAX = 2000;
const MAX_MONEY = 1e15;

export const transactionFormSchema = z.object({
  title: z.string().min(2, 'O título deve ter pelo menos 2 caracteres').max(TITLE_MAX, `O título deve ter no máximo ${TITLE_MAX} caracteres`),
  // Observação livre do lançamento (`description`). Sempre existiu no modelo, e a
  // IA já a preenchia; faltava o campo na tela. Vazio = sem observação.
  description: z.string().max(DESCRIPTION_MAX, `A observação deve ter no máximo ${DESCRIPTION_MAX} caracteres`),
  total_amount: z.number().min(0.01, 'O valor deve ser maior que zero').max(MAX_MONEY, 'Valor acima do limite permitido'),
  currency: z.string(),
  transaction_date: z.string().min(1, 'Informe a data'),
  payers: z.array(payerSchema).min(1, 'Adicione pelo menos um pagador'),
  payment_method: z.string(), // '' = não informado
  credit_card_id: z.string(), // '' = sem cartão
  // Deslocamento de fatura (ADR 0032): em qual fatura a compra REALMENTE entrou,
  // quando o emissor a processou noutro ciclo. `0` = vale a regra do fechamento.
  // Os limites espelham `STATEMENT_SHIFT_MIN/MAX` do backend — estreitos porque
  // isto corrige atraso de captura, não escolhe mês de despesa.
  statement_shift: z.number().int().min(-1).max(2),
  installments: z.number().int().min(1).max(36),
  category_id: z.string(),    // modo transaction: item único p/ relatórios
  tag_ids: z.array(z.number()),
  // Estabelecimento pelo nome (ADR 0038): o servidor acha pelo nome ou apelido,
  // ou cria. `merchant_initial` é o que veio do lançamento, para só mandar o
  // campo quando ele MUDOU (e para "apagar" poder desvincular).
  merchant_name: z.string().max(120, 'No máximo 120 caracteres'),
  merchant_initial: z.string(),
  split_mode: z.enum(['transaction', 'item']),
  split_method: z.enum(['equal', 'percentage', 'fixed']),
  splits: z.array(shareSchema),
  // Os itens da nota. Na divisão por item, cada um com os seus participantes; na
  // divisão pela despesa, só a nota (vazio = lançamento sem nota, e a categoria
  // vai no item-sombra).
  items: z.array(itemSchema),
  // Fecham a soma dos itens com o total; só existem com itens.
  adjustments: z.array(adjustmentSchema),
  // "Já foi paga" (ADR 0029): CAIXA, não competência. `true` = o dinheiro já
  // saiu; `false` = a despesa existe e entra no rateio, mas ainda está na fila
  // de Contas a pagar. Só aparece nos espaços que controlam pagamento.
  settled: z.boolean(),
}).superRefine((data, ctx) => {
  if (data.payment_method === 'credit_card' && !data.credit_card_id) {
    ctx.addIssue({
      code: 'custom',
      path: ['credit_card_id'],
      message: 'Selecione qual cartão foi usado',
    });
  }

  // As mensagens falam a moeda do lançamento — não um "R$" fixo que contradizia
  // o prefixo dos campos numa despesa em USD/EUR.
  const money = (value: number) => formatCurrency(value, data.currency || 'BRL');

  // Pagadores: sem repetição; com vários, a soma precisa fechar o total
  const seenPayers = new Set<string>();
  data.payers.forEach((payer, index) => {
    // Origem coerente (mesmas regras do backend). O requisito de cartão é
    // emitido no campo SEMPRE visível (credit_card_id) — não num campo de
    // pagador que pode estar oculto — para o erro sumir assim que o cartão é
    // escolhido (antes ficava "preso" no path do pagador).
    if (payer.payment_method === 'credit_card') {
      if (!data.credit_card_id) {
        ctx.addIssue({
          code: 'custom',
          path: ['credit_card_id'],
          message: 'Selecione o cartão usado nesta despesa',
        });
      }
      if (payer.account_id) {
        ctx.addIssue({
          code: 'custom',
          path: ['payers', index, 'account_id'],
          message: 'Pagamento no cartão não sai de uma conta',
        });
      }
    }
    if (!payer.user_id) return;
    if (seenPayers.has(payer.user_id)) {
      ctx.addIssue({
        code: 'custom',
        path: ['payers', index, 'user_id'],
        message: 'Pagador repetido',
      });
    }
    seenPayers.add(payer.user_id);
  });
  if (data.payers.length > 1) {
    const sumCents = data.payers.reduce((acc, p) => acc + cents(p.amount), 0);
    const totalCents = cents(data.total_amount);
    if (sumCents !== totalCents) {
      const diff = Math.abs(totalCents - sumCents) / 100;
      ctx.addIssue({
        code: 'custom',
        path: ['payers'],
        message: sumCents < totalCents
          ? `Os pagadores somam ${money(sumCents / 100)} de ${money(totalCents / 100)} — faltam ${money(diff)}`
          : `Os pagadores somam ${money(sumCents / 100)} de ${money(totalCents / 100)} — ${money(diff)} acima do total`,
      });
    }
  }

  // Parcelamento: só no crédito, 1 pagador. A divisão (igual/percentual/fixo,
  // pela despesa ou por item) é fatiada pelos N meses no backend.
  if (data.installments > 1) {
    if (data.payment_method !== 'credit_card') {
      ctx.addIssue({
        code: 'custom',
        path: ['installments'],
        message: 'Parcelamento exige pagamento no cartão de crédito',
      });
    }
    if (data.payers.length > 1) {
      ctx.addIssue({
        code: 'custom',
        path: ['installments'],
        message: 'Parcelamento exige um único pagador',
      });
    }
  }

  const porItem = data.split_mode === 'item';

  if (!porItem) {
    validateShareGroup(ctx, ['splits'], data.split_method, data.splits, data.total_amount, money);
    if (data.splits.length === 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['splits'],
        message: 'Adicione pelo menos um participante',
      });
    }
    // O backend recusa: cada parcela levaria a nota inteira.
    if (data.installments > 1 && data.items.length > 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['items'],
        message: 'Parcelamento pela despesa não leva itens da nota — use a divisão por item',
      });
    }
  } else if (data.items.length === 0) {
    ctx.addIssue({
      code: 'custom',
      path: ['items'],
      message: 'Adicione pelo menos um item',
    });
    return;
  }

  // Ajustes fecham os itens com o total — sem itens, não há o que fechar.
  if (data.adjustments.length > 0 && data.items.length === 0) {
    ctx.addIssue({
      code: 'custom',
      path: ['adjustments'],
      message: 'Ajustes fecham a soma dos itens com o total — adicione os itens da nota',
    });
  }
  if (data.adjustments.length > 0 && data.installments > 1) {
    ctx.addIssue({
      code: 'custom',
      path: ['adjustments'],
      message: 'Compra parcelada não leva ajustes (desconto, frete, taxa) — lance os itens já com o desconto',
    });
  }

  // Divisão pela despesa sem nota: nada mais a conferir.
  if (data.items.length === 0) return;

  const itemsCents = data.items.reduce((acc, item) => acc + cents(item.amount), 0);
  const ajustesCents = data.adjustments.reduce(
    (acc, a) => acc + cents(ajusteComSinal(a.type, a.amount, a.reduz)), 0,
  );
  const totalCents = cents(data.total_amount);
  const somaCents = itemsCents + ajustesCents;
  if (somaCents !== totalCents) {
    const diff = Math.abs(totalCents - somaCents) / 100;
    const falta = somaCents < totalCents;
    ctx.addIssue({
      code: 'custom',
      path: ['items'],
      message: data.adjustments.length === 0
        ? (falta
            ? `Os itens somam ${money(itemsCents / 100)} de ${money(totalCents / 100)} — faltam ${money(diff)}`
            : `Os itens somam ${money(itemsCents / 100)} de ${money(totalCents / 100)} — ${money(diff)} acima do total`)
        : `Itens (${money(itemsCents / 100)}) + ajustes (${money(ajustesCents / 100)}) dão ${money(somaCents / 100)} de ${money(totalCents / 100)} — `
          + (falta ? `faltam ${money(diff)}` : `${money(diff)} acima do total`),
    });
  }

  data.items.forEach((item, index) => {
    const temUnitario = item.unit_amount != null && item.unit_amount > 0;
    if (item.nova && !item.unit) {
      ctx.addIssue({
        code: 'custom',
        path: ['items', index, 'unit'],
        message: 'Escolha a unidade',
      });
    }
    if (item.nova && !temUnitario) {
      ctx.addIssue({
        code: 'custom',
        path: ['items', index, 'unit_amount'],
        message: 'Informe o preço unitário da nota',
      });
    }
    // O total impresso é a verdade e pode diferir em até 1 centavo do produto
    // exato — a balança arredonda ou trunca (ADR 0040). A mesma regra do servidor.
    if (temUnitario && Number.isFinite(item.quantity) && !linhaFecha(item.quantity, item.unit_amount!, item.amount)) {
      const unidade = item.unit ? ` ${UNIDADE_ROTULO[item.unit]}` : '';
      const quantidade = item.quantity.toLocaleString('pt-BR', { maximumFractionDigits: 3 });
      ctx.addIssue({
        code: 'custom',
        path: ['items', index, 'amount'],
        message: `${quantidade}${unidade} × unitário dá ${money(totalDaLinha(item.quantity, item.unit_amount!))} — confira a nota (a balança pode diferir em até 1 centavo)`,
      });
    }
    if (!porItem) return;
    if (item.shares.length === 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['items', index, 'shares'],
        message: 'Adicione pelo menos um participante',
      });
    }
    validateShareGroup(
      ctx,
      ['items', index, 'shares'],
      item.share_method,
      item.shares,
      item.amount,
      money
    );
  });
});

function validateShareGroup(
  ctx: z.RefinementCtx,
  path: (string | number)[],
  method: 'equal' | 'percentage' | 'fixed',
  shares: { user_id: string; value: number }[],
  totalAmount: number,
  money: (value: number) => string
) {
  const seen = new Set<string>();
  shares.forEach((share, index) => {
    if (!share.user_id) return;
    if (seen.has(share.user_id)) {
      ctx.addIssue({
        code: 'custom',
        path: [...path, index, 'user_id'],
        message: 'Participante repetido na divisão',
      });
    }
    seen.add(share.user_id);
  });

  if (method === 'percentage') {
    // Mesma regra do backend: cada participante 0 < pct ≤ 100
    shares.forEach((share, index) => {
      if (Number.isFinite(share.value) && (share.value <= 0 || share.value > 100)) {
        ctx.addIssue({
          code: 'custom',
          path: [...path, index, 'value'],
          message: 'Cada percentual deve ficar entre 0 e 100',
        });
      }
    });
    // Soma exata em centésimos de % (inteiros) — sem tolerância de float,
    // espelhando a igualdade exata em Decimal do backend
    const sumCents = shares.reduce(
      (acc, s) => acc + Math.round((Number.isFinite(s.value) ? s.value : 0) * 100), 0
    );
    const sum = sumCents / 100;
    if (shares.length > 0 && sumCents !== 10000) {
      ctx.addIssue({
        code: 'custom',
        path,
        message: sum < 100
          ? `Os percentuais somam ${formatPercent(sum)}% — faltam ${formatPercent(100 - sum)}%`
          : `Os percentuais somam ${formatPercent(sum)}% — ${formatPercent(sum - 100)}% acima de 100%`,
      });
    }
  }

  if (method === 'fixed') {
    // Soma em centavos: evita falso-negativo de ponto flutuante (0.1 + 0.2)
    const sumCents = shares.reduce((acc, s) => acc + cents(s.value), 0);
    const totalCents = cents(totalAmount);
    if (shares.length > 0 && sumCents !== totalCents) {
      const diff = Math.abs(totalCents - sumCents) / 100;
      ctx.addIssue({
        code: 'custom',
        path,
        message: sumCents < totalCents
          ? `Os valores somam ${money(sumCents / 100)} de ${money(totalCents / 100)} — faltam ${money(diff)}`
          : `Os valores somam ${money(sumCents / 100)} de ${money(totalCents / 100)} — ${money(diff)} acima do total`,
      });
    }
  }
}

export type TransactionFormValues = z.infer<typeof transactionFormSchema>;

// ---------------------------------------------------------------------------
// Round-trip formulário ⟷ API
// ---------------------------------------------------------------------------

function isToday(dateStr: string): boolean {
  return dateStr === todayLocalISO();
}

// Reexportado de @/lib/date: uma única definição de "hoje" no app inteiro
export { todayLocalISO };

/**
 * O estabelecimento só vai quando mudou. Na criação, vazio não manda nada e o
 * servidor liga pelo apelido do título; na edição, apagar desvincula.
 */
function estabelecimento(v: TransactionFormValues): { merchant_name?: string; merchant_id?: null } {
  const nome = v.merchant_name.trim();
  if (nome === v.merchant_initial) return {};
  return nome ? { merchant_name: nome } : { merchant_id: null };
}

export function toApiPayload(v: TransactionFormValues) {
  // Data de hoje mantém o horário real; retroativa fixa 12:00 local (padrão do
  // app). billing_month sai da data ESCOLHIDA no fuso local — nunca do UTC.
  const transactionDate = isToday(v.transaction_date)
    ? new Date().toISOString()
    : new Date(`${v.transaction_date}T12:00:00`).toISOString();

  // `PaymentMethod`, não `string`: o formulário guarda `''` para "não informado"
  // e o campo é `z.string()` livre, então sem esta âncora um método inválido
  // chegava ao backend e voltava 422 sem que o `tsc` tivesse como avisar. O
  // `null` continua sendo o valor legítimo de "não informado" na API.
  const paymentMethod: PaymentMethod | null =
    v.credit_card_id && !v.payment_method
      ? 'credit_card'
      : ((v.payment_method || null) as PaymentMethod | null);

  const base = {
    title: v.title,
    // Sempre explícita: na edição, apagar o texto tem de apagar a observação.
    description: v.description.trim() || null,
    total_amount: v.total_amount,
    transaction_date: transactionDate,
    billing_month: v.transaction_date.slice(0, 7),
    currency: v.currency || 'BRL',
    payment_method: paymentMethod,
    credit_card_id: v.credit_card_id ? Number(v.credit_card_id) : null,
    // Sem cartão o backend recusa qualquer deslocamento (ele exige um cartão
    // para haver fatura), e o formulário pode carregar um valor residual de
    // quando o método era crédito — trocar para Pix não limpa o campo. Zerar
    // aqui, na fronteira, evita um 422 que a pessoa não teria como explicar.
    statement_shift: v.credit_card_id ? v.statement_shift : 0,
    split_mode: v.split_mode,
    tag_ids: v.tag_ids,
    ...estabelecimento(v),
    // Sempre explícito (ADR 0029): sem o campo, o backend cai no palpite pela
    // data, e o palpite discordaria da caixa que a pessoa acabou de ver marcada
    // na tela. Compra no cartão ignora — quem paga é a fatura.
    settled: v.settled,
    ...(v.installments > 1 ? { installments_count: v.installments } : {}),
    // Pagador único paga o total; com vários, cada um informa a sua parte.
    // `PaymentMethod | null` pelo mesmo motivo do método da transação acima: o
    // campo do formulário é string livre com `''` para "não informado" (ADR 0004
    // — cada pagador pode ter origem própria).
    payers: v.payers.length === 1
      ? [{
          user_id: Number(v.payers[0].user_id),
          amount: v.total_amount,
          payment_method: (v.payers[0].payment_method || null) as PaymentMethod | null,
          account_id: v.payers[0].account_id ? Number(v.payers[0].account_id) : null,
        }]
      : v.payers.map((p) => ({
          user_id: Number(p.user_id),
          amount: p.amount,
          payment_method: (p.payment_method || null) as PaymentMethod | null,
          account_id: p.account_id ? Number(p.account_id) : null,
        })),
  };

  // A linha da nota, igual nos dois modos; a divisão por item acrescenta as partes.
  const linha = (item: TransactionFormValues['items'][number], index: number) => ({
    title: item.title,
    description: item.description.trim() || null,
    amount: item.amount,
    quantity: item.quantity,
    unit: item.unit,
    unit_amount: item.unit_amount && item.unit_amount > 0 ? item.unit_amount : null,
    position: index,
    category_id: item.category_id ? Number(item.category_id) : null,
  });
  // Sempre explícitos: a edição é completa, e sem o campo o backend DESCARTA os
  // ajustes gravados (`_full_edit`).
  const adjustments = v.items.length === 0 ? [] : v.adjustments.map((a) => ({
    type: a.type,
    description: a.description.trim() || null,
    amount: ajusteComSinal(a.type, a.amount, a.reduz),
  }));

  if (v.split_mode === 'transaction') {
    return {
      ...base,
      splits: v.splits.map((s) => ({
        user_id: Number(s.user_id),
        split_method: v.split_method,
        input_value: v.split_method === 'equal' ? 0 : s.value,
      })),
      // Com nota, vão os itens dela, sem participantes: quem divide é a despesa.
      // Sem nota, a categoria opcional cria o item-sombra (alimenta relatórios).
      // `quantity`/`position` explícitos: o backend tem default para os dois, mas
      // omiti-los deixava o payload divergente do item do modo `item` logo abaixo
      // — e nada garantia que os defaults continuassem sendo 1 e 0.
      items: v.items.length > 0
        ? v.items.map(linha)
        : v.category_id
          ? [{
              title: v.title,
              amount: v.total_amount,
              quantity: 1,
              position: 0,
              category_id: Number(v.category_id),
            }]
          : [],
      adjustments,
    };
  }

  return {
    ...base,
    splits: [],
    items: v.items.map((item, index) => ({
      ...linha(item, index),
      shares: item.shares.map((sh) => ({
        user_id: Number(sh.user_id),
        split_method: item.share_method,
        input_value: item.share_method === 'equal' ? 0 : sh.value,
      })),
    })),
    adjustments,
  };
}

/*
 * A compra estrangeira, de volta na moeda DELA.
 *
 * O formulário edita o total original (US$ 50) e o servidor reconverte ao
 * salvar. Mas itens, ajustes, pagadores e valores fixos são gravados na moeda do
 * espaço (a conversão da entrada os converte junto), e a edição os abria como
 * vieram: "US$ 50" com itens de "US$ 290", uma soma que nunca fechava.
 *
 * Cada valor volta pela razão original ÷ convertido, e o centavo que o
 * arredondamento deixa sobrando vai para a maior parcela do grupo — é o que faz
 * a soma fechar exata, como o servidor exige. O unitário do item volta com 4
 * casas, ou fica vazio se nem assim a linha fechar (a mesma regra da conversão
 * de ida, ADR 0040).
 */
function naMoedaDaCompra(tx: TransactionRead): TransactionRead {
  if (!tx.original_currency || !tx.original_amount) return tx;
  const convertido = parseFloat(tx.total_amount);
  const original = parseFloat(tx.original_amount);
  if (!(convertido > 0) || !(original > 0)) return tx;

  const centavos = (v: string | number) => Math.round(parseFloat(String(v)) * original * 100 / convertido);
  const texto = (c: number) => (c / 100).toFixed(2);
  /** Converte um grupo e põe a sobra na maior parcela entre as `ajustaveis` primeiras. */
  const grupo = (valores: (string | number)[], alvo: number, ajustaveis = valores.length) => {
    const cs = valores.map(centavos);
    const sobra = alvo - cs.reduce((a, c) => a + c, 0);
    if (sobra !== 0 && ajustaveis > 0) {
      let maior = 0;
      for (let i = 1; i < ajustaveis; i++) if (Math.abs(cs[i]) > Math.abs(cs[maior])) maior = i;
      cs[maior] += sobra;
    }
    return cs;
  };
  const alvo = Math.round(original * 100);

  const pagadores = grupo((tx.payers ?? []).map((p) => p.amount), alvo);
  const fixos = tx.splits?.[0]?.split_method === 'fixed';
  const partes = fixos ? grupo((tx.splits ?? []).map((s) => s.input_value), alvo) : null;

  const itens = tx.items ?? [];
  const ajustes = tx.adjustments ?? [];
  // Itens e ajustes fecham o total juntos; a sobra fica num item, nunca num ajuste.
  const linhas = itens.length > 0
    ? grupo([...itens.map((i) => i.amount), ...ajustes.map((a) => a.amount)], alvo, itens.length)
    : [];

  return {
    ...tx,
    payers: (tx.payers ?? []).map((p, i) => ({ ...p, amount: texto(pagadores[i]) })),
    splits: (tx.splits ?? []).map((s, i) => (partes ? { ...s, input_value: texto(partes[i]) } : s)),
    items: itens.map((item, i) => {
      const valor = linhas[i];
      const qtd = parseFloat(item.quantity);
      let unitario: string | null = null;
      if (item.unit_amount != null && qtd > 0) {
        const u = Math.round((valor / 100 / qtd) * 10_000) / 10_000;
        unitario = linhaFecha(qtd, u, valor / 100) ? String(u) : null;
      }
      const cotas = item.shares?.[0]?.split_method === 'fixed'
        ? grupo(item.shares.map((sh) => sh.input_value), valor)
        : null;
      return {
        ...item,
        amount: texto(valor),
        unit_amount: unitario,
        shares: (item.shares ?? []).map((sh, j) => (cotas ? { ...sh, input_value: texto(cotas[j]) } : sh)),
      };
    }),
    adjustments: ajustes.map((a, j) => ({ ...a, amount: texto(linhas[itens.length + j] ?? centavos(a.amount)) })),
  };
}

export function fromApiTransaction(lido: TransactionRead): TransactionFormValues {
  const tx = naMoedaDaCompra(lido);
  const base = {
    title: tx.title,
    description: tx.description ?? '',
    // Estrangeiro: edita o valor/moeda ORIGINAIS (o backend re-converte no save)
    total_amount: tx.original_currency && tx.original_amount ? parseFloat(tx.original_amount) : parseFloat(tx.total_amount),
    currency: tx.original_currency ?? tx.currency ?? 'BRL',
    transaction_date: tx.transaction_date ? apiDateToInput(tx.transaction_date) : todayLocalISO(),
    payers: (tx.payers ?? []).map((p) => ({
      user_id: String(p.user_id),
      amount: parseFloat(p.amount),
      payment_method: p.payment_method ?? '',
      account_id: p.account_id != null ? String(p.account_id) : '',
    })),
    payment_method: tx.payment_method ?? (tx.credit_card_id ? 'credit_card' : ''),
    credit_card_id: tx.credit_card_id ? String(tx.credit_card_id) : '',
    // O deslocamento REAL da linha, não `0`: abrir para corrigir o título uma
    // compra já movida para a fatura seguinte e salvar a traria de volta para o
    // ciclo natural — desfazendo, calada, a correção que alguém fez de propósito.
    statement_shift: tx.statement_shift ?? 0,
    installments: 1, // reparcelar não existe na edição
    tag_ids: (tx.tags ?? []).map((t) => t.id),
    merchant_name: tx.merchant?.name ?? '',
    merchant_initial: tx.merchant?.name ?? '',
    split_mode: tx.split_mode ?? 'transaction',
    // O estado REAL da liquidação, não um default (ADR 0029): abrir uma conta
    // ainda não paga com a caixa marcada, e salvar, a daria por paga sem que
    // ninguém tivesse dito isso.
    settled: tx.settled_at != null,
    // O valor gravado tem sinal; o formulário o separa em valor e `reduz`.
    adjustments: (tx.adjustments ?? []).map((a) => ({
      type: a.type,
      description: a.description ?? '',
      amount: Math.abs(parseFloat(a.amount)),
      reduz: parseFloat(a.amount) < 0,
    })),
  };

  const itens = (lidos: TransactionRead['items']) => lidos
    .slice()
    .sort((a, b) => a.position - b.position)
    .map((item) => ({
      title: item.title,
      description: item.description ?? '',
      amount: parseFloat(item.amount),
      quantity: item.quantity != null ? parseFloat(item.quantity) : 1,
      unit: (UNIDADES as readonly string[]).includes(item.unit ?? '') ? (item.unit as Unidade) : null,
      unit_amount: item.unit_amount != null ? parseFloat(item.unit_amount) : null,
      nova: false,
      category_id: item.category_id ? String(item.category_id) : '',
      share_method: item.shares?.[0]?.split_method ?? 'equal',
      shares: (item.shares ?? []).map((sh) => ({
        user_id: String(sh.user_id),
        value: parseFloat(sh.input_value),
      })),
    }));

  if ((tx.split_mode ?? 'transaction') === 'transaction') {
    // A divisão pela despesa também pode ter nota (a IA lança assim quando todos
    // os itens seguem a mesma divisão). Sem nota, o único item é a sombra da
    // categoria, e é só a categoria que o formulário lê dele.
    const nota = itensDaNota({ ...tx, split_mode: 'transaction' });
    return {
      ...base,
      split_mode: 'transaction',
      category_id: nota.length === 0 && tx.items?.[0]?.category_id ? String(tx.items[0].category_id) : '',
      split_method: tx.splits?.[0]?.split_method ?? 'equal',
      splits: (tx.splits ?? []).map((s) => ({
        user_id: String(s.user_id),
        value: parseFloat(s.input_value),
      })),
      items: itens(nota),
    };
  }

  return {
    ...base,
    split_mode: 'item',
    category_id: '',
    split_method: 'equal',
    splits: [],
    items: itens(tx.items ?? []),
  };
}
