import * as React from 'react';
import type { Bridge, ToolResultLike } from './bridge';
import { day, money, month } from './format';

/* Tipos mínimos do `structuredContent` de cada tool (o contrato completo está no
   outputSchema de cada uma, em docs/mcp/TOOLS.md). Tudo opcional: o componente
   degrada para "sem detalhes" em vez de quebrar com um campo que não veio. */
interface Ref { id: number; name: string }
interface PersonAmount { person: Ref; amount: string; is_me?: boolean }
interface Tx {
  id: number; title: string; amount: string; currency: string; date: string; status: string; settled: boolean;
  space: Ref; card?: Ref | null; statement?: { month: string } | null; category?: Ref | null;
  split?: PersonAmount[]; payers?: PersonAmount[]; my_share: string; app_url?: string;
  installment?: { number: number; of: number } | null; tags?: string[];
}
interface Brief { id: number; title: string; amount: string; currency: string; date: string; installment?: string | null; card?: string | null }

type Data = Record<string, unknown>;

function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'ok' | 'warn' | 'bad' }) {
  const cores = {
    neutral: 'bg-muted text-muted-fg',
    ok: 'bg-muted text-income',
    warn: 'bg-warn-bg text-warn',
    bad: 'bg-muted text-expense',
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cores}`}>{children}</span>;
}

function Linha({ rotulo, valor }: { rotulo: string; valor: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-muted-fg">{rotulo}</span>
      <span className="num text-right font-medium">{valor}</span>
    </div>
  );
}

function AbrirNoApp({ url, bridge }: { url?: string; bridge: Bridge }) {
  if (!url) return null;
  return (
    <button
      type="button"
      onClick={() => bridge.openLink(url)}
      className="mt-3 w-full rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted"
    >
      Abrir no Controle Financeiro
    </button>
  );
}

function TransactionView({ data, bridge, appUrl }: { data: Data; bridge: Bridge; appUrl?: string }) {
  const tx = data.transaction as Tx | undefined;
  if (!tx) return null;
  const parcelas = (data.installments as Brief[] | undefined) ?? [];
  const divisao = tx.split ?? [];
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold">{tx.title}</p>
          <p className="text-xs text-muted-fg">{day(tx.date)} · {tx.space?.name}</p>
        </div>
        <p className="num shrink-0 text-lg font-semibold">{money(tx.amount, tx.currency)}</p>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {tx.status === 'cancelled' ? <Pill tone="bad">cancelada</Pill>
          : tx.card ? <Pill>cartão {tx.card.name}{tx.statement ? ` · fatura ${month(tx.statement.month)}` : ''}</Pill>
          : <Pill tone={tx.settled ? 'ok' : 'warn'}>{tx.settled ? 'paga' : 'a pagar'}</Pill>}
        {tx.category && <Pill>{tx.category.name}</Pill>}
        {tx.installment && <Pill>parcela {tx.installment.number}/{tx.installment.of}</Pill>}
        {(tx.tags ?? []).map((t) => <Pill key={t}>#{t}</Pill>)}
        {data.replayed === true && <Pill tone="warn">já registrada antes</Pill>}
      </div>
      {divisao.length > 1 && (
        <div className="mt-3 rounded-lg border border-border p-3">
          <p className="mb-1 text-xs font-medium text-muted-fg">Divisão</p>
          {divisao.map((p) => (
            <Linha key={p.person.id} rotulo={p.is_me ? `${p.person.name} (você)` : p.person.name} valor={money(p.amount, tx.currency)} />
          ))}
        </div>
      )}
      <div className="mt-2 border-t border-border pt-2">
        <Linha rotulo="Sua parte" valor={money(tx.my_share, tx.currency)} />
      </div>
      {parcelas.length > 1 && (
        <p className="mt-1 text-xs text-muted-fg">
          {parcelas.length} parcelas de {money(parcelas[parcelas.length - 1].amount, tx.currency)} · última em {day(parcelas[parcelas.length - 1].date)}
        </p>
      )}
      <AbrirNoApp url={appUrl ?? tx.app_url} bridge={bridge} />
    </div>
  );
}

function StatementView({ data, bridge, appUrl }: { data: Data; bridge: Bridge; appUrl?: string }) {
  const moeda = (data.currency as string) ?? 'BRL';
  const categorias = (data.by_category as Array<{ category: string; amount: string }> | undefined) ?? [];
  const total = Number(data.total ?? 0) || 1;
  const compras = ((data.purchases as Brief[] | undefined) ?? []).slice(0, 6);
  const card = data.card as Ref | undefined;
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-base font-semibold">Fatura {month(data.month as string)} · {card?.name}</p>
          <p className="text-xs text-muted-fg">vence em {day(data.due_date as string)}</p>
        </div>
        <p className="num text-lg font-semibold">{money(data.total as string, moeda)}</p>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {data.overdue === true ? <Pill tone="bad">vencida</Pill> : <Pill>{String(data.status)}</Pill>}
        <Pill tone={Number(data.balance) > 0 ? 'warn' : 'ok'}>a pagar {money(data.balance as string, moeda)}</Pill>
      </div>
      {categorias.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {categorias.slice(0, 5).map((c) => (
            <div key={c.category}>
              <div className="flex justify-between text-xs"><span>{c.category}</span><span className="num">{money(c.amount, moeda)}</span></div>
              <div className="h-1.5 rounded-full bg-muted">
                <div className="h-1.5 rounded-full bg-brand" style={{ width: `${Math.min(100, (Number(c.amount) / total) * 100)}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
      {compras.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          {compras.map((p) => (
            <Linha key={p.id} rotulo={`${day(p.date)} ${p.title}${p.installment ? ` (${p.installment})` : ''}`} valor={money(p.amount, moeda)} />
          ))}
        </div>
      )}
      <AbrirNoApp url={appUrl} bridge={bridge} />
    </div>
  );
}

