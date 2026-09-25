/** @jsxImportSource preact */
/**
 * Recorrências (despesa e renda), rendas do mês e financiamentos — tanto a lista
 * (`view_show`) quanto o resultado de uma escrita (criada, editada, excluída), com
 * pausar/retomar, excluir com Desfazer, marcar renda recebida e pagar parcela.
 */
import type { ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, FORMA, money, monthTitle, plural } from '../format';
import type { Meta, PessoaValor, Ref } from '../tipos';
import { useAcao } from '../ui/acao';
import { Aviso, Avatar, Badge, Button, Header, Linha, Money, Progress, Section, Stat, Vazio } from '../ui/base';
import { IconBank, IconCheck, IconExternal, IconRepeat, IconTrash, IconUndo, IconWallet } from '../ui/icons';
import { BotaoDesfazer, Mudancas } from '../ui/mudancas';
import { CarregarMais } from '../ui/lista';
import { usePaginas } from '../ui/paginas';

const MODO: Record<string, [string, 'ok' | 'destaque' | 'perigo']> = {
  created: ['Criada', 'ok'], updated: ['Atualizada', 'destaque'], deleted: ['Excluída', 'perigo'], restored: ['Restaurada', 'ok'],
};

// --- Recorrências ----------------------------------------------------------------

interface Recorrencia {
  id: number; kind: string; space?: Ref | null; title: string; description?: string | null; amount: string; currency: string;
  my_share?: string | null; split?: PessoaValor[]; paid_by?: Ref | null; frequency: string; interval?: number; day_of_month?: number | null;
  active: boolean; start_date?: string | null; end_date?: string | null; next_occurrence?: string | null; occurrences_remaining?: number | null;
  payment_method?: string | null; card?: Ref | null; account?: Ref | null; category?: Ref | null; auto_settle?: boolean; version?: string;
  merchant?: Ref | null; my_monthly?: string | null;
  subscription?: { plan?: string | null; trial_ends_on?: string | null; notes?: string | null } | null;
}

/** "Teste até 12/10" enquanto o teste grátis não acabou (ADR 0039). */
function emTeste(r: Recorrencia): string | null {
  const fim = r.subscription?.trial_ends_on;
  // Dia LOCAL (o sueco escreve AAAA-MM-DD): o `toISOString` é UTC e, à noite no
  // Brasil, já seria amanhã.
  return fim && fim >= new Date().toLocaleDateString('sv') ? `teste até ${day(fim)}` : null;
}

function somaPorMoeda(itens: Recorrencia[]): Array<[string, string]> {
  const total: Record<string, number> = {};
  for (const r of itens) if (r.active && r.my_monthly) total[r.currency] = (total[r.currency] ?? 0) + Number(r.my_monthly);
  return Object.entries(total).map(([m, v]) => [m, v.toFixed(2)]);
}

const FREQUENCIA: Record<string, [string, string]> = {
  daily: ['Todo dia', 'dias'], weekly: ['Toda semana', 'semanas'], monthly: ['Todo mês', 'meses'], yearly: ['Todo ano', 'anos'],
};
function frequencia(r: Recorrencia): string {
  const [um, varios] = FREQUENCIA[r.frequency] ?? [r.frequency, r.frequency];
  const base = (r.interval ?? 1) > 1 ? `A cada ${r.interval} ${varios}` : um;
  return r.frequency === 'monthly' && r.day_of_month ? `${base}, dia ${r.day_of_month}` : base;
}

