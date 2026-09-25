/** @jsxImportSource preact */
/**
 * Recibo de escrita (o que foi feito, com Desfazer quando há volta), histórico de
 * um lançamento e importações (lotes, linhas e Desfazer importação).
 */
import type { ComponentChildren, JSX } from 'preact';
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, money, monthLong, plural } from '../format';
import type { Meta, Ref } from '../tipos';
import { useAcao } from '../ui/acao';
import { Aviso, Badge, Button, Header, Linha, Money, Vazio } from '../ui/base';
import {
  IconArrowRight, IconBank, IconCard, IconChart, IconClip, IconExternal, IconHistory, IconTag, IconTrash, IconUpload, IconUsers,
} from '../ui/icons';
import { CarregarMais } from '../ui/lista';
import { usePaginas } from '../ui/paginas';
import { BotaoDesfazer, Mudancas } from '../ui/mudancas';
import { Historico } from './Lancamento';
import { PreviaDeMassa } from './Massa';

type Tom = 'ok' | 'destaque' | 'perigo';
interface Recibo { icone: JSX.Element; tom: Tom; titulo: string; subtitulo?: string; linhas?: Array<[string, ComponentChildren]>; mudancas?: Array<[string, string, string]> }

const R = (d: Record<string, unknown>, k: string) => (d[k] as Ref | undefined)?.name ?? '—';

/** Cada escrita → como contar o que aconteceu. */
const RECIBOS: Record<string, (d: Record<string, unknown>) => Recibo> = {
  statements_pay: (d) => ({
    icone: <IconCard size={18} />, tom: 'ok', titulo: `Fatura de ${monthLong(d.month as string)} paga`, subtitulo: `${R(d, 'card')} · ${money(d.amount_paid as string, d.currency as string)}`,
    linhas: [['Total', money(d.total as string, d.currency as string)], ['Pago', money(d.paid as string, d.currency as string)],
      ['Falta', money(d.balance as string, d.currency as string)], ['Saiu de', R(d, 'account')]],
  }),
  statements_reopen: (d) => ({
    icone: <IconCard size={18} />, tom: 'destaque', titulo: `Fatura de ${monthLong(d.month as string)} reaberta`,
    subtitulo: `${R(d, 'card')} · ${plural(((d.reversed_payments as unknown[]) ?? []).length, 'pagamento estornado', 'pagamentos estornados')}`,
    linhas: [['Saldo', money(d.balance as string, d.currency as string)]],
  }),
  transfers_create: (d) => ({
    icone: <IconBank size={18} />, tom: 'ok', titulo: 'Transferência registrada', subtitulo: day(d.date as string),
    linhas: [['De', R(d, 'from_account')], ['Para', R(d, 'to_account')], ['Valor', money(d.from_amount as string, d.from_currency as string)],
      ...(d.from_currency !== d.to_currency ? [['Chegou', money(d.to_amount as string, d.to_currency as string)] as [string, string]] : [])],
  }),
  transfers_delete: (d) => {
    const t = (d.deleted ?? {}) as Record<string, unknown>;
    return { icone: <IconTrash size={18} />, tom: 'perigo', titulo: 'Transferência excluída', subtitulo: `${R(t, 'from_account')} → ${R(t, 'to_account')} · ${money(t.from_amount as string, t.from_currency as string)}` };
  },
  settlements_create: (d) => ({
    icone: <IconUsers size={18} />, tom: 'ok', titulo: 'Acerto registrado', subtitulo: `${R(d, 'space')} · ${day(d.date as string)}`,
    linhas: [['Pagou', R(d, 'payer')], ['Recebeu', R(d, 'receiver')], ['Valor', money(d.amount as string, d.currency as string)], ...(d.month ? [['Mês', monthLong(d.month as string)] as [string, string]] : [])],
  }),
  settlements_delete: (d) => {
    const s = (d.deleted ?? {}) as Record<string, unknown>;
    return { icone: <IconTrash size={18} />, tom: 'perigo', titulo: 'Acerto excluído', subtitulo: `${R(s, 'payer')} → ${R(s, 'receiver')} · ${money(s.amount as string, s.currency as string)}` };
  },
  accounts_adjust_balance: (d) => ({
    icone: <IconBank size={18} />, tom: 'ok', titulo: `Saldo de ${R(d, 'account')} ajustado`, subtitulo: day(d.date as string),
    mudancas: [['Saldo', money(d.previous_balance as string, d.currency as string), money(d.new_balance as string, d.currency as string)]],
    linhas: [['Ajuste', <Money valor={d.adjustment as string} moeda={d.currency as string} tom="auto" />]],
  }),
  budgets_set: (d) => ({
    icone: <IconChart size={18} />, tom: 'ok', titulo: `Meta ${d.created ? 'criada' : 'atualizada'}: ${R(d, 'category')}`,
    subtitulo: `${monthLong(d.month as string)} · ${R(d, 'space')}${d.scope === 'personal' ? ' · sua' : ' · da casa'}`,
    linhas: [['Meta', money(d.amount as string)]],
  }),
  categories_create: (d) => ({
    icone: <IconTag size={18} />, tom: 'ok', titulo: `${d.kind === 'tag' ? 'Tag' : 'Categoria'} criada: ${d.kind === 'tag' ? '#' : ''}${d.name as string}`, subtitulo: R(d, 'space'),
  }),
  categories_update: (d) => ({
    icone: d.deleted ? <IconTrash size={18} /> : <IconTag size={18} />, tom: d.deleted ? 'perigo' : 'destaque',
    titulo: d.deleted ? `${d.kind === 'tag' ? 'Tag' : 'Categoria'} excluída: ${d.name as string}` : `${d.kind === 'tag' ? 'Tag' : 'Categoria'} atualizada`,
    subtitulo: R(d, 'space'),
    mudancas: !d.deleted && d.previous_name && d.previous_name !== d.name ? [['Nome', d.previous_name as string, d.name as string]] : undefined,
  }),
  attachments_add: (d) => {
    const a = (d.attachment ?? {}) as Record<string, unknown>;
    return { icone: <IconClip size={18} />, tom: 'ok', titulo: 'Anexo adicionado', subtitulo: `${a.filename as string} · lançamento #${d.transaction_id as number}` };
  },
  attachments_delete: (d) => {
    const a = (d.deleted ?? {}) as Record<string, unknown>;
    return { icone: <IconTrash size={18} />, tom: 'perigo', titulo: 'Anexo removido', subtitulo: `${a.filename as string} · lançamento #${d.transaction_id as number}` };
  },
};