function SummaryView({ data, bridge, appUrl }: { data: Data; bridge: Bridge; appUrl?: string }) {
  const moeda = (data.currency as string) ?? 'BRL';
  const cats = (data.my_categories as Array<{ category: string; amount: string }> | undefined) ?? [];
  const resultado = Number(data.result ?? 0);
  return (
    <div>
      <p className="text-base font-semibold">Resumo de {month(data.month as string)}</p>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {[
          ['Renda', data.income],
          ['Seu consumo', data.consumption],
          ['Saiu do caixa', data.cash_out],
          ['A pagar', data.payables_total],
        ].map(([rotulo, valor]) => (
          <div key={rotulo as string} className="rounded-lg border border-border p-2">
            <p className="text-[11px] text-muted-fg">{rotulo as string}</p>
            <p className="num font-semibold">{money(valor as string, moeda)}</p>
          </div>
        ))}
      </div>
      <Linha rotulo="Resultado do mês" valor={<span className={resultado >= 0 ? 'text-income' : 'text-expense'}>{money(data.result as string, moeda)}</span>} />
      {cats.length > 0 && (
        <div className="mt-2 border-t border-border pt-2">
          {cats.slice(0, 6).map((c) => <Linha key={c.category} rotulo={c.category} valor={money(c.amount, moeda)} />)}
        </div>
      )}
      <AbrirNoApp url={appUrl} bridge={bridge} />
    </div>
  );
}