function DetalheDaRecorrencia({ r }: { r: Recorrencia }) {
  const linhas: Array<[string, ComponentChildren]> = [
    ['Frequência', frequencia(r)],
    ['Próxima', r.next_occurrence ? day(r.next_occurrence) : '—'],
    ['Começa', day(r.start_date)],
    ['Termina', r.end_date ? day(r.end_date) : r.occurrences_remaining ? plural(r.occurrences_remaining, 'ocorrência restante', 'ocorrências restantes') : 'Sem fim'],
    ['Categoria', r.category?.name ?? 'Sem categoria'],
    ['Pagamento', r.card ? `Cartão ${r.card.name}` : r.payment_method ? FORMA[r.payment_method] ?? r.payment_method : '—'],
  ];
  if (r.account) linhas.push(['Conta', r.account.name]);
  if (r.paid_by) linhas.push(['Quem paga', r.paid_by.name]);
  if (r.kind === 'expense' && !r.card) linhas.push(['Paga sozinha', r.auto_settle ? 'Sim' : 'Não']);
  if (r.merchant) linhas.push(['Estabelecimento', r.merchant.name]);
  if (r.subscription?.plan) linhas.push(['Plano', r.subscription.plan]);
  if (r.subscription?.trial_ends_on) linhas.push(['Teste grátis até', day(r.subscription.trial_ends_on)]);
  // Por mês só diz algo novo quando a série não é mensal (ou é "a cada N").
  if (r.my_monthly && (r.frequency !== 'monthly' || (r.interval ?? 1) > 1)) linhas.push(['Sua parte por mês', money(r.my_monthly, r.currency)]);
  return (
    <div class="space-y-2 text-[13px]">
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {linhas.flatMap(([k, v]) => [<dt key={`k-${k}`} class="text-muted-fg">{k}</dt>, <dd key={`v-${k}`} class="min-w-0 truncate">{v}</dd>])}
      </dl>
      {(r.split ?? []).length > 1 && (
        <ul class="space-y-1">
          {(r.split ?? []).map((p) => (
            <li key={p.person.id} class="flex items-center gap-2">
              <Avatar nome={p.person.name} /> <span class="flex-1">{p.person.name}{p.is_me && ' (você)'}</span> <Money valor={p.amount} moeda={r.currency} />
            </li>
          ))}
        </ul>
      )}
      {r.description && <p class="text-muted-fg">{r.description}</p>}
      {r.subscription?.notes && <p class="rounded-md bg-subtle px-3 py-2 text-muted-fg">{r.subscription.notes}</p>}
    </div>
  );
}

