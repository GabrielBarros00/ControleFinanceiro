/**
 * Tipos mínimos do `structuredContent` e do `_meta` que o componente desenha.
 *
 * O contrato completo é o outputSchema de cada tool (docs/mcp/TOOLS.md). Aqui tudo
 * é opcional onde pode faltar: o componente degrada para "sem detalhes" em vez de
 * quebrar com um campo que não veio.
 */
export interface Ref { id: number; name: string }
export interface PessoaValor { person: Ref; amount: string; is_me?: boolean }

export interface Item {
  title: string; description?: string | null; quantity: string; unit_amount?: string | null; amount: string;
  category?: Ref | null; shares?: PessoaValor[]; my_share?: string | null;
}
export interface Ajuste { type: string; amount: string; description?: string | null }
export interface Arquivo { id: number; filename: string; content_type: string; size_bytes: number; uploaded_by?: Ref | null; uploaded_on?: string | null }
export interface Compra {
  group_id: string; title: string; amount: string; currency: string; installments: number; paid_installments: number;
  split?: PessoaValor[]; my_share: string; items?: Item[];
}

export interface Lancamento {
  id: number; space?: Ref | null; title: string; description?: string | null; date: string; billing_month?: string | null;
  amount: string; currency: string; status: string; settled: boolean; settled_on?: string | null;
  payment_method?: string | null; card?: Ref | null; statement?: { id: number; month: string } | null;
  category?: Ref | null; categories?: Ref[]; tags?: string[];
  installment?: { number: number; of: number; group_id?: string | null } | null;
  split_mode?: string; payers?: PessoaValor[]; split?: PessoaValor[]; my_share: string;
  items?: Item[]; adjustments?: Ajuste[]; purchase?: Compra | null;
  created_by?: Ref | null; foreign?: { original_amount: string; original_currency: string } | null;
  attachments?: number; files?: Arquivo[]; version?: string; app_url?: string;
}

export interface Resumo {
  id: number; space?: Ref | null; date: string; title: string; amount: string; currency: string; my_share: string;
  status: string; settled: boolean; payment_method?: string | null; card?: string | null; category?: string | null;
  installment?: string | null; tags?: string[]; statement_amount?: string;
}

export interface Formulario {
  space_id: number;
  categories: Ref[]; tags: Ref[]; cards: Ref[]; accounts: Array<Ref & { currency: string }>;
  people: Array<Ref & { me: boolean }>; payment_methods: string[];
}

export interface Desfazer { tool: string; args: Record<string, unknown>; label?: string }

export interface Meta {
  view?: string; mode?: string; tool?: string; app_url?: string; can_edit?: boolean;
  form?: Formulario; forms?: Record<string, Formulario>; undo?: Desfazer; undo_each?: Array<Record<string, unknown>>;
  query?: { tool: string; args: Record<string, unknown> };
  accounts?: Array<Ref & { currency: string }>; can_pay?: boolean; card_id?: number;
}

export type Dados = Record<string, unknown>;
