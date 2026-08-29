import { describe, it, expect } from 'vitest';
import {
  transactionFormSchema,
  toApiPayload,
  fromApiTransaction,
  todayLocalISO,
  type TransactionFormValues,
} from '../schema';
import type { TransactionRead } from '@/types/transaction';

const baseValues: TransactionFormValues = {
  title: 'Mercado',
  total_amount: 90,
  currency: 'BRL',
  transaction_date: todayLocalISO(),
  payers: [{ user_id: '1', amount: 0, payment_method: '', account_id: '' }],
  payment_method: '',
  credit_card_id: '',
  statement_shift: 0,
  installments: 1,
  category_id: '',
  tag_ids: [],
  split_mode: 'transaction',
  split_method: 'equal',
  splits: [{ user_id: '1', value: 0 }],
  items: [],
  // Despesa de hoje nasce liquidada (ADR 0029) — o padrão do formulário.
  settled: true,
};

const item = (over: Partial<TransactionFormValues['items'][number]> = {}) => ({
  title: 'Carne',
  quantity: 1,
  unit_amount: null,
  amount: 60,
  category_id: '',
  share_method: 'equal' as const,
  shares: [{ user_id: '1', value: 0 }],
  ...over,
});

describe('transactionFormSchema — modo transaction', () => {
  it('aceita divisão igual válida', () => {
    expect(transactionFormSchema.safeParse(baseValues).success).toBe(true);
  });

  it('rejeita percentuais que não somam 100', () => {
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      split_method: 'percentage',
      splits: [{ user_id: '1', value: 60 }, { user_id: '2', value: 30 }],
    });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result.error?.issues)).toContain('faltam 10%');
  });

  it('rejeita fixos que não fecham o total (comparação em centavos)', () => {
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      split_method: 'fixed',
      splits: [{ user_id: '1', value: 30.1 }, { user_id: '2', value: 59.89 }],
    });
    expect(result.success).toBe(false);
  });

  it('aceita fixos com soma exata mesmo com frações binárias (0.1 + 0.2)', () => {
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      total_amount: 0.3,
      split_method: 'fixed',
      splits: [{ user_id: '1', value: 0.1 }, { user_id: '2', value: 0.2 }],
    });
    expect(result.success).toBe(true);
  });

  it('rejeita participante repetido', () => {
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      splits: [{ user_id: '1', value: 0 }, { user_id: '1', value: 0 }],
    });
    expect(result.success).toBe(false);
  });

  it('rejeita percentual zero para um participante (regra do backend)', () => {
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      split_method: 'percentage',
      splits: [{ user_id: '1', value: 0 }, { user_id: '2', value: 100 }],
    });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result.error?.issues)).toContain('entre 0 e 100');
  });

  it('rejeita soma de percentuais fora por menos que a antiga tolerância de 0.001', () => {
    // 33.33 + 33.33 + 33.3335 = 99.9935: passava com tolerância float, o
    // backend rejeita — o form agora compara em centésimos exatos
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      split_method: 'percentage',
      splits: [
        { user_id: '1', value: 33.33 },
        { user_id: '2', value: 33.33 },
        { user_id: '3', value: 33.3335 },
      ],
    });
    expect(result.success).toBe(false);
  });

  it('aceita percentuais que somam exatamente 100', () => {
    const result = transactionFormSchema.safeParse({
      ...baseValues,
      split_method: 'percentage',
      splits: [
        { user_id: '1', value: 33.33 },
        { user_id: '2', value: 33.33 },
        { user_id: '3', value: 33.34 },
      ],
    });
    expect(result.success).toBe(true);
  });
});

