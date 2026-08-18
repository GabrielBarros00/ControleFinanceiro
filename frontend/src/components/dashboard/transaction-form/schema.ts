import * as z from 'zod';
import { formatCurrency } from '@/lib/money';
import type { PaymentMethod, TransactionRead } from '@/types/transaction';
import { apiDateToInput, todayLocalISO } from '@/lib/date';

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
  quantity: z.number({ error: 'Informe a quantidade' }).gt(0, 'Quantidade inválida'),
  // 0/null = sem preço unitário: o total da linha é digitado direto
  unit_amount: z.number().nullable(),
  amount: z.number({ error: 'Informe o valor' }).min(0.01, 'Valor do item inválido'),
  category_id: z.string(),
  share_method: z.enum(['equal', 'percentage', 'fixed']),
  shares: z.array(shareSchema).min(1, 'Adicione pelo menos um participante'),
});

// Espelham TITLE_MAX e MAX_MONEY do backend (app/schemas/common.py). Sem eles o
// usuário só descobria o limite num 422 genérico depois de preencher tudo.
//
// O teto aqui é MENOR que o do backend de propósito: o MAX_MONEY de lá
// (9999999999999999.99) está acima de Number.MAX_SAFE_INTEGER e não é
// representável em JS sem perder precisão. 1e15 é seguro, folgadíssimo para
// finanças pessoais, e garante que nada que passe daqui seja recusado lá.
const TITLE_MAX = 200;
const MAX_MONEY = 1e15;

export const transactionFormSchema = z.object({
  title: z.string().min(2, 'O título deve ter pelo menos 2 caracteres').max(TITLE_MAX, `O título deve ter no máximo ${TITLE_MAX} caracteres`),
  total_amount: z.number().min(0.01, 'O valor deve ser maior que zero').max(MAX_MONEY, 'Valor acima do limite permitido'),
  currency: z.string(),
  transaction_date: z.string().min(1, 'Informe a data'),
  payers: z.array(payerSchema).min(1, 'Adicione pelo menos um pagador'),
  payment_method: z.string(), // '' = não informado
  credit_card_id: z.string(), // '' = sem cartão
  installments: z.number().int().min(1).max(36),
  category_id: z.string(),    // modo transaction: item único p/ relatórios
  tag_ids: z.array(z.number()),
  split_mode: z.enum(['transaction', 'item']),
  split_method: z.enum(['equal', 'percentage', 'fixed']),
  splits: z.array(shareSchema),
  items: z.array(itemSchema),
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

  if (data.split_mode === 'transaction') {
    validateShareGroup(ctx, ['splits'], data.split_method, data.splits, data.total_amount, money);
    if (data.splits.length === 0) {
      ctx.addIssue({
        code: 'custom',
        path: ['splits'],
        message: 'Adicione pelo menos um participante',
      });
    }
    return;
  }

  // ------- split_mode === 'item' -------
  if (data.items.length === 0) {
    ctx.addIssue({
      code: 'custom',
      path: ['items'],
      message: 'Adicione pelo menos um item',
    });
    return;
  }

  const itemsCents = data.items.reduce((acc, item) => acc + cents(item.amount), 0);
  const totalCents = cents(data.total_amount);
  if (itemsCents !== totalCents) {
    const diff = Math.abs(totalCents - itemsCents) / 100;
    ctx.addIssue({
      code: 'custom',
      path: ['items'],
      message: itemsCents < totalCents
        ? `Os itens somam ${money(itemsCents / 100)} de ${money(totalCents / 100)} — faltam ${money(diff)}`
        : `Os itens somam ${money(itemsCents / 100)} de ${money(totalCents / 100)} — ${money(diff)} acima do total`,
    });
  }

  data.items.forEach((item, index) => {
    if (item.unit_amount != null && item.unit_amount > 0) {
      const expected = Math.round(item.quantity * cents(item.unit_amount));
      if (expected !== cents(item.amount)) {
        ctx.addIssue({
          code: 'custom',
          path: ['items', index, 'amount'],
          message: `Valor da linha difere de quantidade × unitário (${money(expected / 100)})`,
        });
      }
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
    total_amount: v.total_amount,
    transaction_date: transactionDate,
    billing_month: v.transaction_date.slice(0, 7),
    currency: v.currency || 'BRL',
    payment_method: paymentMethod,
    credit_card_id: v.credit_card_id ? Number(v.credit_card_id) : null,
    split_mode: v.split_mode,
    tag_ids: v.tag_ids,
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

  if (v.split_mode === 'transaction') {
    return {
      ...base,
      splits: v.splits.map((s) => ({
        user_id: Number(s.user_id),
        split_method: v.split_method,
        input_value: v.split_method === 'equal' ? 0 : s.value,
      })),
      // Categoria opcional: cria o item único da transação (alimenta relatórios).
      // `quantity`/`position` explícitos: o backend tem default para os dois, mas
      // omiti-los deixava o payload divergente do item do modo `item` logo abaixo
      // — e nada garantia que os defaults continuassem sendo 1 e 0.
      items: v.category_id
        ? [{
            title: v.title,
            amount: v.total_amount,
            quantity: 1,
            position: 0,
            category_id: Number(v.category_id),
          }]
        : [],
    };
  }

  return {
    ...base,
    splits: [],
    items: v.items.map((item, index) => ({
      title: item.title,
      amount: item.amount,
      quantity: item.quantity,
      unit_amount: item.unit_amount && item.unit_amount > 0 ? item.unit_amount : null,
      position: index,
      category_id: item.category_id ? Number(item.category_id) : null,
      shares: item.shares.map((sh) => ({
        user_id: Number(sh.user_id),
        split_method: item.share_method,
        input_value: item.share_method === 'equal' ? 0 : sh.value,
      })),
    })),
  };
}

export function fromApiTransaction(tx: TransactionRead): TransactionFormValues {
  const base = {
    title: tx.title,
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
    installments: 1, // reparcelar não existe na edição
    tag_ids: (tx.tags ?? []).map((t) => t.id),
    split_mode: tx.split_mode ?? 'transaction',
  };

  if ((tx.split_mode ?? 'transaction') === 'transaction') {
    return {
      ...base,
      split_mode: 'transaction',
      category_id: tx.items?.[0]?.category_id ? String(tx.items[0].category_id) : '',
      split_method: tx.splits?.[0]?.split_method ?? 'equal',
      splits: (tx.splits ?? []).map((s) => ({
        user_id: String(s.user_id),
        value: parseFloat(s.input_value),
      })),
      items: [],
    };
  }

  return {
    ...base,
    split_mode: 'item',
    category_id: '',
    split_method: 'equal',
    splits: [],
    items: (tx.items ?? [])
      .slice()
      .sort((a, b) => a.position - b.position)
      .map((item) => ({
        title: item.title,
        amount: parseFloat(item.amount),
        quantity: item.quantity != null ? parseFloat(item.quantity) : 1,
        unit_amount: item.unit_amount != null ? parseFloat(item.unit_amount) : null,
        category_id: item.category_id ? String(item.category_id) : '',
        share_method: item.shares?.[0]?.split_method ?? 'equal',
        shares: (item.shares ?? []).map((sh) => ({
          user_id: String(sh.user_id),
          value: parseFloat(sh.input_value),
        })),
      })),
  };
}