export function ReciboView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const montar = RECIBOS[meta.tool ?? ''];
  const r: Recibo = montar ? montar(dados) : { icone: <IconArrowRight size={18} />, tom: 'ok', titulo: 'Feito' };
  const url = (dados.app_url as string | undefined) ?? meta.app_url;
  return (
    <div class="space-y-3">
      <Header icone={r.icone} tom={r.tom} titulo={r.titulo} subtitulo={r.subtitulo} />
      {dados.replayed === true && <Badge tom="aviso">Já tinha sido registrado: nada foi duplicado</Badge>}
      {r.mudancas && <Mudancas linhas={r.mudancas} />}
      {r.linhas && (
        <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
          {r.linhas.flatMap(([k, v]) => [<dt key={`k-${k}`} class="text-muted-fg">{k}</dt>, <dd key={`v-${k}`} class="num min-w-0 truncate text-right font-medium">{v}</dd>])}
        </dl>
      )}
      <div class="flex flex-wrap items-center gap-2">
        <BotaoDesfazer undo={meta.undo} bridge={bridge} feito="Desfeito." />
        <span class="flex-1" />
        {url && <Button variante="ghost" icone={<IconExternal size={14} />} onClick={() => bridge.openLink(url)}>Abrir no app</Button>}
      </div>
    </div>
  );
}

export function HistoricoView({ dados }: { dados: Record<string, unknown> }) {
  const entradas = (dados.entries as Parameters<typeof Historico>[0]['entradas'] | undefined) ?? [];
  return (
    <div class="space-y-3">
      <Header icone={<IconHistory size={18} />} tom="destaque" titulo={`Histórico do lançamento #${dados.transaction_id as number}`}
        subtitulo={plural(entradas.length, 'registro', 'registros')} />
      <Historico entradas={entradas} />
    </div>
  );
}

// --- Importações -----------------------------------------------------------------

interface Lote {
  id: number; space: Ref; filename?: string | null; imported_on: string; total_rows: number; imported: number; ignored: number;
  duplicates: number; skipped: number; live_transactions: number;
}
interface LinhaImportada { line: number; date?: string | null; title?: string | null; amount?: string | null; status: string; transaction_id?: number | null; reason?: string | null }

const SITUACAO_DA_LINHA: Record<string, [string, 'ok' | 'aviso' | 'neutro' | 'perigo']> = {
  imported: ['importada', 'ok'], ignored: ['ignorada', 'neutro'], duplicate: ['duplicada', 'aviso'], skipped: ['pulada', 'aviso'], error: ['erro', 'perigo'],
};