describe('transactionFormSchema — modo item', () => {
  const itemBase: TransactionFormValues = {
    ...baseValues,
    split_mode: 'item',
    splits: [],
    items: [item(), item({ title: 'Cerveja', amount: 30, shares: [{ user_id: '2', value: 0 }] })],
  };

  it('aceita itens que fecham o total', () => {
    expect(transactionFormSchema.safeParse(itemBase).success).toBe(true);
  });

  it('rejeita itens que não somam o total', () => {
    const result = transactionFormSchema.safeParse({
      ...itemBase,
      items: [itemBase.items[0]],
    });
    expect(result.success).toBe(false);
    expect(JSON.stringify(result.error?.issues)).toContain('faltam');
  });

  it('rejeita percentual por item diferente de 100', () => {
    const result = transactionFormSchema.safeParse({
      ...itemBase,
      items: [
        item({
          share_method: 'percentage',
          shares: [{ user_id: '1', value: 70 }, { user_id: '2', value: 20 }],
        }),
        itemBase.items[1],
      ],
    });
    expect(result.success).toBe(false);
  });

  it('rejeita fixos por item que não fecham o valor do item', () => {
    const result = transactionFormSchema.safeParse({
      ...itemBase,
      items: [
        item({
          share_method: 'fixed',
          shares: [{ user_id: '1', value: 20 }, { user_id: '2', value: 30 }],
        }),
        itemBase.items[1],
      ],
    });
    expect(result.success).toBe(false);
  });

  it('valida quantidade × unitário contra o total da linha', () => {
    const bad = transactionFormSchema.safeParse({
      ...itemBase,
      items: [item({ quantity: 3, unit_amount: 10, amount: 25 }),
              item({ title: 'Outro', amount: 65, shares: [{ user_id: '2', value: 0 }] })],
    });
    expect(bad.success).toBe(false);

    const good = transactionFormSchema.safeParse({
      ...itemBase,
      items: [item({ quantity: 3, unit_amount: 10, amount: 30, title: 'Cerveja', shares: [{ user_id: '2', value: 0 }] }),
              item({ title: 'Carne', amount: 60 })],
    });
    expect(good.success).toBe(true);
  });

  it('rejeita modo item sem itens', () => {
    const result = transactionFormSchema.safeParse({ ...itemBase, items: [] });
    expect(result.success).toBe(false);
  });
});

describe('toApiPayload', () => {
  it('modo transaction: categoria vira item único e equal zera input_value', () => {
    const payload = toApiPayload({ ...baseValues, category_id: '7' });
    expect(payload.split_mode).toBe('transaction');
    expect(payload.splits).toEqual([{ user_id: 1, split_method: 'equal', input_value: 0 }]);
    // `quantity`/`position` explícitos: o backend tem default para os dois, mas
    // enviá-los mantém este item igual ao do modo `item`, e o payload deixa de
    // depender de um default do servidor continuar sendo 1 e 0.
    expect(payload.items).toEqual([{ title: 'Mercado', amount: 90, quantity: 1, position: 0, category_id: 7 }]);
    expect(payload.payment_method).toBeNull();
  });

  it('modo item: posições sequenciais, shares e unitário nulo quando zerado', () => {
    const payload = toApiPayload({
      ...baseValues,
      split_mode: 'item',
      splits: [],
      items: [
        item({ quantity: 3, unit_amount: 10, amount: 30, title: 'Cerveja', shares: [{ user_id: '2', value: 0 }] }),
        item({ title: 'Carne', amount: 60, share_method: 'fixed', shares: [{ user_id: '1', value: 60 }] }),
      ],
    });
    expect(payload.splits).toEqual([]);
    expect(payload.items).toEqual([
      {
        title: 'Cerveja', amount: 30, quantity: 3, unit_amount: 10, position: 0, category_id: null,
        shares: [{ user_id: 2, split_method: 'equal', input_value: 0 }],
      },
      {
        title: 'Carne', amount: 60, quantity: 1, unit_amount: null, position: 1, category_id: null,
        shares: [{ user_id: 1, split_method: 'fixed', input_value: 60 }],
      },
    ]);
  });

  it('cartão selecionado sem método explícito infere credit_card', () => {
    const payload = toApiPayload({ ...baseValues, credit_card_id: '3' });
    expect(payload.payment_method).toBe('credit_card');
    expect(payload.credit_card_id).toBe(3);
  });

  it('billing_month sai da data escolhida no fuso local', () => {
    const payload = toApiPayload({ ...baseValues, transaction_date: '2026-01-31' });
    expect(payload.billing_month).toBe('2026-01');
  });

  it('deslocar a fatura NÃO desloca a competência (ADR 0032)', () => {
    // O invariante central da feature, medido na fronteira em que o payload é
    // montado: a compra vai para a fatura seguinte e continua sendo despesa do
    // mês em que aconteceu. Uma implementação que movesse os dois passaria por
    // qualquer teste que olhasse só a fatura.
    const payload = toApiPayload({
      ...baseValues,
      transaction_date: '2026-07-27',
      credit_card_id: '3',
      statement_shift: 1,
    });
    expect(payload.statement_shift).toBe(1);
    expect(payload.billing_month).toBe('2026-07');
    expect(payload.transaction_date.slice(0, 10)).toBe('2026-07-27');
  });

  it('sem cartão o deslocamento é zerado na fronteira', () => {
    // O formulário pode carregar um valor residual de quando o método era
    // crédito — trocar para Pix não limpa o campo. O backend recusaria com 422,
    // e a pessoa não teria como relacionar o erro com a troca de método.
    const payload = toApiPayload({
      ...baseValues,
      credit_card_id: '',
      payment_method: 'pix',
      statement_shift: 1,
    });
    expect(payload.statement_shift).toBe(0);
  });
});

