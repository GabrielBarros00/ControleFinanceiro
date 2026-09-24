/** @jsxImportSource preact */
/**
 * Fatura do cartão: troca de mês, compras paginadas (que abrem o detalhe),
 * pagamentos, Pagar fatura e Estornar pagamentos (`statements_reopen`).
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, monthLong, plural } from '../format';
import type { Meta, Ref, Resumo } from '../tipos';
import { erroDe, novaChave, useAcao } from '../ui/acao';
import { Aviso, Badge, Barras, Button, Header, Linha, Money, Progress, Section, Stat, type Tom } from '../ui/base';
import { Campo, Dinheiro, Escolha } from '../ui/form';
import { IconCard, IconCheck, IconExternal, IconUndo } from '../ui/icons';
import { CarregarMais, LinhaDeLancamento } from '../ui/lista';
import { usePaginas } from '../ui/paginas';

const SITUACAO: Record<string, [string, Tom]> = {
  open: ['Aberta', 'neutro'], closed: ['Fechada', 'aviso'], paid: ['Paga', 'ok'], overdue: ['Vencida', 'perigo'], not_created: ['Sem compras', 'neutro'],
};

interface Pagamento { id: number; amount: string; date: string; account?: Ref | null; note?: string | null }

function Compras({ dados, cartao, bridge, meta }: { dados: Record<string, unknown>; cartao?: number; bridge: Bridge; meta: Meta }) {
  const consulta = cartao ? { tool: 'statements_get', args: { card_id: cartao, month: dados.month } } : undefined;
  const pagina = usePaginas<Resumo>(bridge, consulta, (dados.purchases as Resumo[]) ?? [], dados.next_cursor as string | null, 'purchases');
  if (!pagina.itens.length) return <p class="text-[13px] text-muted-fg">Nenhuma compra nesta fatura.</p>;
  return (
    <>
      <ul>{pagina.itens.map((p) => <LinhaDeLancamento key={p.id} r={p} bridge={bridge} forms={meta.forms} semCartao />)}</ul>
      <CarregarMais pagina={pagina} total={Number(dados.purchases_count ?? 0)} mostrados={pagina.itens.length} />
    </>
  );
}

export function FaturaView({ dados: inicial, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const [dados, setDados] = useState(inicial);
  const [pagando, setPagando] = useState(false);
  const [estornando, setEstornando] = useState(false);
  const [conta, setConta] = useState(meta.accounts?.[0] ? String(meta.accounts[0].id) : '');
  const [valor, setValor] = useState(String(inicial.balance ?? ''));
  const [aviso, setAviso] = useState<string | null>(null);
  const exec = useAcao(bridge);
  const cartao = (dados.card as Ref | undefined)?.id ?? meta.card_id;
  const moeda = (dados.currency as string) ?? 'BRL';
  const meses = (dados.available_months as string[] | undefined) ?? [];
  const pagamentos = (dados.payments as Pagamento[] | undefined) ?? [];
  const saldo = Number(dados.balance ?? 0);
  const [rotulo, tom] = dados.overdue === true ? SITUACAO.overdue : SITUACAO[String(dados.status)] ?? [String(dados.status), 'neutro' as Tom];
  const categorias = (dados.by_category as Array<{ category: string; amount: string }> | undefined) ?? [];

  async function carregar(mes: string) {
    const r = await bridge.callTool('statements_get', { card_id: cartao, month: mes }).catch(() => null);
    if (r && !r.isError) {
      const d = (r.structuredContent ?? {}) as Record<string, unknown>;
      setDados(d);
      setValor(String(d.balance ?? ''));
    } else setAviso(r ? erroDe(r).mensagem : 'Não foi possível abrir a fatura.');
  }

  async function pagar() {
    const r = await exec.executar('statements_pay', {
      idempotency_key: novaChave(), card_id: cartao, month: dados.month, amount: valor, ...(conta ? { account_id: Number(conta) } : {}),
    }, `O usuário pagou pelo componente ${valor} da fatura de ${monthLong(dados.month as string)} do cartão ${(dados.card as Ref)?.name}.`);
    if (!r) return;
    setPagando(false);
    setAviso('Pagamento registrado.');
    await carregar(dados.month as string);
  }

  async function estornar() {
    const r = await exec.executar('statements_reopen', { card_id: cartao, month: dados.month },
      `O usuário estornou pelo componente os pagamentos da fatura de ${monthLong(dados.month as string)}.`);
    if (!r) return;
    setEstornando(false);
    setAviso('Pagamentos estornados: a fatura voltou a ficar em aberto.');
    await carregar(dados.month as string);
  }

  return (
    <div class="space-y-3">
      <Header icone={<IconCard size={18} />} tom="destaque"
        titulo={`Fatura de ${monthLong(dados.month as string)}`}
        subtitulo={`${(dados.card as Ref | undefined)?.name ?? ''} · fecha ${day(dados.closing_date as string)} · vence ${day(dados.due_date as string)}`}
        direita={<Badge tom={tom}>{rotulo}</Badge>} />

      {meses.length > 1 && cartao && (
        <Escolha valor={String(dados.month)} aoMudar={(m) => void carregar(m)}
          opcoes={meses.map((m) => ({ valor: m, rotulo: monthLong(m) }))} />
      )}

      <div class="grid grid-cols-3 gap-2">
        <Stat rotulo="Total"><Money valor={dados.total as string} moeda={moeda} /></Stat>
        <Stat rotulo="Pago"><Money valor={dados.paid as string} moeda={moeda} /></Stat>
        <Stat rotulo={saldo > 0 ? 'Falta pagar' : 'Saldo'}><Money valor={dados.balance as string} moeda={moeda} /></Stat>
      </div>
      {Number(dados.total ?? 0) > 0 && <Progress valor={Number(dados.paid ?? 0)} maximo={Number(dados.total)} tom={saldo > 0 ? 'destaque' : 'ok'} />}

      {aviso && <Aviso>{aviso}</Aviso>}
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}

      {pagando ? (
        <div class="w-aparece grid grid-cols-1 gap-3 rounded-lg border border-border p-3 sm:grid-cols-2">
          <Campo rotulo="Valor">{(id) => <Dinheiro id={id} valor={valor} aoMudar={setValor} moeda={moeda} />}</Campo>
          <Campo rotulo="Saiu da conta">
            {(id) => <Escolha id={id} valor={conta} aoMudar={setConta} vazio="Sem conta"
              opcoes={(meta.accounts ?? []).filter((a) => a.currency === moeda).map((a) => ({ valor: String(a.id), rotulo: a.name }))} />}
          </Campo>
          <div class="flex justify-end gap-2 sm:col-span-2">
            <Button variante="ghost" onClick={() => setPagando(false)}>Cancelar</Button>
            <Button variante="primary" icone={<IconCheck size={14} />} carregando={exec.estado === 'enviando'} disabled={!valor} onClick={() => void pagar()}>Pagar</Button>
          </div>
        </div>
      ) : (
        <div class="flex flex-wrap gap-2">
          {meta.can_pay && saldo > 0 && dados.exists !== false && (
            <Button variante="primary" icone={<IconCheck size={14} />} onClick={() => setPagando(true)}>Pagar fatura</Button>
          )}
          {meta.can_pay && pagamentos.length > 0 && !estornando && (
            <Button variante="ghost" icone={<IconUndo size={14} />} onClick={() => setEstornando(true)}>Estornar pagamentos</Button>
          )}
          {estornando && (
            <span class="flex flex-wrap items-center gap-2">
              <span class="text-[13px] text-muted-fg">Estornar {plural(pagamentos.length, 'pagamento', 'pagamentos')}?</span>
              <Button variante="danger" carregando={exec.estado === 'enviando'} onClick={() => void estornar()}>Estornar</Button>
              <Button variante="ghost" onClick={() => setEstornando(false)}>Não</Button>
            </span>
          )}
          <span class="flex-1" />
          {(dados.app_url ?? meta.app_url) && (
            <Button variante="ghost" icone={<IconExternal size={14} />} onClick={() => bridge.openLink(String(dados.app_url ?? meta.app_url))}>Abrir no app</Button>
          )}
        </div>
      )}

      {categorias.length > 0 && (
        <Section titulo="Por categoria" contagem={categorias.length}>
          <Barras total={dados.total as string} fatias={categorias.map((c) => ({ chave: c.category, rotulo: c.category, valor: c.amount, moeda }))} />
        </Section>
      )}
      <Section titulo="Compras" contagem={Number(dados.purchases_count ?? 0)} aberta>
        <Compras key={String(dados.month)} dados={dados} cartao={cartao} bridge={bridge} meta={meta} />
      </Section>
      {pagamentos.length > 0 && (
        <Section titulo="Pagamentos" contagem={pagamentos.length}>
          <ul>
            {pagamentos.map((p) => (
              <Linha key={p.id} titulo={p.account?.name ?? 'Pago fora do app'} detalhe={[day(p.date), p.note].filter(Boolean).join(' · ')}
                direita={<Money valor={p.amount} moeda={moeda} tom="entrada" />} />
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
