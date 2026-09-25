/** @jsxImportSource preact */
/**
 * Dívidas entre pessoas (com Registrar acerto), contas a pagar (Marcar como paga,
 * Pagar fatura, Pagar parcela) e metas do mês (com a edição da meta).
 *
 * Cada botão chama a tool de escrita de sempre; depois, a tela é relida pela
 * consulta original (`_meta.query`), para os números voltarem do servidor.
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, money, monthLong, monthTitle, plural } from '../format';
import type { Meta, Ref } from '../tipos';
import { erroDe, novaChave, useAcao } from '../ui/acao';
import { Aviso, Avatar, Badge, Button, Header, Linha, Money, Progress, Section, Stat, Vazio } from '../ui/base';
import { Campo, Dinheiro, Escolha } from '../ui/form';
import { IconAlert, IconCalendar, IconChart, IconCheck, IconPencil, IconTrash, IconUsers } from '../ui/icons';

/** Relê a tela pela consulta que a desenhou. */
function useReler(bridge: Bridge, meta: Meta, inicial: Record<string, unknown>) {
  const [dados, setDados] = useState(inicial);
  const [erro, setErro] = useState<string | null>(null);
  async function reler() {
    if (!meta.query) return;
    const r = await bridge.callTool(meta.query.tool, meta.query.args).catch(() => null);
    if (r && !r.isError) setDados((r.structuredContent ?? {}) as Record<string, unknown>);
    else setErro(r ? erroDe(r).mensagem : 'Não foi possível atualizar.');
  }
  return { dados, erro, reler };
}

// --- Dívidas ---------------------------------------------------------------------

interface Saldo { person: Ref; direction: 'owes_you' | 'you_owe'; amount: string }
interface EspacoDeDivida { space: Ref; currency: string; balances: Saldo[]; to_pay: string; to_receive: string }
interface Acerto { id: number; space: Ref; counterparty: Ref; direction: string; amount: string; currency: string; date: string; note?: string | null }

function Acertar({ saldo, espaco, moeda, mes, bridge, aoAcertar }: {
  saldo: Saldo; espaco: Ref; moeda: string; mes?: string; bridge: Bridge; aoAcertar: (texto: string) => void;
}) {
  const [aberto, setAberto] = useState(false);
  const [valor, setValor] = useState(saldo.amount);
  const exec = useAcao(bridge);
  const recebi = saldo.direction === 'owes_you';
  async function registrar() {
    const r = await exec.executar('settlements_create', {
      idempotency_key: novaChave(), person_id: saldo.person.id, direction: recebi ? 'they_paid_me' : 'i_paid_them',
      amount: valor, space_id: espaco.id, ...(mes ? { month: mes } : {}),
    }, `O usuário registrou pelo componente um acerto de ${money(valor, moeda)} com ${saldo.person.name} (${espaco.name}).`);
    if (r) {
      setAberto(false);
      aoAcertar(`Acerto de ${money(valor, moeda)} com ${saldo.person.name} registrado.`);
    }
  }
  if (!aberto) return <Button variante="ghost" icone={<IconCheck size={14} />} onClick={() => setAberto(true)}>{recebi ? 'Recebi' : 'Paguei'}</Button>;
  return (
    <div class="w-aparece mt-1 flex flex-wrap items-end gap-2 rounded-lg border border-border p-2">
      <div class="min-w-32 flex-1">
        <Campo rotulo={recebi ? `${saldo.person.name} te pagou` : `Você pagou ${saldo.person.name}`}>
          {(id) => <Dinheiro id={id} valor={valor} aoMudar={setValor} moeda={moeda} />}
        </Campo>
      </div>
      <Button variante="ghost" onClick={() => setAberto(false)}>Cancelar</Button>
      <Button variante="primary" disabled={!valor} carregando={exec.estado === 'enviando'} onClick={() => void registrar()}>Registrar</Button>
      {exec.erro && <div class="w-full"><Aviso tom="erro">{exec.erro.mensagem}</Aviso></div>}
    </div>
  );
}