describe('fromApiTransaction — round-trip', () => {
  const apiTx: TransactionRead = {
    id: 10,
    workspace_id: 1,
    title: 'Churrasco',
    currency: 'BRL',
    total_amount: '90.00',
    transaction_date: '2026-07-18T15:00:00Z',
    billing_month: '2026-07',
    status: 'confirmed',
    credit_card_id: 3,
    split_mode: 'item',
    payment_method: 'credit_card',
    created_at: '',
    updated_at: '',
    tags: [],
    adjustments: [],
    payers: [{ id: 1, user_id: 1, amount: '90.00' }],
    splits: [
      { id: 1, user_id: 1, split_method: 'fixed', input_value: '30.00', computed_amount: '30.00' },
      { id: 2, user_id: 2, split_method: 'fixed', input_value: '60.00', computed_amount: '60.00' },
    ],
    items: [
      {
        id: 5, title: 'Cerveja', amount: '30.00', quantity: '3.000', unit_amount: '10.00',
        position: 1, category_id: null,
        shares: [{ id: 1, user_id: 2, split_method: 'fixed', input_value: '30.00', computed_amount: '30.00' }],
      },
      {
        id: 4, title: 'Carne', amount: '60.00', quantity: '1.000', unit_amount: null,
        position: 0, category_id: 2,
        shares: [
          { id: 2, user_id: 1, split_method: 'equal', input_value: '0.00', computed_amount: '30.00' },
          { id: 3, user_id: 2, split_method: 'equal', input_value: '0.00', computed_amount: '30.00' },
        ],
      },
    ],
  };

  it('reconstrói o form em modo item ordenando por position', () => {
    const values = fromApiTransaction(apiTx);
    expect(values.split_mode).toBe('item');
    expect(values.payment_method).toBe('credit_card');
    expect(values.credit_card_id).toBe('3');
    expect(values.items.map((i) => i.title)).toEqual(['Carne', 'Cerveja']);
    expect(values.items[1].quantity).toBe(3);
    expect(values.items[1].unit_amount).toBe(10);
    expect(values.items[0].share_method).toBe('equal');
  });

  it('o round-trip preserva um deslocamento já aplicado', () => {
    // Abrir uma compra já movida para corrigir o TÍTULO e salvar não pode
    // trazê-la de volta ao ciclo natural — desfazendo, calada, uma correção que
    // alguém fez de propósito olhando a fatura real.
    const payload = toApiPayload(
      fromApiTransaction({ ...apiTx, statement_shift: 1 })
    );
    expect(payload.statement_shift).toBe(1);
  });

  it('round-trip preserva os dados essenciais do payload', () => {
    const payload = toApiPayload(fromApiTransaction(apiTx));
    expect(payload.total_amount).toBe(90);
    expect(payload.split_mode).toBe('item');
    expect(payload.payers).toEqual([
      { user_id: 1, amount: 90, payment_method: null, account_id: null },
    ]);
    expect(payload.items).toHaveLength(2);
    expect(payload.items[0]).toMatchObject({
      title: 'Carne', amount: 60, position: 0, category_id: 2,
      shares: [
        { user_id: 1, split_method: 'equal', input_value: 0 },
        { user_id: 2, split_method: 'equal', input_value: 0 },
      ],
    });
    expect(payload.items[1]).toMatchObject({
      title: 'Cerveja', amount: 30, quantity: 3, unit_amount: 10,
      shares: [{ user_id: 2, split_method: 'fixed', input_value: 30 }],
    });
  });

  it('reconstrói modo transaction com percentuais originais', () => {
    const pctTx: TransactionRead = {
      ...apiTx,
      split_mode: 'transaction',
      payment_method: 'pix',
      credit_card_id: null,
      splits: [
        { id: 1, user_id: 1, split_method: 'percentage', input_value: '70.00', computed_amount: '63.00' },
        { id: 2, user_id: 2, split_method: 'percentage', input_value: '30.00', computed_amount: '27.00' },
      ],
      items: [],
    };
    const values = fromApiTransaction(pctTx);
    expect(values.split_method).toBe('percentage');
    expect(values.splits).toEqual([
      { user_id: '1', value: 70 },
      { user_id: '2', value: 30 },
    ]);
  });
});