function LinhaDeRecorrencia({ inicial, bridge, podeEditar }: { inicial: Recorrencia; bridge: Bridge; podeEditar: boolean }) {
  const [r, setR] = useState(inicial);
  const [aberta, setAberta] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [excluida, setExcluida] = useState(false);
  const exec = useAcao(bridge);
  const renda = r.kind === 'income';

  async function alternar() {
    const res = await exec.executar('recurring_update', { recurring_id: r.id, kind: r.kind, active: !r.active, ...(r.version ? { expected_version: r.version } : {}) },
      `O usuário ${r.active ? 'pausou' : 'retomou'} pelo componente a recorrência "${r.title}".`);
    if (res?.recurring) setR(res.recurring as Recorrencia);
  }
  async function excluir() {
    const res = await exec.executar('recurring_delete', { recurring_id: r.id, kind: r.kind, ...(r.version ? { expected_version: r.version } : {}) },
      `O usuário excluiu pelo componente a recorrência "${r.title}".`);
    if (res) setExcluida(true);
  }

  return (
    <Linha titulo={r.title} riscada={excluida || !r.active}
      esquerda={<span class={`inline-flex size-8 shrink-0 items-center justify-center rounded-md ${renda ? 'bg-ok-bg text-income' : 'bg-muted text-muted-fg'}`}><IconRepeat size={15} /></span>}
      detalhe={[r.subscription?.plan, frequencia(r), r.next_occurrence && `próxima ${day(r.next_occurrence)}`, r.space?.name].filter(Boolean).join(' · ')}
      direita={
        <>
          <Money valor={r.amount} moeda={r.currency} tom={renda ? 'entrada' : undefined} class="font-medium" />
          {r.my_share && r.my_share !== r.amount && <span class="block text-[11px] text-muted-fg">sua parte {money(r.my_share, r.currency)}</span>}
          {(excluida || !r.active) && <span class="block"><Badge tom={excluida ? 'perigo' : 'aviso'}>{excluida ? 'excluída' : 'pausada'}</Badge></span>}
          {!excluida && r.active && emTeste(r) && <span class="block"><Badge tom="aviso">{emTeste(r)}</Badge></span>}
        </>
      }
      onClick={() => setAberta(!aberta)} expandida={aberta}>
      <div class="space-y-2">
        <DetalheDaRecorrencia r={r} />
        {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
        {podeEditar && !excluida && (
          <div class="flex flex-wrap gap-2">
            <Button carregando={exec.estado === 'enviando'} onClick={() => void alternar()}>{r.active ? 'Pausar' : 'Retomar'}</Button>
            {!confirmando ? <Button variante="ghost" icone={<IconTrash size={14} />} onClick={() => setConfirmando(true)}>Excluir</Button> : (
              <span class="flex flex-wrap items-center gap-2">
                <span class="text-[12px] text-muted-fg">Os lançamentos já criados ficam.</span>
                <Button variante="danger" carregando={exec.estado === 'enviando'} onClick={() => void excluir()}>Excluir</Button>
                <Button variante="ghost" onClick={() => setConfirmando(false)}>Não</Button>
              </span>
            )}
          </div>
        )}
      </div>
    </Linha>
  );
}

const ROTULO_RECORRENCIA: Record<string, string> = {
  title: 'Título', amount: 'Valor', active: 'Ativa', frequency: 'Frequência', interval: 'Intervalo', day_of_month: 'Dia',
  start_date: 'Começa', end_date: 'Termina', category: 'Categoria', card: 'Cartão', payment_method: 'Forma', account: 'Conta',
  paid_by: 'Quem paga', split: 'Divisão', auto_settle: 'Paga sozinha', description: 'Observação',
  merchant: 'Estabelecimento', subscription: 'Assinatura',
};
function textoDaRecorrencia(c: string, r: Recorrencia): string {
  const v = (r as unknown as Record<string, unknown>)[c];
  if (c === 'amount') return money(r.amount, r.currency);
  if (c === 'active' || c === 'auto_settle') return v ? 'Sim' : 'Não';
  if (c.endsWith('_date')) return day(v as string);
  if (c === 'frequency' || c === 'interval' || c === 'day_of_month') return frequencia(r);
  if (c === 'split') return (r.split ?? []).map((p) => `${p.person.name} ${money(p.amount, r.currency)}`).join(' · ') || '—';
  if (c === 'subscription') {
    if (!r.subscription) return 'Não';
    const { plan, trial_ends_on } = r.subscription;
    return [plan ?? 'Sim', trial_ends_on && `teste até ${day(trial_ends_on)}`].filter(Boolean).join(' · ');
  }
  if (v && typeof v === 'object' && 'name' in v) return String((v as Ref).name);
  return v === null || v === undefined || v === '' ? '—' : String(v);
}

export function RecorrenciasView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const unica = (dados.recurring ?? dados.deleted) as Recorrencia | undefined;
  if (unica) {
    const [rotulo, tom] = MODO[meta.mode ?? ''] ?? ['', 'destaque'];
    const antes = dados.previous as Recorrencia | undefined;
    const mudou = ((dados.changed as string[] | undefined) ?? []).filter((c) => ROTULO_RECORRENCIA[c]);
    const canceladas = (dados.cancelled_occurrences as number[] | undefined) ?? [];
    return (
      <div class="space-y-3">
        <Header icone={<IconRepeat size={18} />} tom={tom} titulo={unica.title} riscado={meta.mode === 'deleted'}
          subtitulo={`${unica.kind === 'income' ? 'Renda recorrente' : 'Despesa recorrente'}${unica.space ? ` · ${unica.space.name}` : ''}`}
          direita={<Money valor={unica.amount} moeda={unica.currency} class="text-[17px] font-semibold" />} />
        <div class="flex flex-wrap gap-1.5">
          {rotulo && <Badge tom={tom}>{rotulo}</Badge>}
          {unica.subscription && <Badge>Assinatura</Badge>}
          {emTeste(unica) && <Badge tom="aviso">{emTeste(unica)}</Badge>}
          {!unica.active && <Badge tom="aviso">Pausada</Badge>}
          {dados.replayed === true && <Badge tom="aviso">Já registrada antes</Badge>}
        </div>
        {antes && <Mudancas linhas={[...new Set(mudou.map((c) => (['frequency', 'interval', 'day_of_month'].includes(c) ? 'frequency' : c)))].map((c) =>
          [ROTULO_RECORRENCIA[c], textoDaRecorrencia(c, antes), textoDaRecorrencia(c, unica)])} />}
        {canceladas.length > 0 && <Aviso tom="info">{plural(canceladas.length, 'ocorrência em aberto cancelada', 'ocorrências em aberto canceladas')}.</Aviso>}
        {meta.mode !== 'deleted' && <DetalheDaRecorrencia r={unica} />}
        <BotaoDesfazer undo={meta.undo} bridge={bridge} feito="Desfeito: a recorrência foi excluída." />
      </div>
    );
  }
  const itens = (dados.items as Recorrencia[] | undefined) ?? [];
  const mensal = Object.entries((dados.monthly_my_share as Record<string, string> | undefined) ?? {});
  // Assinaturas num grupo próprio, com o custo delas por mês (ADR 0039).
  const assinaturas = itens.filter((r) => r.kind !== 'income' && r.subscription);
  const despesas = itens.filter((r) => r.kind !== 'income' && !r.subscription);
  const rendas = itens.filter((r) => r.kind === 'income');
  const porMesAssinaturas = somaPorMoeda(assinaturas);
  const podeEditar = meta.can_edit !== false;
  return (
    <div class="space-y-3">
      <Header icone={<IconRepeat size={18} />} tom="destaque" titulo="Recorrências" subtitulo={plural(itens.length, 'recorrência', 'recorrências')}
        direita={mensal.length ? <><p class="text-[11px] text-muted-fg">Sua parte por mês</p><p class="num text-[15px] font-semibold">{mensal.map(([m, v]) => money(v, m)).join(' + ')}</p></> : undefined} />
      {itens.length === 0 && <Vazio>Nenhuma recorrência.</Vazio>}
      {assinaturas.length > 0 && (
        <Section titulo="Assinaturas" contagem={assinaturas.length} aberta
          direita={porMesAssinaturas.length ? <span class="num font-medium normal-case tracking-normal text-fg">{porMesAssinaturas.map(([m, v]) => money(v, m)).join(' + ')}/mês</span> : undefined}>
          <ul>{assinaturas.map((r) => <LinhaDeRecorrencia key={`s${r.id}`} inicial={r} bridge={bridge} podeEditar={podeEditar} />)}</ul>
        </Section>
      )}
      {despesas.length > 0 && (
        <Section titulo="Despesas" contagem={despesas.length} aberta>
          <ul>{despesas.map((r) => <LinhaDeRecorrencia key={`e${r.id}`} inicial={r} bridge={bridge} podeEditar={podeEditar} />)}</ul>
        </Section>
      )}
      {rendas.length > 0 && (
        <Section titulo="Rendas" contagem={rendas.length} aberta>
          <ul>{rendas.map((r) => <LinhaDeRecorrencia key={`i${r.id}`} inicial={r} bridge={bridge} podeEditar={podeEditar} />)}</ul>
        </Section>
      )}
    </div>
  );
}

