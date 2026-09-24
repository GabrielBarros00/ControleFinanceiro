/** @jsxImportSource preact */
/**
 * Lista de lançamentos (`view_show view=transactions`): os filtros que o
 * assistente usou, os totais (cheio e minha parte), a paginação, a linha que
 * abre o detalhe com o editor, e a seleção para agir em vários de uma vez.
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, money, monthLong, plural } from '../format';
import type { Meta, Resumo } from '../tipos';
import { erroDe, useAcao } from '../ui/acao';
import { Aviso, Badge, Button, Header, Stat, Vazio } from '../ui/base';
import { Escolha } from '../ui/form';
import { IconCheck, IconReceipt, IconTrash, IconX } from '../ui/icons';
import { CarregarMais, LinhaDeLancamento } from '../ui/lista';
import { type Consulta, usePaginas } from '../ui/paginas';
import { PreviaDeMassa, ResultadoDeMassa } from './Massa';

interface Total { currency: string; amount: string; count: number }

const FILTRO: Record<string, (v: unknown) => string> = {
  month: (v) => monthLong(String(v)),
  date_from: (v) => `desde ${day(String(v))}`,
  date_to: (v) => `até ${day(String(v))}`,
  space: (v) => String(v),
  text: (v) => `“${String(v)}”`,
  card: (v) => `cartão ${String(v)}`,
  category: (v) => String(v),
  tag: (v) => `#${String(v)}`,
  person: (v) => `com ${String(v)}`,
  uncategorized: () => 'sem categoria',
  settled: (v) => (v ? 'pagos' : 'a pagar'),
};

export function Filtros({ args }: { args: Record<string, unknown> }) {
  const chips = Object.entries(args).filter(([k, v]) => FILTRO[k] && v !== undefined && v !== null && v !== false);
  if (!chips.length) return null;
  return <div class="flex flex-wrap gap-1.5">{chips.map(([k, v]) => <Badge key={k} tom="destaque">{FILTRO[k](v)}</Badge>)}</div>;
}

/** A lista em si — reusada pela análise (clicar numa categoria abre os lançamentos dela). */
export function ListaDeLancamentos({ dados, consulta, meta, bridge }: {
  dados: Record<string, unknown>; consulta?: Consulta; meta: Meta; bridge: Bridge;
}) {
  const pagina = usePaginas<Resumo>(bridge, consulta, (dados.items as Resumo[]) ?? [], dados.next_cursor as string | null, 'items');
  const [selecionando, setSelecionando] = useState(false);
  const [marcados, setMarcados] = useState<number[]>([]);
  const [previa, setPrevia] = useState<Record<string, unknown> | null>(null);
  const [resultado, setResultado] = useState<Record<string, unknown> | null>(null);
  const [categoria, setCategoria] = useState('');
  const [erroLista, setErroLista] = useState<string | null>(null);
  const exec = useAcao(bridge);
  const total = Number(dados.total_count ?? pagina.itens.length);
  const podeEditar = Boolean(meta.forms && Object.keys(meta.forms).length);

  const espacos = new Set(pagina.itens.filter((r) => marcados.includes(r.id)).map((r) => r.space?.id));
  const formDoEspaco = espacos.size === 1 ? meta.forms?.[String([...espacos][0])] : undefined;

  async function previsualizar(acao: string, extra: Record<string, unknown> = {}) {
    const r = await exec.executar('transactions_bulk_preview', { action: acao, transaction_ids: marcados, ...extra });
    if (r) setPrevia(r);
  }

  async function recarregar() {
    if (!consulta) return;
    const r = await bridge.callTool(consulta.tool, consulta.args).catch(() => null);
    if (r && !r.isError) {
      const d = (r.structuredContent ?? {}) as Record<string, unknown>;
      pagina.trocar((d.items as Resumo[]) ?? [], d.next_cursor as string | null);
    } else setErroLista(r ? erroDe(r).mensagem : 'Não foi possível atualizar a lista.');
  }

  if (!pagina.itens.length) return <Vazio>Nenhum lançamento com esses filtros.</Vazio>;

  return (
    <div class="space-y-2">
      {previa ? (
        <div class="w-aparece rounded-lg border border-border p-3">
          <PreviaDeMassa dados={previa} meta={meta} bridge={bridge} aoConcluir={(r) => {
            setResultado(r);
            setPrevia(null);
            setMarcados([]);
            setSelecionando(false);
            void recarregar();
          }} />
          <Button variante="ghost" class="mt-2" onClick={() => setPrevia(null)}>Voltar</Button>
        </div>
      ) : resultado ? (
        <div class="w-aparece rounded-lg border border-border p-3">
          <ResultadoDeMassa dados={resultado} bridge={bridge}
            meta={{ undo_each: resultado.action === 'delete' ? ((resultado.transaction_ids as number[]) ?? []).map((i) => ({ transaction_id: i })) : [] }} />
          <Button variante="ghost" class="mt-2" onClick={() => { setResultado(null); void recarregar(); }}>Fechar</Button>
        </div>
      ) : null}

      {podeEditar && !previa && (
        <div class="flex flex-wrap items-center gap-2">
          {!selecionando ? (
            <Button variante="ghost" icone={<IconCheck size={14} />} onClick={() => setSelecionando(true)}>Selecionar</Button>
          ) : (
            <>
              <span class="text-[12px] text-muted-fg">{plural(marcados.length, 'selecionado', 'selecionados')}</span>
              {marcados.length > 0 && (
                <>
                  <Button carregando={exec.estado === 'enviando'} onClick={() => void previsualizar('settle')}>Marcar pago</Button>
                  <Button variante="danger" icone={<IconTrash size={14} />} carregando={exec.estado === 'enviando'} onClick={() => void previsualizar('delete')}>Excluir</Button>
                  {formDoEspaco && (
                    <span class="w-40">
                      <Escolha valor={categoria} vazio="Categorizar…" aoMudar={(v) => { setCategoria(v); if (v) void previsualizar('recategorize', { category_id: Number(v) }); }}
                        opcoes={formDoEspaco.categories.map((c) => ({ valor: String(c.id), rotulo: c.name }))} />
                    </span>
                  )}
                </>
              )}
              <Button variante="ghost" icone={<IconX size={14} />} onClick={() => { setSelecionando(false); setMarcados([]); }}>Cancelar</Button>
            </>
          )}
        </div>
      )}
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      {erroLista && <Aviso tom="erro">{erroLista}</Aviso>}

      <ul>
        {pagina.itens.map((r) => (
          <LinhaDeLancamento key={r.id} r={r} bridge={bridge} forms={meta.forms} selecionavel={selecionando}
            marcado={marcados.includes(r.id)}
            aoMarcar={(id, sim) => setMarcados((m) => (sim ? [...m, id] : m.filter((x) => x !== id)))} />
        ))}
      </ul>
      <CarregarMais pagina={pagina} total={total} mostrados={pagina.itens.length} />
    </div>
  );
}

export function ListaView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const totais = (dados.totals as Total[] | undefined) ?? [];
  const minha = (dados.my_share_totals as Total[] | undefined) ?? [];
  const total = Number(dados.total_count ?? 0);
  return (
    <div class="space-y-3">
      <Header icone={<IconReceipt size={18} />} tom="destaque" titulo="Lançamentos" subtitulo={plural(total, 'lançamento', 'lançamentos')} />
      <Filtros args={meta.query?.args ?? {}} />
      {totais.length > 0 && (
        <div class="grid grid-cols-2 gap-2">
          <Stat rotulo="Total">{totais.map((t) => money(t.amount, t.currency)).join(' + ')}</Stat>
          <Stat rotulo="Sua parte">{minha.map((t) => money(t.amount, t.currency)).join(' + ') || '—'}</Stat>
        </div>
      )}
      <ListaDeLancamentos dados={dados} consulta={meta.query} meta={meta} bridge={bridge} />
    </div>
  );
}
