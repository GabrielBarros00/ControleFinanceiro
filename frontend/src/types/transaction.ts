// Espelho do TransactionRead da API. Decimais chegam como string (Pydantic v2
// serializa Decimal como string no JSON) — converta com parseFloat na borda.
export type SplitMethod = 'equal' | 'percentage' | 'fixed';
export type SplitMode = 'transaction' | 'item';
export type PaymentMethod =
  | 'credit_card'
  | 'debit_card'
  | 'pix'
  | 'cash'
  | 'bank_transfer'
  | 'boleto'
  | 'other';
export type TransactionStatus = 'draft' | 'pending' | 'confirmed' | 'paid' | 'cancelled';

export interface TransactionPayerRead {
  id: number;
  user_id: number;
  amount: string;
  payment_method?: string | null;
  account_id?: number | null;
}

export type AdjustmentType =
  | 'discount'
  | 'tax'
  | 'tip'
  | 'shipping'
  | 'cashback'
  | 'rounding'
  | 'other';

export interface TransactionAdjustmentRead {
  id: number;
  type: AdjustmentType;
  description?: string | null;
  amount: string;
}

export interface TransactionSplitRead {
  id: number;
  user_id: number;
  split_method: SplitMethod;
  input_value: string;
  computed_amount: string;
}

export interface TransactionItemShareRead {
  id: number;
  user_id: number;
  split_method: SplitMethod;
  input_value: string;
  computed_amount: string;
}

export interface TransactionItemRead {
  id: number;
  title: string;
  description?: string | null;
  amount: string;
  quantity: string;
  unit_amount?: string | null;
  position: number;
  category_id?: number | null;
  shares: TransactionItemShareRead[];
}

export interface TransactionTagRead {
  id: number;
  name: string;
  color?: string | null;
}

export interface TransactionRead {
  id: number;
  workspace_id: number;
  title: string;
  description?: string | null;
  currency: string;
  total_amount: string;
  transaction_date: string;
  billing_month?: string | null;
  status: TransactionStatus;
  /**
   * Quando o dinheiro saiu de fato; `null` = ainda a pagar (ADR 0029).
   *
   * Eixo separado do `status`: aquele é competência (a despesa existe, entra em
   * rateio e relatórios), este é caixa. O boleto de julho pago em 14 de agosto é
   * gasto de julho e dinheiro que saiu em agosto.
   */
  settled_at?: string | null;
  credit_card_id?: number | null;
  statement_id?: number | null;
  split_mode: SplitMode;
  payment_method?: PaymentMethod | null;
  installment_no?: number | null;
  installments_of?: number | null;
  installment_group_id?: string | null;
  // Conversão de moeda: original congelado quando o lançamento foi estrangeiro
  original_amount?: string | null;
  original_currency?: string | null;
  exchange_rate?: string | null;
  iof_rate?: string | null;
  rate_source?: string | null;
  created_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
  payers: TransactionPayerRead[];
  splits: TransactionSplitRead[];
  items: TransactionItemRead[];
  adjustments: TransactionAdjustmentRead[];
  tags: TransactionTagRead[];
}