// --- Rendas ----------------------------------------------------------------------

interface Renda {
  id: number; title: string; description?: string | null; amount: string; currency: string; date: string; received_on?: string | null;
  status: string; category?: string | null; account?: Ref | null; recurring?: boolean; version?: string;
  original_amount?: string | null; original_currency?: string | null;
}
const SITUACAO_DA_RENDA: Record<string, [string, 'ok' | 'aviso' | 'perigo' | 'neutro']> = {
  received: ['Recebida', 'ok'], expected: ['Prevista', 'aviso'], overdue: ['Atrasada', 'perigo'], cancelled: ['Cancelada', 'neutro'],
};

function LinhaDeRenda({ inicial, bridge }: { inicial: Renda; bridge: Bridge }) {
  const [r, setR] = useState(inicial);
  const [excluida, setExcluida] = useState(false);
  const exec = useAcao(bridge);
  const [rotulo, tom] = SITUACAO_DA_RENDA[r.status] ?? [r.status, 'neutro'];
  async function receber() {
    const res = await exec.executar('income_update', { income_id: r.id, status: 'received', ...(r.version ? { expected_version: r.version } : {}) },
      `O usuário marcou pelo componente a renda "${r.title}" como recebida.`);
    if (res?.income) setR(res.income as Renda);
  }
  async function excluir() {
    if (excluida) {
      const res = await exec.executar('income_restore', { income_id: r.id }, `O usuário restaurou pelo componente a renda "${r.title}".`);
      if (res?.income) { setR(res.income as Renda); setExcluida(false); }
      return;
    }
    const res = await exec.executar('income_delete', { income_id: r.id, ...(r.version ? { expected_version: r.version } : {}) },
      `O usuário excluiu pelo componente a renda "${r.title}".`);
    if (res) setExcluida(true);
  }
  return (
    <>
    <Linha titulo={r.title} riscada={excluida}
      esquerda={<span class="inline-flex size-8 shrink-0 items-center justify-center rounded-md bg-ok-bg text-income"><IconWallet size={15} /></span>}
      detalhe={[day(r.received_on ?? r.date), r.category, r.account?.name, r.recurring && 'recorrente'].filter(Boolean).join(' · ')}
      direita={
        <span class="flex items-center gap-2">
          <span class="text-right">
            <Money valor={r.amount} moeda={r.currency} tom="entrada" class="font-medium" />
            <span class="block"><Badge tom={excluida ? 'perigo' : tom}>{excluida ? 'excluída' : rotulo}</Badge></span>
          </span>
          {!excluida && (r.status === 'expected' || r.status === 'overdue') && (
            <button type="button" class="w-icon-btn" aria-label={`Marcar ${r.title} como recebida`} title="Recebi" disabled={exec.estado === 'enviando'} onClick={() => void receber()}><IconCheck size={15} /></button>
          )}
          <button type="button" class="w-icon-btn" aria-label={excluida ? `Restaurar ${r.title}` : `Excluir ${r.title}`} title={excluida ? 'Desfazer' : 'Excluir'}
            disabled={exec.estado === 'enviando'} onClick={() => void excluir()}>{excluida ? <IconUndo size={15} /> : <IconTrash size={15} />}</button>
        </span>
      } />
    {exec.erro && <li class="list-none"><Aviso tom="erro">{exec.erro.mensagem}</Aviso></li>}
    </>
  );
}

