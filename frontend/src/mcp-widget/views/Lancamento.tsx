/** @jsxImportSource preact */
/**
 * Um lançamento: como ficou (criado), o antes → depois (editado), o que sumiu
 * (excluído, com Desfazer) — e o editor ali mesmo, para a pessoa corrigir sem
 * pedir ao assistente.
 *
 * Toda ação chama a MESMA tool que o assistente chamaria; o servidor reaplica as
 * regras (permissão, trava de paga, versão). Depois, `updateModelContext` conta
 * ao modelo o que mudou.
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, FORMA, money, monthLong, plural, SITUACAO } from '../format';
import type { Arquivo, Desfazer, Formulario, Item, Lancamento, Meta, PessoaValor, Resumo } from '../tipos';
import { erroDe, useAcao } from '../ui/acao';
import { Aviso, Avatar, Badge, Button, Header, Linha, Money, Section, Vazio } from '../ui/base';
import { Campo, Chips, Data, Dinheiro, Escolha, Segmentos, Texto } from '../ui/form';
import {
  IconArrowRight, IconCard, IconCheck, IconClip, IconExternal, IconHistory, IconPencil, IconReceipt, IconTrash, IconUndo,
} from '../ui/icons';

const ROTULO_DO_CAMPO: Record<string, string> = {
  title: 'Título', description: 'Observação', date: 'Data', billing_month: 'Competência', amount: 'Valor',
  currency: 'Moeda', status: 'Situação', settled: 'Pago', payment_method: 'Forma de pagamento', card: 'Cartão',
  statement: 'Fatura', category: 'Categoria', categories: 'Categorias', tags: 'Tags', merchant: 'Estabelecimento',
  payers: 'Quem pagou',
  split: 'Divisão', split_mode: 'Modo de divisão', items: 'Itens', adjustments: 'Ajustes',
};

function valorDoCampo(campo: string, tx: Lancamento): string {
  switch (campo) {
    case 'amount': return money(tx.amount, tx.currency);
    case 'date': return day(tx.date);
    case 'billing_month': return monthLong(tx.billing_month);
    case 'settled': return tx.settled ? 'Pago' : 'A pagar';
    case 'status': return SITUACAO[tx.status] ?? tx.status;
    case 'payment_method': return tx.payment_method ? FORMA[tx.payment_method] ?? tx.payment_method : '—';
    case 'card': return tx.card?.name ?? '—';
    case 'statement': return tx.statement ? monthLong(tx.statement.month) : '—';
    case 'category': return tx.category?.name ?? 'Sem categoria';
    case 'categories': return (tx.categories ?? []).map((c) => c.name).join(', ') || '—';
    case 'tags': return (tx.tags ?? []).map((t) => `#${t}`).join(' ') || 'Sem tags';
    case 'merchant': return tx.merchant?.name ?? 'Sem estabelecimento';
    case 'payers': case 'split':
      return ((campo === 'split' ? tx.split : tx.payers) ?? []).map((p) => `${p.person.name.split(' ')[0]} ${money(p.amount, tx.currency)}`).join(' · ') || '—';
    case 'split_mode': return tx.split_mode === 'item' ? 'Por item' : 'Pelo total';
    case 'items': return plural((tx.items ?? []).length, 'item', 'itens');
    case 'adjustments': return plural((tx.adjustments ?? []).length, 'ajuste', 'ajustes');
    case 'description': return tx.description || '—';
    default: return String((tx as unknown as Record<string, unknown>)[campo] ?? '—');
  }
}

/** Antes → depois de cada campo que mudou. */
function Diferenca({ antes, depois, campos }: { antes: Lancamento; depois: Lancamento; campos: string[] }) {
  if (!campos.length) return <Vazio>Nada mudou: os valores já eram esses.</Vazio>;
  return (
    <ul class="space-y-1.5 rounded-lg bg-subtle p-2.5">
      {campos.map((c) => (
        <li key={c} class="grid grid-cols-[minmax(0,7rem)_1fr] items-baseline gap-2 text-[13px]">
          <span class="truncate text-muted-fg">{ROTULO_DO_CAMPO[c] ?? c}</span>
          <span class="flex min-w-0 flex-wrap items-center gap-1.5">
            <span class="num text-muted-fg line-through decoration-1">{valorDoCampo(c, antes)}</span>
            <IconArrowRight size={12} class="shrink-0 text-muted-fg" />
            <span class="num font-medium">{valorDoCampo(c, depois)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Pessoas({ lista, moeda, total }: { lista: PessoaValor[]; moeda: string; total: string }) {
  return (
    <ul class="space-y-1.5">
      {lista.map((p) => {
        const pct = Number(total) > 0 ? Math.round((Number(p.amount) / Number(total)) * 100) : 0;
        return (
          <li key={p.person.id} class="flex items-center gap-2 text-[13px]">
            <Avatar nome={p.person.name} />
            <span class="min-w-0 flex-1 truncate">{p.person.name}{p.is_me && <span class="text-muted-fg"> (você)</span>}</span>
            <span class="num text-[12px] text-muted-fg">{pct}%</span>
            <Money valor={p.amount} moeda={moeda} class="w-24 text-right font-medium" />
          </li>
        );
      })}
    </ul>
  );
}

function Itens({ itens, moeda }: { itens: Item[]; moeda: string }) {
  return (
    <ul class="divide-y divide-border">
      {itens.map((i, n) => (
        <li key={`${i.title}-${n}`} class="py-1.5">
          <div class="flex items-baseline gap-2 text-[13px]">
            <span class="min-w-0 flex-1 truncate">{i.title}</span>
            {i.quantity !== '1' && <span class="num text-[12px] text-muted-fg">{i.quantity} × {i.unit_amount ? money(i.unit_amount, moeda) : '—'}</span>}
            <Money valor={i.amount} moeda={moeda} class="font-medium" />
          </div>
          <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
            {i.category && <Badge>{i.category.name}</Badge>}
            {(i.shares ?? []).map((s) => (
              <span key={s.person.id} class="inline-flex items-center gap-1 text-[11px] text-muted-fg" title={`${s.person.name}: ${money(s.amount, moeda)}`}>
                <Avatar nome={s.person.name} tamanho={16} /> <span class="num">{money(s.amount, moeda)}</span>
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

const TAMANHO = (b: number) => (b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

function Anexos({ arquivos, bridge }: { arquivos: Arquivo[]; bridge: Bridge }) {
  const [imagens, setImagens] = useState<Record<number, string | null>>({});
  const acao = useAcao(bridge);
  async function ver(a: Arquivo) {
    const r = await bridge.callTool('attachments_get', { attachment_id: a.id }).catch(() => null);
    const bloco = (r?.content as Array<{ type: string; data?: string; mimeType?: string }> | undefined)?.find((c) => c.type === 'image');
    setImagens((m) => ({ ...m, [a.id]: bloco?.data ? `data:${bloco.mimeType};base64,${bloco.data}` : null }));
  }
  return (
    <ul class="space-y-1">
      {arquivos.map((a) => (
        <li key={a.id} class="rounded-md border border-border px-2.5 py-2 text-[13px]">
          <div class="flex items-center gap-2">
            <IconClip size={14} class="shrink-0 text-muted-fg" />
            <span class="min-w-0 flex-1 truncate">{a.filename}</span>
            <span class="text-[11px] text-muted-fg">{TAMANHO(a.size_bytes)}</span>
            {a.content_type.startsWith('image/') && imagens[a.id] === undefined && (
              <Button variante="ghost" onClick={() => void ver(a)}>Ver</Button>
            )}
          </div>
          {imagens[a.id] && <img src={imagens[a.id]!} alt={`Recibo ${a.filename}`} class="mt-2 max-h-72 w-full rounded-md object-contain" />}
          {imagens[a.id] === null && <p class="mt-1 text-[12px] text-muted-fg">Grande demais para abrir aqui: veja no app.</p>}
        </li>
      ))}
      {acao.erro && <Aviso tom="erro">{acao.erro.mensagem}</Aviso>}
    </ul>
  );
}

interface EntradaDoHistorico {
  at: string; action: string; by?: { name: string } | null; via_ai: boolean; client?: string | null;
  changes: Array<{ field: string; before?: string | null; after?: string | null }>; detail_only: boolean;
}
const ACAO_DO_HISTORICO: Record<string, string> = {
  created: 'Criado', updated: 'Alterado', deleted: 'Excluído', restored: 'Restaurado', cancelled: 'Cancelado', paid: 'Pago', reopened: 'Reaberto',
};

/** O histórico guarda o valor cru ("89.90", "2026-09-20", "credit_card"): aqui vira texto da tela. */
function textoDoHistorico(campo: string, v?: string | null): string {
  if (v === null || v === undefined || v === '') return '—';
  switch (campo) {
    case 'amount': return Number.isFinite(Number(v)) ? Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : v;
    case 'date': case 'settled_on': return day(v);
    case 'billing_month': return monthLong(v);
    case 'status': return SITUACAO[v] ?? v;
    case 'payment_method': return FORMA[v] ?? v;
    case 'split_mode': return v === 'item' ? 'Por item' : 'Pelo total';
    default: return v;
  }
}

export function Historico({ entradas }: { entradas: EntradaDoHistorico[] }) {
  if (!entradas.length) return <Vazio>Sem registros.</Vazio>;
  return (
    <ol class="relative ml-1.5 space-y-3 border-l border-border pl-4">
      {entradas.map((e, i) => (
        <li key={i} class="relative">
          <span class="absolute -left-[21px] top-1 size-2.5 rounded-full border-2 border-surface bg-accent" aria-hidden="true" />
          <p class="text-[13px]">
            <span class="font-medium">{ACAO_DO_HISTORICO[e.action] ?? e.action}</span>
            <span class="text-muted-fg"> · {e.at.slice(8, 10)}/{e.at.slice(5, 7)} {e.at.slice(11)}</span>
          </p>
          <p class="text-[12px] text-muted-fg">
            {e.by?.name ?? 'Alguém'}{e.via_ai && <> · <Badge tom="destaque">via IA{e.client ? ` (${e.client})` : ''}</Badge></>}
          </p>
          {e.changes.length > 0 && (
            <ul class="mt-1 space-y-0.5 text-[12px]">
              {e.changes.map((c) => (
                <li key={c.field} class="flex flex-wrap items-center gap-1">
                  <span class="text-muted-fg">{ROTULO_DO_CAMPO[c.field] ?? c.field}:</span>
                  <span class="line-through opacity-60">{textoDoHistorico(c.field, c.before)}</span>
                  <IconArrowRight size={11} class="text-muted-fg" />
                  <span>{textoDoHistorico(c.field, c.after)}</span>
                </li>
              ))}
            </ul>
          )}
          {e.detail_only && <p class="text-[12px] text-muted-fg">Divisão, itens ou tags.</p>}
        </li>
      ))}
    </ol>
  );
}

/** O editor: só o que mudou vai para o servidor, junto com a versão lida. */
function Editor({ tx, form, bridge, aoSalvar, aoCancelar }: {
  tx: Lancamento; form: Formulario; bridge: Bridge; aoSalvar: (d: Record<string, unknown>) => void; aoCancelar: () => void;
}) {
  const [titulo, setTitulo] = useState(tx.title);
  const [valor, setValor] = useState(tx.foreign ? tx.foreign.original_amount : tx.amount);
  const [data, setData] = useState(tx.date);
  const [categoria, setCategoria] = useState(tx.category ? String(tx.category.id) : '');
  const [tags, setTags] = useState<string[]>(tx.tags ?? []);
  const [loja, setLoja] = useState(tx.merchant?.name ?? '');
  const [cartao, setCartao] = useState(tx.card ? String(tx.card.id) : '');
  const [forma, setForma] = useState(tx.payment_method ?? '');
  const [pago, setPago] = useState(tx.settled);
  const outros = form.people.filter((p) => !p.me);
  const divididoCom = (tx.split ?? []).filter((p) => !p.is_me).map((p) => p.person.id);
  const [divisao, setDivisao] = useState<'eu' | 'igual'>(divididoCom.length ? 'igual' : 'eu');
  const [com, setCom] = useState<number[]>(divididoCom);
  const acao = useAcao(bridge);
  const parcela = Boolean(tx.installment);
  const porItem = tx.split_mode === 'item' || (tx.items?.length ?? 0) > 0;
  const divisaoSimples = !porItem && (tx.split ?? []).length <= 2 || !porItem && divididoCom.length > 0;

  async function salvar() {
    const args: Record<string, unknown> = { transaction_id: tx.id };
    if (tx.version) args.expected_version = tx.version;
    if (titulo.trim() && titulo.trim() !== tx.title) args.title = titulo.trim();
    if (!parcela && !porItem && valor && valor !== (tx.foreign ? tx.foreign.original_amount : tx.amount)) args.amount = valor;
    if (data && data !== tx.date) args.date = data;
    if (categoria !== (tx.category ? String(tx.category.id) : '')) {
      if (categoria) args.category_id = Number(categoria);
      else args.remove_category = true;
    }
    const tagsAntes = [...(tx.tags ?? [])].sort().join('|');
    if ([...tags].sort().join('|') !== tagsAntes) args.tags = tags;
    // "" desvincula; um nome acha pelo nome ou apelido (parecido volta como pergunta).
    if (loja.trim() !== (tx.merchant?.name ?? '')) args.merchant = loja.trim();
    if (cartao !== (tx.card ? String(tx.card.id) : '')) {
      if (cartao) args.card_id = Number(cartao);
      else if (forma && forma !== 'credit_card') args.payment_method = forma;
    } else if (!cartao && forma && forma !== (tx.payment_method ?? '')) {
      args.payment_method = forma;
    }
    if (!cartao && pago !== tx.settled) args.settled = pago;
    if (!parcela && !porItem) {
      const antes = [...divididoCom].sort().join(',');
      const agora = divisao === 'eu' ? '' : [...com].sort().join(',');
      if (antes !== agora) args.split_with_ids = divisao === 'eu' ? [] : com;
    }
    if (Object.keys(args).length <= (tx.version ? 2 : 1)) {
      aoCancelar();
      return;
    }
    const resposta = await acao.executar(
      'transactions_update', args,
      `O usuário editou no componente o lançamento #${tx.id} ("${tx.title}"): ${Object.keys(args).filter((k) => !['transaction_id', 'expected_version'].includes(k)).join(', ')}.`,
    );
    if (resposta) aoSalvar(resposta);
  }

  return (
    <div class="w-aparece space-y-3 rounded-lg border border-border p-3">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Campo rotulo="Título">{(id) => <Texto id={id} valor={titulo} aoMudar={setTitulo} />}</Campo>
        <Campo rotulo={tx.foreign ? `Valor (${tx.foreign.original_currency})` : 'Valor'}
          dica={parcela ? 'Valor e parcelas da compra inteira: peça ao assistente ou use o app.' : porItem ? 'O valor sai dos itens.' : undefined}>
          {(id) => (parcela || porItem)
            ? <p id={id} class="w-input num opacity-60">{money(tx.amount, tx.currency)}</p>
            : <Dinheiro id={id} valor={valor} aoMudar={setValor} moeda={tx.foreign?.original_currency ?? tx.currency} />}
        </Campo>
        <Campo rotulo="Data">{(id) => <Data id={id} valor={data} aoMudar={setData} />}</Campo>
        <Campo rotulo="Categoria">
          {(id) => <Escolha id={id} valor={categoria} aoMudar={setCategoria} vazio="Sem categoria"
            opcoes={form.categories.map((c) => ({ valor: String(c.id), rotulo: c.name }))} />}
        </Campo>
        <Campo rotulo="Estabelecimento">
          {(id) => <Texto id={id} valor={loja} aoMudar={setLoja} max={120} placeholder="Onde foi a compra"
            sugestoes={(form.merchants ?? []).map((m) => m.name)} />}
        </Campo>
        <Campo rotulo="Cartão">
          {(id) => <Escolha id={id} valor={cartao} aoMudar={setCartao} vazio="Fora do cartão"
            opcoes={form.cards.map((c) => ({ valor: String(c.id), rotulo: c.name }))} />}
        </Campo>
        {!cartao && (
          <Campo rotulo="Forma de pagamento">
            {(id) => <Escolha id={id} valor={forma === 'credit_card' ? '' : forma} aoMudar={setForma} vazio="Não informada"
              opcoes={form.payment_methods.filter((f) => f !== 'credit_card').map((f) => ({ valor: f, rotulo: FORMA[f] ?? f }))} />}
          </Campo>
        )}
      </div>
      {!cartao && (
        <Segmentos rotulo="Situação" valor={pago ? 'pago' : 'aberto'} aoMudar={(v) => setPago(v === 'pago')}
          opcoes={[{ valor: 'aberto', rotulo: 'A pagar' }, { valor: 'pago', rotulo: 'Já paguei' }]} />
      )}
      {!parcela && !porItem && outros.length > 0 && divisaoSimples && (
        <div class="space-y-2">
          <span class="w-label">Divisão</span>
          <Segmentos rotulo="Divisão" valor={divisao} aoMudar={setDivisao}
            opcoes={[{ valor: 'eu', rotulo: 'Só minha' }, { valor: 'igual', rotulo: 'Partes iguais' }]} />
          {divisao === 'igual' && (
            <div class="flex flex-wrap gap-1.5">
              {outros.map((p) => {
                const marcado = com.includes(p.id);
                return (
                  <button key={p.id} type="button" aria-pressed={marcado}
                    onClick={() => setCom(marcado ? com.filter((x) => x !== p.id) : [...com, p.id])}
                    class={`inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-0.5 pr-2.5 text-[12px] ${marcado ? 'border-accent bg-accent-bg' : 'border-border'}`}>
                    <Avatar nome={p.name} tamanho={20} /> {p.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div>
        <span class="w-label">Tags</span>
        <Chips opcoes={form.tags.map((t) => t.name)} marcadas={tags} aoMudar={setTags} />
      </div>
      {acao.erro && (
        <Aviso tom="erro">
          {acao.erro.codigo === 'CONFLICT' ? 'Este lançamento mudou enquanto você editava. Feche e abra de novo para ver a versão atual.' : acao.erro.mensagem}
        </Aviso>
      )}
      <div class="flex flex-wrap justify-end gap-2">
        <Button variante="ghost" onClick={aoCancelar}>Cancelar</Button>
        <Button variante="primary" icone={<IconCheck size={14} />} carregando={acao.estado === 'enviando'} onClick={() => void salvar()}>Salvar</Button>
      </div>
    </div>
  );
}

const MODO: Record<string, [string, 'ok' | 'destaque' | 'perigo' | 'neutro']> = {
  created: ['Registrado', 'ok'], updated: ['Atualizado', 'destaque'], deleted: ['Excluído', 'perigo'], restored: ['Restaurado', 'ok'],
};

export function LancamentoView({ dados, meta, bridge, embutido }: {
  dados: Record<string, unknown>; meta: Meta; bridge: Bridge; embutido?: boolean;
}) {
  const inicial = dados.transaction as Lancamento | undefined;
  const excluidos = (dados.deleted as Resumo[] | undefined) ?? [];
  const [tx, setTx] = useState<Lancamento | undefined>(inicial);
  const [antes, setAntes] = useState<Lancamento | undefined>(dados.previous as Lancamento | undefined);
  const [mudou, setMudou] = useState<string[]>((dados.changed as string[] | undefined) ?? []);
  const [modo, setModo] = useState(meta.mode ?? 'read');
  const [undo, setUndo] = useState<Desfazer | undefined>(meta.undo);
  const [undoEach, setUndoEach] = useState(meta.undo_each);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [historico, setHistorico] = useState<EntradaDoHistorico[] | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const acao = useAcao(bridge);
  const parcelas = (dados.installments as Resumo[] | undefined) ?? [];

  async function recarregar(id: number) {
    const r = await bridge.callTool('transactions_get', { transaction_id: id }).catch(() => null);
    if (r && !r.isError) setTx((r.structuredContent as { transaction: Lancamento }).transaction);
  }

  async function desfazer() {
    if (!undo) return;
    const alvos = undoEach && undo.tool === 'transactions_restore' ? undoEach : [undo.args];
    for (const args of alvos) {
      const r = await acao.executar(undo.tool, args);
      if (!r) return;
    }
    void bridge.updateModelContext?.(`O usuário desfez no componente: ${undo.label ?? 'a última ação'} (${undo.tool}).`);
    setUndo(undefined);
    if (modo === 'created') { setModo('deleted'); setAviso('Desfeito: o lançamento foi excluído.'); }
    else if (modo === 'deleted') {
      setModo('restored');
      setAviso('Desfeito: o lançamento voltou.');
      const id = (undo.args.transaction_id as number) ?? excluidos[0]?.id;
      if (id) await recarregar(id);
    } else if (modo === 'updated') { setModo('read'); setMudou([]); setAviso('Desfeito: os valores anteriores voltaram.'); if (tx) await recarregar(tx.id); }
    else setAviso('Desfeito.');
  }

  async function excluir(escopo: 'installment' | 'purchase') {
    if (!tx) return;
    const r = await acao.executar(
      'transactions_delete', { transaction_id: tx.id, scope: escopo, ...(tx.version ? { expected_version: tx.version } : {}) },
      `O usuário excluiu no componente o lançamento #${tx.id} ("${tx.title}")${escopo === 'purchase' ? ' (a compra inteira)' : ''}.`,
    );
    if (!r) return;
    setConfirmando(false);
    setModo('deleted');
    const ids = ((r.deleted as Resumo[] | undefined) ?? []).map((d) => d.id);
    setUndo({ tool: 'transactions_restore', args: { transaction_id: ids[0] ?? tx.id }, label: 'Desfazer' });
    setUndoEach(ids.map((i) => ({ transaction_id: i })));
  }

  async function abrirHistorico() {
    if (!tx || historico) return;
    const r = await bridge.callTool('transactions_history', { transaction_id: tx.id }).catch(() => null);
    setHistorico(r && !r.isError ? ((r.structuredContent as { entries: EntradaDoHistorico[] }).entries) : []);
    if (r?.isError) setAviso(erroDe(r).mensagem);
  }

  // Excluído sem o lançamento inteiro na saída (transactions_delete): a lista do que saiu.
  if (!tx) {
    return (
      <div class="space-y-3">
        <Header icone={<IconTrash size={18} />} tom="perigo" titulo={`${plural(excluidos.length, 'lançamento excluído', 'lançamentos excluídos')}`}
          subtitulo={modo === 'restored' ? 'Restaurado' : 'Dá para desfazer'} />
        <ul>
          {excluidos.map((e) => (
            <Linha key={e.id} titulo={e.title} detalhe={[day(e.date), e.space?.name].filter(Boolean).join(' · ')} riscada={modo !== 'restored'}
              direita={<Money valor={e.amount} moeda={e.currency} />} />
          ))}
        </ul>
        {aviso && <Aviso>{aviso}</Aviso>}
        {acao.erro && <Aviso tom="erro">{acao.erro.mensagem}</Aviso>}
        {undo && modo === 'deleted' && (
          <Button icone={<IconUndo size={14} />} carregando={acao.estado === 'enviando'} onClick={() => void desfazer()}>Desfazer exclusão</Button>
        )}
      </div>
    );
  }

  const cancelado = tx.status === 'cancelled';
  const excluido = modo === 'deleted';
  const [rotuloModo, tomModo] = MODO[modo] ?? [null, 'neutro'];
  const dividido = (tx.split ?? []).length > 1;
  const compra = tx.purchase;
  // Parcela de compra com itens: a nota aparece uma vez só, a da compra inteira.
  const itens = compra?.items?.length ? [] : tx.items ?? [];
  const podeEditar = Boolean(meta.can_edit && meta.form) && !excluido;

  return (
    <div class="space-y-3">
      {!embutido && <Header
        icone={tx.card ? <IconCard size={18} /> : <IconReceipt size={18} />}
        tom={excluido ? 'perigo' : modo === 'created' ? 'ok' : 'destaque'}
        titulo={tx.title} riscado={cancelado || excluido}
        subtitulo={[day(tx.date), tx.merchant?.name, tx.space?.name, tx.category?.name].filter(Boolean).join(' · ')}
        direita={
          <>
            <Money valor={tx.amount} moeda={tx.currency} class="text-[17px] font-semibold" />
            {tx.foreign && <p class="num text-[11px] text-muted-fg">{money(tx.foreign.original_amount, tx.foreign.original_currency)} convertidos</p>}
            {dividido && <p class="text-[11px] text-muted-fg">sua parte <Money valor={tx.my_share} moeda={tx.currency} class="font-medium text-fg" /></p>}
          </>
        }
      />}
      <div class="flex flex-wrap gap-1.5">
        {rotuloModo && <Badge tom={tomModo}>{rotuloModo}</Badge>}
        {cancelado ? <Badge tom="perigo">Cancelado</Badge>
          : tx.card ? <Badge icone={<IconCard size={11} />}>{tx.card.name}{tx.statement ? ` · fatura de ${monthLong(tx.statement.month)}` : ''}</Badge>
          : <Badge tom={tx.settled ? 'ok' : 'aviso'}>{tx.settled ? `Pago${tx.settled_on ? ` em ${day(tx.settled_on)}` : ''}` : 'A pagar'}</Badge>}
        {tx.payment_method && !tx.card && <Badge>{FORMA[tx.payment_method] ?? tx.payment_method}</Badge>}
        {tx.installment && <Badge>Parcela {tx.installment.number}/{tx.installment.of}</Badge>}
        {(tx.tags ?? []).map((t) => <Badge key={t}>#{t}</Badge>)}
        {dados.replayed === true && <Badge tom="aviso">Já registrado antes</Badge>}
      </div>

      {modo === 'updated' && antes && <Diferenca antes={antes} depois={tx} campos={mudou} />}
      {tx.description && <p class="rounded-md bg-subtle px-3 py-2 text-[13px] text-muted-fg">{tx.description}</p>}

      {editando && meta.form ? (
        <Editor tx={tx} form={meta.form} bridge={bridge} aoCancelar={() => setEditando(false)}
          aoSalvar={(r) => {
            setAntes(r.previous as Lancamento);
            setTx(r.transaction as Lancamento);
            setMudou((r.changed as string[]) ?? []);
            setModo('updated');
            setUndo(undefined);
            setEditando(false);
          }} />
      ) : (
        <>
          {dividido && (
            <Section titulo="Divisão" contagem={plural((tx.split ?? []).length, 'pessoa', 'pessoas')} aberta>
              <Pessoas lista={tx.split ?? []} moeda={tx.currency} total={tx.amount} />
            </Section>
          )}
          {itens.length > 0 && (
            <Section titulo="Itens da nota" contagem={itens.length} aberta={itens.length <= 6}>
              <Itens itens={itens} moeda={tx.currency} />
              {(tx.adjustments ?? []).map((a, i) => (
                <div key={i} class="flex justify-between py-1 text-[13px] text-muted-fg">
                  <span>{a.description || { discount: 'Desconto', cashback: 'Cashback', tax: 'Taxa', tip: 'Gorjeta', shipping: 'Frete', rounding: 'Arredondamento' }[a.type] || 'Ajuste'}</span>
                  <Money valor={a.amount} moeda={tx.currency} tom="auto" />
                </div>
              ))}
            </Section>
          )}
          {compra && (
            <Section titulo="Compra inteira" contagem={`${compra.installments}×`} aberta={Boolean(compra.items?.length)}>
              <div class="mb-2 flex items-baseline justify-between text-[13px]">
                <span class="text-muted-fg">{compra.paid_installments} de {compra.installments} pagas</span>
                <span><Money valor={compra.amount} moeda={compra.currency} class="font-semibold" /> · sua parte <Money valor={compra.my_share} moeda={compra.currency} /></span>
              </div>
              {(compra.items ?? []).length > 0 && <Itens itens={compra.items ?? []} moeda={compra.currency} />}
              {parcelas.length > 1 && (
                <ul class="mt-2 grid grid-cols-2 gap-1 sm:grid-cols-3">
                  {parcelas.map((p) => (
                    <li key={p.id} class="flex items-center justify-between rounded-md bg-subtle px-2 py-1 text-[12px]">
                      <span class="text-muted-fg">{p.installment}</span>
                      <Money valor={p.amount} moeda={p.currency} />
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          )}
          {(tx.files ?? []).length > 0 && (
            <Section titulo="Anexos" contagem={(tx.files ?? []).length}>
              <Anexos arquivos={tx.files ?? []} bridge={bridge} />
            </Section>
          )}
          <Section titulo="Histórico" direita={<IconHistory size={14} />}>
            <HistoricoCarregando entradas={historico} aoAbrir={() => void abrirHistorico()} />
          </Section>
        </>
      )}

      {aviso && <Aviso>{aviso}</Aviso>}
      {acao.erro && !editando && <Aviso tom="erro">{acao.erro.mensagem}</Aviso>}

      {!editando && (
        <div class="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {undo && modo !== 'read' && (
            <Button icone={<IconUndo size={14} />} carregando={acao.estado === 'enviando'} onClick={() => void desfazer()}>{undo.label ?? 'Desfazer'}</Button>
          )}
          {podeEditar && <Button icone={<IconPencil size={14} />} onClick={() => setEditando(true)}>Editar</Button>}
          {podeEditar && !confirmando && tx.status !== 'paid' && (
            <Button variante="ghost" icone={<IconTrash size={14} />} onClick={() => setConfirmando(true)}>Excluir</Button>
          )}
          {confirmando && (
            <span class="flex flex-wrap items-center gap-2">
              <span class="text-[13px] text-muted-fg">Excluir{tx.installment ? '' : ' este lançamento'}?</span>
              {tx.installment && <Button variante="danger" carregando={acao.estado === 'enviando'} onClick={() => void excluir('installment')}>Só esta parcela</Button>}
              <Button variante="danger" carregando={acao.estado === 'enviando'} onClick={() => void excluir(tx.installment ? 'purchase' : 'installment')}>
                {tx.installment ? 'A compra inteira' : 'Excluir'}
              </Button>
              <Button variante="ghost" onClick={() => setConfirmando(false)}>Não</Button>
            </span>
          )}
          <span class="flex-1" />
          {(meta.app_url ?? tx.app_url) && (
            <Button variante="ghost" icone={<IconExternal size={14} />} onClick={() => bridge.openLink((meta.app_url ?? tx.app_url)!)}>Abrir no app</Button>
          )}
        </div>
      )}
    </div>
  );
}

function HistoricoCarregando({ entradas, aoAbrir }: { entradas: EntradaDoHistorico[] | null; aoAbrir: () => void }) {
  if (entradas === null) {
    aoAbrir();
    return <p class="text-[12px] text-muted-fg">Carregando…</p>;
  }
  return <Historico entradas={entradas} />;
}