function BulkPreviewView({ data, bridge }: { data: Data; bridge: Bridge }) {
  const [estado, setEstado] = React.useState<'parado' | 'enviando' | 'feito' | 'erro'>('parado');
  const [mensagem, setMensagem] = React.useState('');
  const acao = data.action as string;
  const token = data.confirmation_token as string | null;
  const totais = (data.totals as Array<{ currency: string; amount: string }> | undefined) ?? [];
  const amostra = (data.sample as Brief[] | undefined) ?? [];
  const categoria = data.category as Ref | undefined;
  const anexos = Number(data.attachments ?? 0);

  const confirmar = async () => {
    if (!token) return;
    setEstado('enviando');
    try {
      const nome = acao === 'delete' ? 'transactions_bulk_delete' : 'transactions_bulk_categorize';
      const r = await bridge.callTool(nome, { confirmation_token: token });
      if (r.isError) throw new Error(r.content?.[0]?.text?.split('\n')[0] ?? 'A operação foi recusada.');
      const feito = (r.structuredContent ?? {}) as { count?: number };
      setMensagem(acao === 'delete' ? `${feito.count ?? 0} lançamento(s) excluído(s).` : `${feito.count ?? 0} lançamento(s) categorizado(s).`);
      setEstado('feito');
    } catch (e) {
      setMensagem(e instanceof Error ? e.message : 'Não foi possível concluir.');
      setEstado('erro');
    }
  };

  return (
    <div>
      <p className="text-base font-semibold">
        {acao === 'delete' ? 'Excluir' : `Categorizar como ${categoria?.name ?? '—'}`} · {String(data.count ?? 0)} lançamento(s)
      </p>
      <p className="num text-sm text-muted-fg">{totais.map((t) => money(t.amount, t.currency)).join(' + ') || 'nada'}</p>
      {anexos > 0 && (
        <p className="mt-2 rounded-lg bg-warn-bg px-3 py-2 text-xs text-warn">{anexos} anexo(s) serão apagados para sempre.</p>
      )}
      {amostra.length > 0 && (
        <div className="mt-2 border-t border-border pt-2">
          {amostra.map((b) => <Linha key={b.id} rotulo={`${day(b.date)} ${b.title}`} valor={money(b.amount, b.currency)} />)}
        </div>
      )}
      {Number(data.ineligible_count ?? 0) > 0 && (
        <p className="mt-1 text-xs text-muted-fg">{String(data.ineligible_count)} ficaram de fora (pagos, de outra pessoa ou já categorizados).</p>
      )}
      {token && estado !== 'feito' && (
        <button
          type="button"
          disabled={estado === 'enviando'}
          onClick={confirmar}
          className={`mt-3 w-full rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-60 ${acao === 'delete' ? 'bg-expense text-white' : 'bg-brand text-brand-fg'}`}
        >
          {estado === 'enviando' ? 'Enviando…' : acao === 'delete' ? 'Confirmar exclusão' : 'Confirmar categorização'}
        </button>
      )}
      {mensagem && <p className={`mt-2 text-sm ${estado === 'erro' ? 'text-expense' : 'text-income'}`} role="status">{mensagem}</p>}
    </div>
  );
}

export function Widget({ bridge }: { bridge: Bridge }) {
  const [resultado, setResultado] = React.useState<ToolResultLike | null>(null);
  const [tema, setTema] = React.useState<'light' | 'dark'>('light');

  React.useEffect(() => {
    bridge.onResult(setResultado);
    bridge.onTheme(setTema);
  }, [bridge]);

  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', tema === 'dark');
  }, [tema]);

  if (!resultado) return <p className="p-3 text-sm text-muted-fg">Carregando…</p>;
  const data = (resultado.structuredContent ?? {}) as Data;
  const meta = (resultado._meta ?? {}) as { view?: string; app_url?: string };
  if (resultado.isError) return null; // o texto do erro já está na conversa

  const vista = meta.view
    ?? (data.transaction ? 'transaction' : data.confirmation_token !== undefined ? 'bulk_preview' : data.purchases ? 'statement' : data.my_categories ? 'summary' : '');
  return (
    <div className="rounded-xl bg-bg p-4 text-fg">
      {vista === 'transaction' && <TransactionView data={data} bridge={bridge} appUrl={meta.app_url} />}
      {vista === 'statement' && <StatementView data={data} bridge={bridge} appUrl={meta.app_url} />}
      {vista === 'summary' && <SummaryView data={data} bridge={bridge} appUrl={meta.app_url} />}
      {vista === 'bulk_preview' && <BulkPreviewView data={data} bridge={bridge} />}
    </div>
  );
}