export function RendaView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const unica = (dados.income ?? dados.deleted) as Renda | undefined;
  if (unica) {
    const [rotulo, tom] = MODO[meta.mode ?? ''] ?? ['', 'destaque'];
    const antes = dados.previous as Renda | undefined;
    const mudou = (dados.changed as string[] | undefined) ?? [];
    const texto = (c: string, r: Renda) => (c === 'amount' ? money(r.amount, r.currency) : c === 'date' || c === 'received_on' ? day((r as unknown as Record<string, string>)[c])
      : c === 'status' ? SITUACAO_DA_RENDA[r.status]?.[0] ?? r.status : c === 'account' ? r.account?.name ?? '—' : String((r as unknown as Record<string, unknown>)[c] ?? '—'));
    const ROTULO: Record<string, string> = { title: 'Título', amount: 'Valor', date: 'Competência', received_on: 'Recebida em', status: 'Situação', category: 'Categoria', account: 'Conta', description: 'Observação' };
    return (
      <div class="space-y-3">
        <Header icone={<IconWallet size={18} />} tom={tom} titulo={unica.title} riscado={meta.mode === 'deleted'}
          subtitulo={[day(unica.received_on ?? unica.date), unica.account?.name, unica.category].filter(Boolean).join(' · ')}
          direita={<Money valor={unica.amount} moeda={unica.currency} tom="entrada" class="text-[17px] font-semibold" />} />
        <div class="flex flex-wrap gap-1.5">
          {rotulo && <Badge tom={tom}>{rotulo}</Badge>}
          <Badge tom={SITUACAO_DA_RENDA[unica.status]?.[1] ?? 'neutro'}>{SITUACAO_DA_RENDA[unica.status]?.[0] ?? unica.status}</Badge>
          {unica.original_currency && <Badge>{money(unica.original_amount, unica.original_currency)} convertidos</Badge>}
          {dados.replayed === true && <Badge tom="aviso">Já registrada antes</Badge>}
        </div>
        {antes && <Mudancas linhas={mudou.filter((c) => ROTULO[c]).map((c) => [ROTULO[c], texto(c, antes), texto(c, unica)])} />}
        <BotaoDesfazer undo={meta.undo} bridge={bridge} feito={meta.mode === 'deleted' ? 'Desfeito: a renda voltou.' : 'Desfeito: a renda foi excluída.'} />
      </div>
    );
  }
  const rendas = (dados.incomes as Renda[] | undefined) ?? [];
  const totais = Object.entries((dados.currency_totals as Record<string, string> | undefined) ?? {});
  return (
    <div class="space-y-3">
      <Header icone={<IconWallet size={18} />} tom="ok" titulo="Rendas" subtitulo={monthTitle(dados.month as string)}
        direita={<p class="num text-[15px] font-semibold text-income">{totais.map(([m, v]) => money(v, m)).join(' + ') || '—'}</p>} />
      {rendas.length === 0 ? <Vazio>Nenhuma renda no mês.</Vazio> : <ul>{rendas.map((r) => <LinhaDeRenda key={r.id} inicial={r} bridge={bridge} />)}</ul>}
    </div>
  );
}

