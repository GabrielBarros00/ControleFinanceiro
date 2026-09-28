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
  description: '',
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
  merchant_name: '',
  merchant_initial: '',
  split_mode: 'transaction',
  split_method: 'equal',
  splits: [{ user_id: '1', value: 0 }],
  items: [],
  adjustments: [],
  // Despesa de hoje nasce liquidada (ADR 0029) — o padrão do formulário.
  settled: true,
};

// Linha ANTIGA por padrão (`nova: false`, sem unidade): a medida só é exigida da
// linha que nasce no formulário, e os casos dela têm testes próprios abaixo.
const item = (over: Partial<TransactionFormValues['items'][number]> = {}) => ({
  title: 'Carne',
  description: '',
  quantity: 1,
  unit: null as TransactionFormValues['items'][number]['unit'],
  unit_amount: null,
  amount: 60,
  nova: false,
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

  // ---- A linha da nota (ADR 0040) ----
  const nova = (over: Partial<TransactionFormValues['items'][number]> = {}) =>
    item({ nova: true, unit: 'kg', ...over });
  const issues = (items: ReturnType<typeof item>[]) => {
    const r = transactionFormSchema.safeParse({ ...itemBase, total_amount: items.reduce((a, i) => a + i.amount, 0), items });
    return r.success ? [] : r.error.issues.map((i) => ({ path: i.path.join('.'), message: i.message }));
  };

  it('linha nova exige a unidade e o preço unitário', () => {
    expect(issues([nova({ unit: null, unit_amount: null, amount: 60 })])).toEqual([
      { path: 'items.0.unit', message: 'Escolha a unidade' },
      { path: 'items.0.unit_amount', message: 'Informe o preço unitário da nota' },
    ]);
  });

  it('linha antiga, sem medida, continua editável (decisão do dono)', () => {
    expect(issues([item({ unit: null, unit_amount: null, amount: 60 })])).toEqual([]);
  });

  it('o total impresso vale com até 1 centavo de diferença da conta', () => {
    // 1,235 kg × R$ 39,90 = 49,2765: a balança que arredonda imprime 49,28, a
    // que trunca imprime 49,27 — as duas notas são verdadeiras.
    expect(issues([nova({ quantity: 1.235, unit_amount: 39.9, amount: 49.28 })])).toEqual([]);
    expect(issues([nova({ quantity: 1.235, unit_amount: 39.9, amount: 49.27 })])).toEqual([]);
    // O litro com 3 casas.
    expect(issues([nova({ quantity: 40.123, unit: 'l', unit_amount: 5.899, amount: 236.69 })])).toEqual([]);
  });

  it('a conta não usa ponto flutuante: 2,050 × R$ 19,90 fecha R$ 40,80', () => {
    // A versão anterior calculava 2.05 * 1990 = 4079,4999… → R$ 40,79 e
    // recusava a nota verdadeira de R$ 40,80.
    expect(issues([nova({ quantity: 2.05, unit_amount: 19.9, amount: 40.8 })])).toEqual([]);
  });

  it('diferença maior que 1 centavo é leitura errada, e a mensagem diz a conta', () => {
    const [problema] = issues([nova({ quantity: 1.235, unit_amount: 39.9, amount: 49.4 })]);
    expect(problema.path).toBe('items.0.amount');
    expect(problema.message).toMatch(/^1,235 kg × unitário dá R\$\s49,28 — confira a nota/);
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
        title: 'Cerveja', description: null, amount: 30, quantity: 3, unit: null, unit_amount: 10, position: 0, category_id: null,
        shares: [{ user_id: 2, split_method: 'equal', input_value: 0 }],
      },
      {
        title: 'Carne', description: null, amount: 60, quantity: 1, unit: null, unit_amount: null, position: 1, category_id: null,
        shares: [{ user_id: 1, split_method: 'fixed', input_value: 60 }],
      },
    ]);
  });

  it('modo item: a unidade vai à API e a marca de linha nova não', () => {
    const payload = toApiPayload({
      ...baseValues,
      split_mode: 'item',
      splits: [],
      items: [item({ nova: true, unit: 'kg', quantity: 1.235, unit_amount: 39.9, amount: 49.27 })],
    });
    expect(payload.items[0]).toEqual({
      title: 'Carne', description: null, amount: 49.27, quantity: 1.235, unit: 'kg', unit_amount: 39.9,
      position: 0, category_id: null,
      shares: [{ user_id: 1, split_method: 'equal', input_value: 0 }],
    });
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
    // Linhas que vêm do servidor são antigas: a medida não é exigida delas.
    expect(values.items.map((i) => i.nova)).toEqual([false, false]);
  });

  it('reconstrói a unidade e o unitário com 4 casas', () => {
    const values = fromApiTransaction({
      ...apiTx,
      items: [{ ...apiTx.items![0], quantity: '40.123', unit: 'l', unit_amount: '5.8990', amount: '236.69' }],
    });
    expect(values.items[0]).toMatchObject({ quantity: 40.123, unit: 'l', unit_amount: 5.899, amount: 236.69 });
    // Unidade fora do vocabulário não vira valor inválido no <select>.
    const estranha = fromApiTransaction({ ...apiTx, items: [{ ...apiTx.items![0], unit: 'cx' }] });
    expect(estranha.items[0].unit).toBeNull();
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

describe('estabelecimento (ADR 0038): só vai quando mudou', () => {
  const campos = (v: TransactionFormValues) => {
    const p = toApiPayload(v) as Record<string, unknown>;
    return { merchant_name: p.merchant_name, merchant_id: p.merchant_id, tem_id: 'merchant_id' in p };
  };

  it('criação: vazio não manda nada (o servidor liga pelo apelido do título); nome manda o nome', () => {
    expect(campos(baseValues)).toEqual({ merchant_name: undefined, merchant_id: undefined, tem_id: false });
    expect(campos({ ...baseValues, merchant_name: '  Padaria  ' }).merchant_name).toBe('Padaria');
  });

  it('edição: igual não manda; apagar desvincula com merchant_id nulo; trocar manda o nome novo', () => {
    const editando = { ...baseValues, merchant_name: 'Padaria', merchant_initial: 'Padaria' };
    expect(campos(editando)).toEqual({ merchant_name: undefined, merchant_id: undefined, tem_id: false });
    expect(campos({ ...editando, merchant_name: '' })).toEqual({ merchant_name: undefined, merchant_id: null, tem_id: true });
    expect(campos({ ...editando, merchant_name: 'Mercado' }).merchant_name).toBe('Mercado');
  });
});

describe('observação (description)', () => {
  it('vai aparada; vazia vai null, para a edição conseguir apagar', () => {
    expect(toApiPayload({ ...baseValues, description: '  Verduras  ' }).description).toBe('Verduras');
    expect(toApiPayload({ ...baseValues, description: '   ' }).description).toBeNull();
  });

  it('a edição abre com a observação do lançamento', () => {
    const tx: TransactionRead = {
      id: 231, workspace_id: 1, title: 'Coca lata', currency: 'BRL', total_amount: '5.70',
      transaction_date: '2026-09-24T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
      credit_card_id: 2, split_mode: 'transaction', payment_method: 'credit_card', created_at: '', updated_at: '',
      tags: [], adjustments: [], items: [], payers: [{ id: 1, user_id: 1, amount: '5.70' }],
      splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '0', computed_amount: '5.70' }],
    };
    expect(fromApiTransaction({ ...tx, description: 'Coca lata comprada na Duff' }).description).toBe('Coca lata comprada na Duff');
    expect(fromApiTransaction({ ...tx, description: null }).description).toBe('');
  });
});