/** Desfazer importação = a prévia de exclusão pelo lote, confirmada aqui mesmo. */
function DesfazerImportacao({ lote, bridge, meta, rotulo = 'Desfazer importação' }: { lote: number; bridge: Bridge; meta: Meta; rotulo?: string }) {
  const [previa, setPrevia] = useState<Record<string, unknown> | null>(null);
  const exec = useAcao(bridge);
  if (previa) {
    return (
      <div class="w-aparece rounded-lg border border-border p-3">
        <PreviaDeMassa dados={previa} meta={meta} bridge={bridge} />
      </div>
    );
  }
  return (
    <>
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      <Button variante="ghost" icone={<IconTrash size={14} />} carregando={exec.estado === 'enviando'}
        onClick={async () => { const r = await exec.executar('transactions_bulk_preview', { action: 'delete', filters: { import_batch_id: lote } }); if (r) setPrevia(r); }}>
        {rotulo}
      </Button>
    </>
  );
}

function Linhas({ dados, lote, bridge }: { dados: Record<string, unknown>; lote: number; bridge: Bridge }) {
  const pagina = usePaginas<LinhaImportada>(bridge, { tool: 'imports_list', args: { batch_id: lote } }, (dados.rows as LinhaImportada[]) ?? [], dados.next_cursor as string | null, 'rows');
  if (!pagina.itens.length) return <Vazio>Sem linhas.</Vazio>;
  return (
    <>
      <ul>
        {pagina.itens.map((l) => {
          const [rotulo, tom] = SITUACAO_DA_LINHA[l.status] ?? [l.status, 'neutro'];
          return (
            <Linha key={l.line} titulo={l.title ?? `Linha ${l.line}`} detalhe={[`linha ${l.line}`, l.date && day(l.date), l.reason].filter(Boolean).join(' · ')}
              direita={<>{l.amount && <Money valor={l.amount} class="font-medium" />}<span class="block"><Badge tom={tom}>{rotulo}</Badge></span></>} />
          );
        })}
      </ul>
      <CarregarMais pagina={pagina} mostrados={pagina.itens.length} />
    </>
  );
}

export function ImportacoesView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  // Resultado do imports_commit: o lote recém-importado, com Desfazer.
  if (meta.tool === 'imports_commit') {
    const lote = dados.batch_id as number | undefined;
    return (
      <div class="space-y-3">
        <Header icone={<IconUpload size={18} />} tom="ok" titulo={`${plural(Number(dados.imported ?? 0), 'lançamento importado', 'lançamentos importados')}`}
          subtitulo={[R(dados, 'space'), Number(dados.duplicate ?? 0) > 0 && `${dados.duplicate} duplicados`, Number(dados.ignored ?? 0) > 0 && `${dados.ignored} ignorados`,
            Number(dados.skipped ?? 0) > 0 && `${dados.skipped} pulados`].filter(Boolean).join(' · ')} />
        {dados.replayed === true && <Badge tom="aviso">Já tinha sido importado: nada foi duplicado</Badge>}
        {lote && meta.undo && <DesfazerImportacao lote={lote} bridge={bridge} meta={meta} />}
      </div>
    );
  }
  const lotes = (dados.batches as Lote[] | undefined) ?? [];
  const lote = meta.query?.args.batch_id as number | undefined;
  return (
    <div class="space-y-3">
      <Header icone={<IconUpload size={18} />} tom="destaque" titulo={lote ? `Importação #${lote}` : 'Importações'}
        subtitulo={lote ? lotes[0]?.filename ?? undefined : plural(lotes.length, 'lote', 'lotes')} />
      {!lote && lotes.length === 0 && <Vazio>Nenhuma importação.</Vazio>}
      {!lote && (
        <ul class="space-y-2">
          {lotes.map((b) => (
            <li key={b.id} class="list-none rounded-lg border border-border p-2.5">
              <div class="flex items-baseline gap-2">
                <span class="min-w-0 flex-1 truncate text-[14px] font-medium">{b.filename ?? `Lote #${b.id}`}</span>
                <span class="text-[12px] text-muted-fg">{day(b.imported_on)}</span>
              </div>
              <p class="text-[12px] text-muted-fg">
                {b.space.name} · {plural(b.imported, 'importado', 'importados')}{b.duplicates ? ` · ${b.duplicates} duplicados` : ''}{b.ignored ? ` · ${b.ignored} ignorados` : ''}
                {b.live_transactions === 0 && b.imported > 0 ? ' · desfeita' : b.live_transactions !== b.imported ? ` · ${b.live_transactions} ainda no app` : ''}
              </p>
              {b.live_transactions > 0 && <div class="mt-1.5"><DesfazerImportacao lote={b.id} bridge={bridge} meta={meta} /></div>}
            </li>
          ))}
        </ul>
      )}
      {lote && <Linhas dados={dados} lote={lote} bridge={bridge} />}
      {lote && (lotes[0]?.live_transactions ?? 0) > 0 && <DesfazerImportacao lote={lote} bridge={bridge} meta={meta} />}
    </div>
  );
}