// --- Financiamento ---------------------------------------------------------------

interface Financiamento {
  id: number; title: string; status: string; currency: string; amount: string; monthly_rate?: string | null; start_date: string;
  installments: number; paid_installments: number; remaining_installments: number; outstanding: string;
  next_due_date?: string | null; next_amount?: string | null; overdue_count: number; app_url?: string;
}
interface ParcelaDoCronograma {
  number: number; due_date: string; principal: string; interest: string; total: string; remaining_balance: string;
  paid: boolean; paid_on?: string | null; account?: Ref | null; overdue: boolean;
}

function Cronograma({ f, dados, bridge }: { f: Financiamento; dados: Record<string, unknown>; bridge: Bridge }) {
  const consulta = { tool: 'financings_list', args: { financing_id: f.id } };
  const pagina = usePaginas<ParcelaDoCronograma>(bridge, consulta, (dados.schedule as ParcelaDoCronograma[]) ?? [], dados.next_cursor as string | null, 'schedule');
  const [pagas, setPagas] = useState<Record<number, boolean>>({});
  const exec = useAcao(bridge);
  async function alternar(p: ParcelaDoCronograma, pagar: boolean) {
    const r = await exec.executar('financings_installment', { action: pagar ? 'pay' : 'unpay', financing_id: f.id, installment: p.number },
      `O usuário ${pagar ? 'pagou a' : 'desfez o pagamento da'} parcela ${p.number} de "${f.title}" pelo componente.`);
    if (r) setPagas((m) => ({ ...m, [p.number]: pagar }));
  }
  const proxima = pagina.itens.find((p) => !(pagas[p.number] ?? p.paid))?.number;
  return (
    <>
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      <ul>
        {pagina.itens.map((p) => {
          const paga = pagas[p.number] ?? p.paid;
          return (
            <Linha key={p.number} titulo={`Parcela ${p.number}`}
              detalhe={[`vence ${day(p.due_date)}`, paga ? `paga${p.paid_on ? ` em ${day(p.paid_on)}` : ''}` : p.overdue ? 'atrasada' : null, `saldo ${money(p.remaining_balance, f.currency)}`].filter(Boolean).join(' · ')}
              direita={
                <span class="flex items-center gap-2">
                  <span class="text-right">
                    <Money valor={p.total} moeda={f.currency} class="font-medium" />
                    <span class="block text-[11px] text-muted-fg">juros {money(p.interest, f.currency)}</span>
                  </span>
                  {paga ? (
                    <button type="button" class="w-icon-btn" aria-label={`Desfazer pagamento da parcela ${p.number}`} title="Desfazer pagamento" disabled={exec.estado === 'enviando'} onClick={() => void alternar(p, false)}><IconUndo size={15} /></button>
                  ) : p.number === proxima ? (
                    <Button variante="ghost" icone={<IconCheck size={14} />} carregando={exec.estado === 'enviando'} onClick={() => void alternar(p, true)}>Pagar</Button>
                  ) : null}
                </span>
              } />
          );
        })}
      </ul>
      <CarregarMais pagina={pagina} total={f.installments} mostrados={pagina.itens.length} />
    </>
  );
}