function AcertoDoHistorico({ a, bridge, aoMudar }: { a: Acerto; bridge: Bridge; aoMudar: (t: string) => void }) {
  const [confirmando, setConfirmando] = useState(false);
  const exec = useAcao(bridge);
  async function excluir() {
    const r = await exec.executar('settlements_delete', { settlement_id: a.id },
      `O usuário excluiu pelo componente o acerto #${a.id} de ${money(a.amount, a.currency)} com ${a.counterparty.name}.`);
    if (r) aoMudar('Acerto excluído: o saldo entre vocês voltou.');
  }
  return (
    <Linha esquerda={<Avatar nome={a.counterparty.name} />}
      titulo={a.direction === 'paid' ? `Você pagou ${a.counterparty.name}` : `${a.counterparty.name} te pagou`}
      detalhe={[day(a.date), a.space.name, a.note].filter(Boolean).join(' · ')}
      direita={
        confirmando ? (
          <span class="flex gap-1">
            <Button variante="danger" carregando={exec.estado === 'enviando'} onClick={() => void excluir()}>Excluir</Button>
            <Button variante="ghost" onClick={() => setConfirmando(false)}>Não</Button>
          </span>
        ) : (
          <span class="flex items-center gap-1">
            <Money valor={a.amount} moeda={a.currency} />
            <button type="button" class="w-icon-btn" aria-label="Excluir acerto" title="Excluir acerto" onClick={() => setConfirmando(true)}><IconTrash size={14} /></button>
          </span>
        )
      } />
  );
}