/*
 * A nota na divisão PELA DESPESA — o lançamento #302, gravado pela IA.
 *
 * O MCP grava assim toda nota em que nenhum item tem divisão própria
 * (`plan_items`): itens com medida, ajustes, e a despesa dividida pelo total. A
 * tela só conhecia itens na divisão por item: aqui ela lia o primeiro item como
 * o item-sombra da categoria, e a edição abria sem nota nenhuma. Pior, salvar —
 * até para trocar o título — mandava o item-sombra no lugar do combo e nenhum
 * ajuste, e a edição completa apagava os dois.
 */
describe('nota na divisão pela despesa', () => {
  const delivery: TransactionRead = {
    id: 302, workspace_id: 1, title: "McDonald's", currency: 'BRL', total_amount: '37.41',
    description: 'Pedido nº 8509.',
    transaction_date: '2026-09-27T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
    credit_card_id: 1, split_mode: 'transaction', payment_method: 'credit_card', created_at: '', updated_at: '',
    tags: [],
    payers: [{ id: 1, user_id: 1, amount: '37.41' }],
    splits: [{ id: 1, user_id: 1, split_method: 'equal', input_value: '0.00', computed_amount: '37.41' }],
    items: [{
      id: 7, title: 'Combo: Big Mac + Quarterão', description: 'Combo com 2 sanduíches.',
      amount: '37.90', quantity: '1.000', unit: 'un', unit_amount: '37.9000', position: 0, category_id: 1, shares: [],
    }],
    adjustments: [
      { id: 1, type: 'discount', amount: '-9.47', description: 'Desconto do pedido' },
      { id: 2, type: 'shipping', amount: '7.99', description: 'Taxa de entrega' },
      { id: 3, type: 'other', amount: '0.99', description: 'Taxa de serviço' },
    ],
  };

  it('a edição abre com os itens e os ajustes da nota', () => {
    const v = fromApiTransaction(delivery);
    expect(v.split_mode).toBe('transaction');
    // A categoria mora no item: não há item-sombra para lê-la.
    expect(v.category_id).toBe('');
    expect(v.items).toHaveLength(1);
    expect(v.items[0]).toMatchObject({
      title: 'Combo: Big Mac + Quarterão', description: 'Combo com 2 sanduíches.',
      amount: 37.9, quantity: 1, unit: 'un', unit_amount: 37.9, category_id: '1', shares: [],
    });
    expect(v.adjustments).toEqual([
      { type: 'discount', description: 'Desconto do pedido', amount: 9.47, reduz: true },
      { type: 'shipping', description: 'Taxa de entrega', amount: 7.99, reduz: false },
      { type: 'other', description: 'Taxa de serviço', amount: 0.99, reduz: false },
    ]);
    // Item da nota na divisão pela despesa não tem participantes, e isso é válido.
    expect(transactionFormSchema.safeParse(v).success).toBe(true);
  });

  it('salvar sem mexer devolve a nota inteira, com o sinal de cada ajuste', () => {
    const payload = toApiPayload(fromApiTransaction(delivery));
    expect(payload.split_mode).toBe('transaction');
    expect(payload.splits).toEqual([{ user_id: 1, split_method: 'equal', input_value: 0 }]);
    expect(payload.items).toEqual([{
      title: 'Combo: Big Mac + Quarterão', description: 'Combo com 2 sanduíches.', amount: 37.9,
      quantity: 1, unit: 'un', unit_amount: 37.9, position: 0, category_id: 1,
    }]);
    expect(payload.adjustments).toEqual([
      { type: 'discount', description: 'Desconto do pedido', amount: -9.47 },
      { type: 'shipping', description: 'Taxa de entrega', amount: 7.99 },
      { type: 'other', description: 'Taxa de serviço', amount: 0.99 },
    ]);
  });

  it('o item-sombra continua sendo só a categoria', () => {
    const simples: TransactionRead = {
      ...delivery,
      adjustments: [],
      items: [{
        id: 8, title: "McDonald's", description: null, amount: '37.41', quantity: '1.000', unit: null,
        unit_amount: null, position: 0, category_id: 4, shares: [],
      }],
    };
    const v = fromApiTransaction(simples);
    expect(v.items).toEqual([]);
    expect(v.category_id).toBe('4');
    const payload = toApiPayload(v);
    expect(payload.items).toEqual([{ title: "McDonald's", amount: 37.41, quantity: 1, position: 0, category_id: 4 }]);
    expect(payload.adjustments).toEqual([]);
  });

  it('itens + ajustes que não fecham o total: a mensagem mostra a conta', () => {
    const r = transactionFormSchema.safeParse({ ...fromApiTransaction(delivery), total_amount: 40 });
    expect(r.success).toBe(false);
    expect(r.error!.issues.map((i) => i.message).join('\n'))
      .toMatch(/Itens \(R\$\s37,90\) \+ ajustes \(.*0,49\) dão R\$\s37,41 de R\$\s40,00 — faltam R\$\s2,59/);
  });

  it('ajuste sem item é recusado, e parcelado não leva ajuste nem nota pela despesa', () => {
    const v = fromApiTransaction(delivery);
    const semItens = transactionFormSchema.safeParse({ ...v, items: [] });
    expect(semItens.error!.issues.map((i) => i.path.join('.'))).toContain('adjustments');

    const parcelado = transactionFormSchema.safeParse({ ...v, installments: 3 });
    const caminhos = parcelado.error!.issues.map((i) => i.path.join('.'));
    expect(caminhos).toContain('adjustments');
    expect(caminhos).toContain('items');
  });

  it('na divisão por item, os ajustes também entram na soma', () => {
    const porItem: TransactionFormValues = {
      ...baseValues,
      total_amount: 85,
      split_mode: 'item',
      splits: [],
      items: [item(), item({ title: 'Cerveja', amount: 30, shares: [{ user_id: '2', value: 0 }] })],
      adjustments: [{ type: 'discount', description: '', amount: 5, reduz: true }],
    };
    expect(transactionFormSchema.safeParse(porItem).success).toBe(true);
    expect(toApiPayload(porItem).adjustments).toEqual([{ type: 'discount', description: null, amount: -5 }]);
    // Ainda exige participantes por item.
    const semPartes = transactionFormSchema.safeParse({ ...porItem, items: [item({ amount: 90, shares: [] })] });
    expect(semPartes.error!.issues.map((i) => i.path.join('.'))).toContain('items.0.shares');
  });
});