export function FinanciamentoView({ dados, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const lista = (dados.financings as Financiamento[] | undefined) ?? (dados.financing ? [dados.financing as Financiamento] : []);
  const umSo = lista.length === 1 && Array.isArray(dados.schedule);
  if (!lista.length) return <Vazio>Nenhum financiamento.</Vazio>;
  return (
    <div class="space-y-4">
      {lista.map((f) => (
        <div key={f.id} class="space-y-3">
          <Header icone={<IconBank size={18} />} tom={f.overdue_count ? 'perigo' : 'destaque'} titulo={f.title}
            subtitulo={`${f.paid_installments} de ${f.installments} pagas${f.monthly_rate ? ` · ${(Number(f.monthly_rate) * 100).toFixed(2).replace('.', ',')}% a.m.` : ''}`}
            direita={<><p class="text-[11px] text-muted-fg">Saldo devedor</p><Money valor={f.outstanding} moeda={f.currency} class="text-[15px] font-semibold" /></>} />
          <Progress valor={f.paid_installments} maximo={f.installments} tom="ok" />
          <div class="grid grid-cols-2 gap-2">
            <Stat rotulo="Próxima parcela">{f.next_amount ? money(f.next_amount, f.currency) : '—'}</Stat>
            <Stat rotulo="Vence">{f.next_due_date ? day(f.next_due_date) : '—'}</Stat>
          </div>
          {f.overdue_count > 0 && <Aviso tom="erro">{plural(f.overdue_count, 'parcela atrasada', 'parcelas atrasadas')}.</Aviso>}
          {meta.tool === 'financings_installment' && (
            <>
              <Aviso>{dados.action === 'pay' ? `Parcela ${dados.installment} paga.` : `Pagamento da parcela ${dados.installment} desfeito.`}</Aviso>
              <BotaoDesfazer undo={meta.undo} bridge={bridge} feito="Desfeito." />
            </>
          )}
          {umSo && (
            <Section titulo="Cronograma" contagem={f.installments} aberta>
              <Cronograma f={f} dados={dados} bridge={bridge} />
            </Section>
          )}
          {f.app_url && <Button variante="ghost" icone={<IconExternal size={14} />} onClick={() => bridge.openLink(f.app_url!)}>Abrir no app</Button>}
        </div>
      ))}
    </div>
  );
}

