import * as React from 'react';
import { Button } from '@/components/ui/button';
import { useTransactionHistory } from '@/hooks/use-transactions';
import { formatCurrency } from '@/lib/money';

const ACOES: Record<string, string> = {
  created: 'Criado', updated: 'Atualizado', deleted: 'Excluído', restored: 'Restaurado',
  cancelled: 'Cancelado', paid: 'Marcado como pago', reopened: 'Reaberto',
};

const CAMPOS: Record<string, string> = {
  title: 'Título', description: 'Observação', amount: 'Valor', currency: 'Moeda',
  date: 'Data', billing_month: 'Competência', status: 'Situação', settled_on: 'Pago em',
  payment_method: 'Forma de pagamento', card: 'Cartão',
  statement_shift: 'Deslocamento de fatura', split_mode: 'Modo de divisão',
};

const SITUACOES: Record<string, string> = {
  draft: 'Rascunho', pending: 'Pendente', confirmed: 'Confirmado',
  paid: 'Pago', cancelled: 'Cancelado',
};

function valor(campo: string, texto: string | null | undefined, moeda: string): string {
  if (texto == null || texto === '') return '—';
  if (campo === 'amount') return formatCurrency(texto, moeda);
  if (campo === 'status') return SITUACOES[texto] ?? texto;
  return texto;
}

/** Usa a mesma trilha e os mesmos nomes da tool MCP transactions_history. */
export function TransactionHistory({ transactionId, currency }: { transactionId: number; currency: string }) {
  const [aberto, setAberto] = React.useState(false);
  const { data, isLoading, isError } = useTransactionHistory(transactionId, aberto);

  return (
    <section className="border-t border-border pt-3">
      <Button type="button" variant="ghost" size="sm" onClick={() => setAberto(!aberto)}>
        {aberto ? 'Ocultar histórico' : 'Ver histórico'}
      </Button>
      {aberto && (
        <div className="mt-2 max-h-64 space-y-3 overflow-y-auto text-sm" aria-label="Histórico do lançamento">
          {isLoading && <p className="text-muted-foreground">Carregando histórico…</p>}
          {isError && <p role="alert">Não foi possível carregar o histórico.</p>}
          {data?.entries.length === 0 && <p className="text-muted-foreground">Ainda não há registros de alteração.</p>}
          {data?.entries.map((entrada, indice) => (
            <div key={`${entrada.at}-${indice}`} className="rounded-lg border border-border px-3 py-2">
              <p className="font-medium">
                {ACOES[entrada.action] ?? entrada.action} · {entrada.at}
              </p>
              <p className="text-xs text-muted-foreground">
                {entrada.by?.name ?? 'Sistema'}
                {entrada.via_ai && ` via IA${entrada.client ? ` (${entrada.client})` : ''}`}
              </p>
              {(entrada.changes?.length ?? 0) > 0 && (
                <ul className="mt-1 space-y-1 text-xs">
                  {entrada.changes?.map((mudanca, i) => (
                    <li key={`${mudanca.field}-${i}`}>
                      {CAMPOS[mudanca.field] ?? mudanca.field}: {valor(mudanca.field, mudanca.before, currency)} → {valor(mudanca.field, mudanca.after, currency)}
                    </li>
                  ))}
                </ul>
              )}
              {entrada.detail_only && (
                <p className="mt-1 text-xs text-muted-foreground">Divisão, itens ou tags alterados; o histórico não guarda os valores anteriores.</p>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