export function DividasView({ dados: inicial, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const { dados, erro, reler } = useReler(bridge, meta, inicial);
  const [aviso, setAviso] = useState<string | null>(null);
  const moeda = (dados.currency as string) ?? 'BRL';
  const espacos = (dados.spaces as EspacoDeDivida[] | undefined) ?? [];
  const historico = (dados.history as Acerto[] | undefined) ?? [];
  const mes = dados.month as string | undefined;
  const feito = (t: string) => { setAviso(t); void reler(); };
  const saldos = espacos.flatMap((e) => e.balances.map((b) => ({ ...b, espaco: e })));

  return (
    <div class="space-y-3">
      <Header icone={<IconUsers size={18} />} tom="destaque" titulo="Entre pessoas"
        subtitulo={dados.scope === 'month' && mes ? `Retrato de ${monthLong(mes)}` : 'Saldo em aberto'} />
      <div class="grid grid-cols-2 gap-2">
        <Stat rotulo="Você deve" tom="saida">{money(dados.to_pay as string, moeda)}</Stat>
        <Stat rotulo="Tem a receber" tom="entrada">{money(dados.to_receive as string, moeda)}</Stat>
      </div>
      {aviso && <Aviso>{aviso}</Aviso>}
      {erro && <Aviso tom="erro">{erro}</Aviso>}
      {saldos.length === 0 ? <Vazio>Tudo acertado.</Vazio> : (
        <ul class="space-y-1">
          {saldos.map((s) => (
            <li key={`${s.espaco.space.id}-${s.person.id}`} class="list-none rounded-lg px-1 py-1.5">
              <div class="flex items-center gap-2">
                <Avatar nome={s.person.name} tamanho={28} />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[14px]">{s.direction === 'owes_you' ? `${s.person.name} te deve` : `Você deve a ${s.person.name}`}</p>
                  <p class="truncate text-[12px] text-muted-fg">{s.espaco.space.name}</p>
                </div>
                <Money valor={s.amount} moeda={s.espaco.currency} tom={s.direction === 'owes_you' ? 'entrada' : 'saida'} class="font-semibold" />
              </div>
              <div class="mt-1 flex justify-end">
                <Acertar saldo={s} espaco={s.espaco.space} moeda={s.espaco.currency} mes={dados.scope === 'month' ? mes : undefined} bridge={bridge} aoAcertar={feito} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {historico.length > 0 && (
        <Section titulo="Acertos" contagem={historico.length}>
          <ul>{historico.map((a) => <AcertoDoHistorico key={a.id} a={a} bridge={bridge} aoMudar={feito} />)}</ul>
        </Section>
      )}
    </div>
  );
}

// --- A pagar ---------------------------------------------------------------------

interface Conta { transaction_id: number; space: Ref; title: string; due_date: string; amount: string; currency: string; overdue: boolean; installment?: string | null }
interface FaturaAPagar { card: Ref; statement_id: number; month: string; due_date: string; amount: string; overdue: boolean }
interface Parcela { financing_id: number; title: string; next_due_date?: string | null; next_amount?: string | null; outstanding: string; remaining_installments: number; overdue_count: number }

function PagarFatura({ f, moeda, contas, bridge, aoPagar }: {
  f: FaturaAPagar; moeda: string; contas: Array<Ref & { currency: string }>; bridge: Bridge; aoPagar: (t: string) => void;
}) {
  const [aberto, setAberto] = useState(false);
  const [conta, setConta] = useState(contas[0] ? String(contas[0].id) : '');
  const exec = useAcao(bridge);
  async function pagar() {
    const r = await exec.executar('statements_pay', {
      idempotency_key: novaChave(), card_id: f.card.id, month: f.month, ...(conta ? { account_id: Number(conta) } : {}),
    }, `O usuário pagou pelo componente a fatura de ${monthLong(f.month)} do cartão ${f.card.name}.`);
    if (r) aoPagar(`Fatura do ${f.card.name} paga.`);
  }
  if (!aberto) return <Button variante="ghost" icone={<IconCheck size={14} />} onClick={() => setAberto(true)}>Pagar</Button>;
  return (
    <div class="w-aparece mt-1 flex flex-wrap items-end gap-2">
      <div class="min-w-32 flex-1">
        <Campo rotulo="Saiu da conta">
          {(id) => <Escolha id={id} valor={conta} aoMudar={setConta} vazio="Sem conta"
            opcoes={contas.filter((c) => c.currency === moeda).map((c) => ({ valor: String(c.id), rotulo: c.name }))} />}
        </Campo>
      </div>
      <Button variante="ghost" onClick={() => setAberto(false)}>Cancelar</Button>
      <Button variante="primary" carregando={exec.estado === 'enviando'} onClick={() => void pagar()}>Pagar {money(f.amount, moeda)}</Button>
      {exec.erro && <div class="w-full"><Aviso tom="erro">{exec.erro.mensagem}</Aviso></div>}
    </div>
  );
}

function BotaoDeAcao({ rotulo, bridge, tool, args, contexto, feito, aoFeito }: {
  rotulo: string; bridge: Bridge; tool: string; args: Record<string, unknown>; contexto: string; feito: string; aoFeito: (t: string) => void;
}) {
  const exec = useAcao(bridge);
  return (
    <span class="inline-flex flex-col items-end gap-1">
      <Button variante="ghost" icone={<IconCheck size={14} />} carregando={exec.estado === 'enviando'}
        onClick={async () => { if (await exec.executar(tool, args, contexto)) aoFeito(feito); }}>
        {rotulo}
      </Button>
      {exec.erro && <span class="text-[12px] text-expense">{exec.erro.mensagem}</span>}
    </span>
  );
}

export function APagarView({ dados: inicial, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const { dados, erro, reler } = useReler(bridge, meta, inicial);
  const [aviso, setAviso] = useState<string | null>(null);
  const moeda = (dados.currency as string) ?? 'BRL';
  const contas = (dados.bills as Conta[] | undefined) ?? [];
  const faturas = (dados.card_bills as FaturaAPagar[] | undefined) ?? [];
  const parcelas = (dados.financings as Parcela[] | undefined) ?? [];
  const feito = (t: string) => { setAviso(t); void reler(); };
  const nada = !contas.length && !faturas.length && !parcelas.length;

  return (
    <div class="space-y-3">
      <Header icone={<IconCalendar size={18} />} tom={Number(dados.overdue_total ?? 0) > 0 ? 'perigo' : 'destaque'}
        titulo="A pagar" subtitulo={monthTitle(dados.month as string)}
        direita={<><p class="text-[11px] text-muted-fg">Contas do mês</p><Money valor={dados.bills_total as string} moeda={moeda} class="text-[17px] font-semibold" /></>} />
      {Number(dados.overdue_total ?? 0) > 0 && (
        <Aviso tom="erro"><IconAlert size={14} class="mr-1 inline" />{money(dados.overdue_total as string, moeda)} vencidos.</Aviso>
      )}
      {aviso && <Aviso>{aviso}</Aviso>}
      {erro && <Aviso tom="erro">{erro}</Aviso>}
      {nada && <Vazio>Nada a pagar neste mês.</Vazio>}
      {faturas.length > 0 && (
        <Section titulo="Faturas" contagem={faturas.length} aberta>
          <ul>
            {faturas.map((f) => (
              <li key={f.statement_id} class="list-none py-1">
                <div class="w-row">
                  <span class="min-w-0 flex-1">
                    <span class="block truncate text-[14px]">{f.card.name}</span>
                    <span class="block text-[12px] text-muted-fg">fatura de {monthLong(f.month)} · vence {day(f.due_date)}</span>
                  </span>
                  <span class="text-right"><Money valor={f.amount} moeda={moeda} class="font-medium" />{f.overdue && <span class="block"><Badge tom="perigo">vencida</Badge></span>}</span>
                </div>
                {meta.accounts && <div class="flex justify-end"><PagarFatura f={f} moeda={moeda} contas={meta.accounts} bridge={bridge} aoPagar={feito} /></div>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {contas.length > 0 && (
        <Section titulo="Contas" contagem={contas.length} aberta>
          <ul>
            {contas.map((c) => (
              <Linha key={c.transaction_id} titulo={c.title}
                detalhe={[`vence ${day(c.due_date)}`, c.installment && `parcela ${c.installment}`, c.space.name].filter(Boolean).join(' · ')}
                direita={
                  <span class="flex items-center gap-2">
                    <span><Money valor={c.amount} moeda={c.currency} class="font-medium" />{c.overdue && <span class="block"><Badge tom="perigo">vencida</Badge></span>}</span>
                    <BotaoDeAcao rotulo="Paga" bridge={bridge} tool="transactions_update" args={{ transaction_id: c.transaction_id, settled: true }}
                      contexto={`O usuário marcou pelo componente "${c.title}" como paga.`} feito={`"${c.title}" marcada como paga.`} aoFeito={feito} />
                  </span>
                } />
            ))}
          </ul>
        </Section>
      )}
      {parcelas.length > 0 && (
        <Section titulo="Financiamentos" contagem={parcelas.length} aberta>
          <ul>
            {parcelas.map((p) => (
              <Linha key={p.financing_id} titulo={p.title}
                detalhe={[p.next_due_date && `próxima ${day(p.next_due_date)}`, `${plural(p.remaining_installments, 'parcela restante', 'parcelas restantes')}`,
                  p.overdue_count > 0 && `${p.overdue_count} em atraso`].filter(Boolean).join(' · ')}
                direita={
                  <span class="flex items-center gap-2">
                    <Money valor={p.next_amount ?? '0'} moeda={moeda} class="font-medium" />
                    {p.next_amount && (
                      <BotaoDeAcao rotulo="Pagar" bridge={bridge} tool="financings_installment" args={{ action: 'pay', financing_id: p.financing_id }}
                        contexto={`O usuário pagou pelo componente a próxima parcela de "${p.title}".`} feito={`Parcela de "${p.title}" paga.`} aoFeito={feito} />
                    )}
                  </span>
                } />
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

// --- Metas -----------------------------------------------------------------------

interface MetaDoMes { id: number; space: Ref; category: string; scope: string; planned: string; spent: string; remaining: string; over_budget: boolean; currency: string }

function LinhaDeMeta({ m, mes, bridge, aoMudar }: { m: MetaDoMes; mes: string; bridge: Bridge; aoMudar: (t: string) => void }) {
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(m.planned);
  const exec = useAcao(bridge);
  const gasto = Number(m.spent);
  const plano = Number(m.planned);
  async function salvar() {
    const r = await exec.executar('budgets_set', {
      space_id: m.space.id, category: m.category, amount: valor, month: mes, scope: m.scope === 'personal' ? 'personal' : 'space',
    }, `O usuário mudou pelo componente a meta de ${m.category} (${monthLong(mes)}) para ${money(valor, m.currency)}.`);
    if (r) { setEditando(false); aoMudar(`Meta de ${m.category} agora é ${money(valor, m.currency)}.`); }
  }
  return (
    <li class="list-none space-y-1.5 py-2">
      <div class="flex items-baseline gap-2 text-[13px]">
        <span class="min-w-0 flex-1 truncate font-medium">{m.category}{m.scope === 'personal' && <span class="font-normal text-muted-fg"> · sua</span>}</span>
        <span class="num text-muted-fg"><span class={m.over_budget ? 'text-expense' : 'text-fg'}>{money(m.spent, m.currency)}</span> de {money(m.planned, m.currency)}</span>
        {!editando && <button type="button" class="w-icon-btn" aria-label={`Editar a meta de ${m.category}`} title="Editar meta" onClick={() => setEditando(true)}><IconPencil size={14} /></button>}
      </div>
      <Progress valor={gasto} maximo={plano} tom={m.over_budget ? 'perigo' : gasto / (plano || 1) > 0.85 ? 'destaque' : 'ok'} />
      <p class="text-[11px] text-muted-fg">
        {m.over_budget ? `Estourou ${money(-Number(m.remaining), m.currency)}` : `Sobram ${money(m.remaining, m.currency)}`} · {m.space.name}
      </p>
      {editando && (
        <div class="w-aparece flex flex-wrap items-end gap-2">
          <div class="min-w-32 flex-1"><Campo rotulo="Meta do mês">{(id) => <Dinheiro id={id} valor={valor} aoMudar={setValor} moeda={m.currency} />}</Campo></div>
          <Button variante="ghost" onClick={() => setEditando(false)}>Cancelar</Button>
          <Button variante="primary" disabled={!valor} carregando={exec.estado === 'enviando'} onClick={() => void salvar()}>Salvar</Button>
        </div>
      )}
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
    </li>
  );
}

export function MetasView({ dados: inicial, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const { dados, erro, reler } = useReler(bridge, meta, inicial);
  const [aviso, setAviso] = useState<string | null>(null);
  const metas = (dados.budgets as MetaDoMes[] | undefined) ?? [];
  const mes = dados.month as string;
  const estouradas = metas.filter((m) => m.over_budget).length;
  return (
    <div class="space-y-3">
      <Header icone={<IconChart size={18} />} tom={estouradas ? 'perigo' : 'destaque'} titulo="Metas do mês"
        subtitulo={`${monthTitle(mes)}${estouradas ? ` · ${plural(estouradas, 'estourada', 'estouradas')}` : ''}`} />
      {aviso && <Aviso>{aviso}</Aviso>}
      {erro && <Aviso tom="erro">{erro}</Aviso>}
      {metas.length === 0 ? <Vazio>Nenhuma meta neste mês.</Vazio> : (
        <ul class="divide-y divide-border">
          {metas.map((m) => <LinhaDeMeta key={m.id} m={m} mes={mes} bridge={bridge} aoMudar={(t) => { setAviso(t); void reler(); }} />)}
        </ul>
      )}
    </div>
  );
}