/*
 * Compra em moeda estrangeira.
 *
 * O formulário edita a compra na moeda DELA (o total em US$, e o servidor
 * reconverte ao salvar), mas itens, ajustes, pagadores e valores fixos vêm
 * gravados na moeda do espaço. A edição abria "US$ 50" com itens de "US$ 290":
 * a soma nunca fechava e não havia como salvar.
 */
describe('compra em moeda estrangeira', () => {
  const emDolar: TransactionRead = {
    id: 40, workspace_id: 1, title: 'Amazon', currency: 'BRL', total_amount: '290.00',
    original_amount: '50.00', original_currency: 'USD', exchange_rate: '5.80',
    transaction_date: '2026-09-10T15:00:00Z', billing_month: '2026-09', status: 'confirmed',
    credit_card_id: null, split_mode: 'item', payment_method: 'pix', created_at: '', updated_at: '',
    tags: [],
    payers: [
      { id: 1, user_id: 1, amount: '174.00' },
      { id: 2, user_id: 2, amount: '116.00' },
    ],
    splits: [],
    items: [
      {
        id: 1, title: 'Fone', amount: '174.00', quantity: '1', unit: 'un', unit_amount: '174.0000', position: 0,
        category_id: null,
        shares: [{ id: 1, user_id: 1, split_method: 'fixed', input_value: '174.00', computed_amount: '174.00' }],
      },
      {
        id: 2, title: 'Cabo', amount: '145.00', quantity: '1', unit: 'un', unit_amount: '145.0000', position: 1,
        category_id: null,
        shares: [{ id: 2, user_id: 2, split_method: 'equal', input_value: '0', computed_amount: '145.00' }],
      },
    ],
    adjustments: [{ id: 1, type: 'discount', amount: '-29.00', description: 'Cupom' }],
  };

  it('abre itens, ajustes, pagadores e valores fixos na moeda da compra', () => {
    const v = fromApiTransaction(emDolar);
    expect(v.currency).toBe('USD');
    expect(v.total_amount).toBe(50);
    expect(v.items.map((i) => [i.amount, i.unit_amount])).toEqual([[30, 30], [25, 25]]);
    expect(v.items[0].shares).toEqual([{ user_id: '1', value: 30 }]);
    expect(v.adjustments).toEqual([{ type: 'discount', description: 'Cupom', amount: 5, reduz: true }]);
    expect(v.payers.map((p) => p.amount)).toEqual([30, 20]);
    expect(transactionFormSchema.safeParse(v).success).toBe(true);
  });

  it('o centavo do arredondamento vai para o maior item, e a soma fecha', () => {
    // R$ 33,33 = US$ 10,00: cada item de R$ 11,11 vira US$ 3,333… → 3,33 × 3 = 9,99.
    const v = fromApiTransaction({
      ...emDolar, total_amount: '33.33', original_amount: '10.00', adjustments: [],
      payers: [{ id: 1, user_id: 1, amount: '33.33' }],
      items: [0, 1, 2].map((n) => ({
        id: n, title: `Item ${n}`, amount: '11.11', quantity: '1', unit: null, unit_amount: null, position: n,
        category_id: null, shares: [{ id: n, user_id: 1, split_method: 'equal' as const, input_value: '0', computed_amount: '11.11' }],
      })),
    });
    expect(v.items.map((i) => i.amount)).toEqual([3.34, 3.33, 3.33]);
    expect(transactionFormSchema.safeParse(v).success).toBe(true);
  });

  it('na divisão pela despesa, o valor fixo de cada um também volta', () => {
    const v = fromApiTransaction({
      ...emDolar, split_mode: 'transaction', items: [], adjustments: [],
      splits: [
        { id: 1, user_id: 1, split_method: 'fixed', input_value: '174.00', computed_amount: '174.00' },
        { id: 2, user_id: 2, split_method: 'fixed', input_value: '116.00', computed_amount: '116.00' },
      ],
    });
    expect(v.splits).toEqual([{ user_id: '1', value: 30 }, { user_id: '2', value: 20 }]);
    expect(transactionFormSchema.safeParse(v).success).toBe(true);
  });
});
