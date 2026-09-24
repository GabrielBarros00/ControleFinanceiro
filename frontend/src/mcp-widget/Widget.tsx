/** @jsxImportSource preact */
import type { ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import type { Bridge, Tema, ToolResultLike } from './bridge';
import { day, money, monthLong, percent, plural, shortDay } from './format';

/* Tipos mínimos do `structuredContent` de cada tool (o contrato completo está no
   outputSchema de cada uma, em docs/mcp/TOOLS.md). Tudo opcional: o componente
   degrada para "sem detalhes" em vez de quebrar com um campo que não veio. */
interface Ref { id: number; name: string }
interface PersonAmount { person: Ref; amount: string; is_me?: boolean }
interface Foreign { original_amount: string; original_currency: string }
interface Tx {
  id: number; title: string; amount: string; currency: string; date: string; status: string; settled: boolean;
  space: Ref; card?: Ref | null; statement?: { month: string } | null; category?: Ref | null;
  split?: PersonAmount[]; my_share: string; app_url?: string; foreign?: Foreign | null;
  installment?: { number: number; of: number } | null; tags?: string[];
}
interface Brief {
  id: number; title: string; amount: string; currency: string; date: string;
  installment?: string | null; statement_amount?: string;
}
interface Share { category: string; amount: string }

type Data = Record<string, unknown>;
type Tom = 'neutro' | 'ok' | 'aviso' | 'perigo';

const SITUACAO_DA_FATURA: Record<string, [string, Tom]> = {
  open: ['Aberta', 'neutro'],
  closed: ['Fechada', 'aviso'],
  paid: ['Paga', 'ok'],
  overdue: ['Vencida', 'perigo'],
  not_created: ['Sem compras', 'neutro'],
};

function Etiqueta({ children, tom = 'neutro' }: { children: ComponentChildren; tom?: Tom }) {
  const cores = {
    neutro: 'bg-muted text-muted-fg',
    ok: 'bg-ok-bg text-income',
    aviso: 'bg-warn-bg text-warn',
    perigo: 'bg-danger-bg text-expense',
  }[tom];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cores}`}>{children}</span>;
}

function Linha({ rotulo, valor, fraco }: { rotulo: ComponentChildren; valor: ComponentChildren; fraco?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className={`min-w-0 truncate ${fraco ? 'text-muted-fg' : ''}`}>{rotulo}</span>
      <span className="num shrink-0 text-right font-medium">{valor}</span>
    </div>
  );
}

/** Barra de participação: a parte de cada categoria no total, com a porcentagem escrita. */
function Barras({ itens, total, moeda }: { itens: Share[]; total: string | number; moeda: string }) {
  return (
    <ul className="mt-3 space-y-2">
      {itens.map((c) => {
        const p = percent(c.amount, total);
        return (
          <li key={c.category}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="min-w-0 truncate">{c.category}</span>
              <span className="num shrink-0 text-muted-fg">{p}% · <span className="text-fg">{money(c.amount, moeda)}</span></span>
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-muted" aria-hidden="true">
              <div className="h-1.5 rounded-full bg-accent" style={{ width: `${p}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function AbrirNoApp({ url, bridge }: { url?: string; bridge: Bridge }) {
  if (!url) return null;
  return (
    <button
      type="button"
      onClick={() => bridge.openLink(url)}
      className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-accent"
    >
      Abrir no Controle Financeiro
      {/* SVG, não o caractere "↗": no Windows ele vira emoji colorido. */}
      <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 2h6v6M10 2 3 9" />
      </svg>
    </button>
  );
}

function TransactionView({ data, bridge, appUrl }: { data: Data; bridge: Bridge; appUrl?: string }) {
  const tx = data.transaction as Tx | undefined;
  if (!tx) return null;
  const parcelas = (data.installments as Brief[] | undefined) ?? [];
  const divisao = tx.split ?? [];
  const cancelada = tx.status === 'cancelled';
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`truncate text-base font-semibold ${cancelada ? 'line-through opacity-60' : ''}`}>{tx.title}</p>
          <p className="text-xs text-muted-fg">{day(tx.date)} · {tx.space?.name}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="num text-lg font-semibold">{money(tx.amount, tx.currency)}</p>
          {tx.foreign && (
            <p className="num text-[11px] text-muted-fg">{money(tx.foreign.original_amount, tx.foreign.original_currency)} convertidos</p>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {cancelada ? <Etiqueta tom="perigo">Cancelada</Etiqueta>
          : tx.card ? <Etiqueta>Cartão {tx.card.name}{tx.statement ? ` · fatura de ${monthLong(tx.statement.month)}` : ''}</Etiqueta>
          : <Etiqueta tom={tx.settled ? 'ok' : 'aviso'}>{tx.settled ? 'Paga' : 'A pagar'}</Etiqueta>}
        {tx.category && <Etiqueta>{tx.category.name}</Etiqueta>}
        {tx.installment && <Etiqueta>Parcela {tx.installment.number}/{tx.installment.of}</Etiqueta>}
        {(tx.tags ?? []).map((t) => <Etiqueta key={t}>#{t}</Etiqueta>)}
        {data.replayed === true && <Etiqueta tom="aviso">Já registrada antes</Etiqueta>}
      </div>
      {divisao.length > 1 && (
        <div className="mt-3 rounded-md border border-border px-3 py-2">
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
  const categorias = ((data.by_category as Share[] | undefined) ?? []).slice(0, 4);
  const compras = ((data.purchases as Brief[] | undefined) ?? []).slice(0, 6);
  const quantas = Number(data.purchases_count ?? compras.length);
  const card = data.card as Ref | undefined;
  const saldo = Number(data.balance ?? 0);
  const [rotulo, tom] = data.overdue === true ? SITUACAO_DA_FATURA.overdue
    : SITUACAO_DA_FATURA[String(data.status)] ?? [String(data.status), 'neutro' as Tom];
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold">Fatura de {monthLong(data.month as string)}</p>
          <p className="truncate text-xs text-muted-fg">{card?.name} · vence em {day(data.due_date as string)}</p>
        </div>
        <Etiqueta tom={tom}>{rotulo}</Etiqueta>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] text-muted-fg">Total</p>
          <p className="num text-xl font-semibold">{money(data.total as string, moeda)}</p>
        </div>
        <div className="text-right">
          <p className="text-[11px] text-muted-fg">{saldo > 0 ? 'Falta pagar' : 'Quitada'}</p>
          <p className={`num font-semibold ${saldo > 0 ? 'text-warn' : 'text-income'}`}>{money(data.balance as string, moeda)}</p>
        </div>
      </div>
      {categorias.length > 0 && <Barras itens={categorias} total={data.total as string} moeda={moeda} />}
      {compras.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          {compras.map((p) => (
            <Linha
              key={p.id}
              rotulo={<><span className="num text-muted-fg">{shortDay(p.date)}</span> {p.title}</>}
              valor={money(p.statement_amount ?? p.amount, moeda)}
            />
          ))}
          {quantas > compras.length && (
            <p className="pt-1 text-xs text-muted-fg">e mais {plural(quantas - compras.length, 'compra', 'compras')} no app</p>
          )}
        </div>
      )}
      <AbrirNoApp url={appUrl} bridge={bridge} />
    </div>
  );
}

function Quadro({ rotulo, valor, destaque }: { rotulo: string; valor: string; destaque?: boolean }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <p className="text-[11px] text-muted-fg">{rotulo}</p>
      <p className={`num font-semibold ${destaque ? 'text-base' : 'text-sm'}`}>{valor}</p>
    </div>
  );
}

function SummaryView({ data, bridge, appUrl }: { data: Data; bridge: Bridge; appUrl?: string }) {
  const moeda = (data.currency as string) ?? 'BRL';
  const cats = ((data.my_categories as Share[] | undefined) ?? []).slice(0, 5);
  const resultado = Number(data.result ?? 0);
  return (
    <div>
      <p className="text-base font-semibold first-letter:uppercase">{monthLong(data.month as string)}</p>
      <div className="mt-2 flex items-baseline justify-between gap-3">
        <span className="text-sm text-muted-fg">Resultado do mês</span>
        <span className={`num text-xl font-semibold ${resultado >= 0 ? 'text-income' : 'text-expense'}`}>{money(data.result as string, moeda)}</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Quadro rotulo="Renda" valor={money(data.income as string, moeda)} />
        <Quadro rotulo="Seu consumo" valor={money(data.consumption as string, moeda)} />
        <Quadro rotulo="Saiu do caixa" valor={money(data.cash_out as string, moeda)} />
        <Quadro rotulo="A pagar" valor={money(data.payables_total as string, moeda)} />
      </div>
      {cats.length > 0 && <Barras itens={cats} total={data.consumption as string} moeda={moeda} />}
      <AbrirNoApp url={appUrl} bridge={bridge} />
    </div>
  );
}

function BulkPreviewView({ data, bridge }: { data: Data; bridge: Bridge }) {
  const [estado, setEstado] = useState<'parado' | 'enviando' | 'feito' | 'erro'>('parado');
  const [mensagem, setMensagem] = useState('');
  const acao = data.action as string;
  const token = data.confirmation_token as string | null;
  const totais = (data.totals as Array<{ currency: string; amount: string }> | undefined) ?? [];
  const amostra = (data.sample as Brief[] | undefined) ?? [];
  const categoria = data.category as Ref | undefined;
  const anexos = Number(data.attachments ?? 0);
  const excluir = acao === 'delete';

  const confirmar = async () => {
    if (!token) return;
    setEstado('enviando');
    try {
      const nome = excluir ? 'transactions_bulk_delete' : 'transactions_bulk_categorize';
      const r = await bridge.callTool(nome, { confirmation_token: token });
      if (r.isError) throw new Error(r.content?.[0]?.text?.split('\n')[0] ?? 'A operação foi recusada.');
      const feito = (r.structuredContent ?? {}) as { count?: number };
      const n = feito.count ?? 0;
      setMensagem(
        excluir
          ? `${plural(n, 'lançamento excluído', 'lançamentos excluídos')}.`
          : `${plural(n, 'lançamento categorizado', 'lançamentos categorizados')}.`,
      );
      setEstado('feito');
    } catch (e) {
      setMensagem(e instanceof Error ? e.message : 'Não foi possível concluir.');
      setEstado('erro');
    }
  };

  return (
    <div>
      <p className="text-base font-semibold">
        {excluir ? 'Excluir' : `Categorizar como ${categoria?.name ?? '—'}`} · {plural(Number(data.count ?? 0), 'lançamento', 'lançamentos')}
      </p>
      <p className="num text-sm text-muted-fg">{totais.map((t) => money(t.amount, t.currency)).join(' + ') || 'nada'}</p>
      {anexos > 0 && (
        <p className="mt-2 rounded-md bg-warn-bg px-3 py-2 text-xs text-warn">
          {plural(anexos, 'anexo será apagado', 'anexos serão apagados')} para sempre.
        </p>
      )}
      {amostra.length > 0 && (
        <div className="mt-2 border-t border-border pt-2">
          {amostra.map((b) => (
            <Linha key={b.id} rotulo={<><span className="num text-muted-fg">{shortDay(b.date)}</span> {b.title}</>} valor={money(b.amount, b.currency)} />
          ))}
        </div>
      )}
      {Number(data.ineligible_count ?? 0) > 0 && (
        <p className="mt-1 text-xs text-muted-fg">
          {plural(Number(data.ineligible_count), 'lançamento ficou de fora', 'lançamentos ficaram de fora')} (pagos, de outra pessoa ou já categorizados).
        </p>
      )}
      {token && estado !== 'feito' && (
        <button
          type="button"
          disabled={estado === 'enviando'}
          onClick={confirmar}
          className={`mt-3 w-full rounded-md px-3 py-2 text-sm font-semibold disabled:opacity-60 ${excluir ? 'bg-danger text-danger-fg' : 'bg-primary text-primary-fg'}`}
        >
          {estado === 'enviando' ? 'Enviando…' : excluir ? 'Confirmar exclusão' : 'Confirmar categorização'}
        </button>
      )}
      {mensagem && <p className={`mt-2 text-sm ${estado === 'erro' ? 'text-expense' : 'text-income'}`} role="status">{mensagem}</p>}
    </div>
  );
}

/** Enquanto o resultado não chega: a silhueta do cartão, sem texto piscando. */
function Esqueleto() {
  return (
    <div className="animate-pulse space-y-2" aria-busy="true" aria-label="Carregando">
      <div className="h-4 w-1/2 rounded bg-muted" />
      <div className="h-3 w-1/3 rounded bg-muted" />
      <div className="h-8 w-full rounded bg-muted" />
    </div>
  );
}

export function Widget({ bridge }: { bridge: Bridge }) {
  const [resultado, setResultado] = useState<ToolResultLike | null>(null);
  const [tema, setTema] = useState<Tema>('light');

  useEffect(() => {
    bridge.onResult(setResultado);
    bridge.onTheme(setTema);
  }, [bridge]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', tema === 'dark');
  }, [tema]);

  if (!resultado) return <Esqueleto />;
  if (resultado.isError) return null; // o texto do erro já está na conversa
  const data = (resultado.structuredContent ?? {}) as Data;
  const meta = (resultado._meta ?? {}) as { view?: string; app_url?: string };

  const vista = meta.view
    ?? (data.transaction ? 'transaction' : data.confirmation_token !== undefined ? 'bulk_preview' : data.purchases ? 'statement' : data.my_categories ? 'summary' : '');
  return (
    <div className="text-fg">
      {vista === 'transaction' && <TransactionView data={data} bridge={bridge} appUrl={meta.app_url} />}
      {vista === 'statement' && <StatementView data={data} bridge={bridge} appUrl={meta.app_url} />}
      {vista === 'summary' && <SummaryView data={data} bridge={bridge} appUrl={meta.app_url} />}
      {vista === 'bulk_preview' && <BulkPreviewView data={data} bridge={bridge} />}
    </div>
  );
}
