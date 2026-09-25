/** @jsxImportSource preact */
/**
 * Extrato de uma conta (saldo linha a linha) e caixa do mês, com troca de mês,
 * paginação e "Ajustar saldo" (a conta passa a bater com o banco).
 */
import { useState } from 'preact/hooks';
import type { Bridge } from '../bridge';
import { day, money, monthTitle } from '../format';
import type { Meta, Ref } from '../tipos';
import { erroDe, novaChave, useAcao } from '../ui/acao';
import { Aviso, Button, Header, IconButton, Linha, Money, Stat, Vazio } from '../ui/base';
import { Campo, Dinheiro } from '../ui/form';
import { IconBank, IconChevron, IconExternal, IconPencil, IconWallet } from '../ui/icons';
import { CarregarMais } from '../ui/lista';
import { usePaginas } from '../ui/paginas';

interface Entrada {
  date: string; source: string; title: string; amount: string; currency: string; running_balance?: string | null;
  converted_amount?: string | null; space?: Ref | null; counterparty?: string | null;
}

const ORIGEM: Record<string, string> = {
  transaction: 'Despesa', income: 'Renda', transfer_in: 'Transferência recebida', transfer_out: 'Transferência enviada',
  statement_payment: 'Pagamento de fatura', settlement_received: 'Acerto recebido', settlement_sent: 'Acerto pago',
  adjustment: 'Ajuste de saldo', financing_installment: 'Parcela de financiamento', opening_balance: 'Saldo inicial',
};

function mesVizinho(mes: string, delta: number): string {
  const [a, m] = mes.split('-').map(Number);
  const d = new Date(Date.UTC(a, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function Entradas({ dados, consulta, bridge }: { dados: Record<string, unknown>; consulta: { tool: string; args: Record<string, unknown> }; bridge: Bridge }) {
  const pagina = usePaginas<Entrada>(bridge, consulta, (dados.entries as Entrada[]) ?? [], dados.next_cursor as string | null, 'entries');
  if (!pagina.itens.length) return <Vazio>Nenhuma movimentação no mês.</Vazio>;
  return (
    <>
      <ul>
        {pagina.itens.map((e, i) => {
          const n = Number(e.amount);
          return (
            <Linha key={`${e.date}-${i}`} titulo={e.title}
              detalhe={[day(e.date), ORIGEM[e.source] ?? e.source, e.counterparty, e.space?.name].filter(Boolean).join(' · ')}
              direita={
                <>
                  <Money valor={e.amount} moeda={e.currency} tom={n >= 0 ? 'entrada' : 'saida'} class="text-[14px] font-medium" />
                  {e.running_balance && <span class="num block text-[11px] text-muted-fg">saldo {money(e.running_balance, e.currency)}</span>}
                </>
              } />
          );
        })}
      </ul>
      <CarregarMais pagina={pagina} total={Number(dados.total_count ?? 0)} mostrados={pagina.itens.length} />
    </>
  );
}

export function ContaView({ dados: inicial, meta, bridge }: { dados: Record<string, unknown>; meta: Meta; bridge: Bridge }) {
  const [dados, setDados] = useState(inicial);
  const [ajustando, setAjustando] = useState(false);
  const [real, setReal] = useState('');
  const [aviso, setAviso] = useState<string | null>(null);
  const exec = useAcao(bridge);
  const conta = dados.account as Ref | null | undefined;
  const moeda = (dados.currency as string) ?? 'BRL';
  const mes = dados.month as string | null;
  const args: Record<string, unknown> = { ...(meta.query?.args ?? {}), ...(conta ? { account_id: conta.id } : {}), ...(mes ? { month: mes } : {}) };
  delete args.account;
  const podeAjustar = Boolean(conta && meta.accounts?.some((a) => a.id === conta.id));

  async function carregar(novoMes: string | null) {
    const resto = { ...args };
    delete resto.month;
    const r = await bridge.callTool('accounts_statement', { ...resto, ...(novoMes ? { month: novoMes } : {}) }).catch(() => null);
    if (r && !r.isError) setDados((r.structuredContent ?? {}) as Record<string, unknown>);
    else setAviso(r ? erroDe(r).mensagem : 'Não foi possível abrir o mês.');
  }

  async function ajustar() {
    if (!conta) return;
    const r = await exec.executar('accounts_adjust_balance', { idempotency_key: novaChave(), account_id: conta.id, real_balance: real },
      `O usuário ajustou pelo componente o saldo da conta ${conta.name} para ${money(real, moeda)}.`);
    if (!r) return;
    setAjustando(false);
    setAviso(`Saldo ajustado: ${money(r.previous_balance as string, moeda)} → ${money(r.new_balance as string, moeda)}.`);
    await carregar(mes);
  }

  const rotuloDoMes = mes ? monthTitle(mes) : 'Extrato completo';

  return (
    <div class="space-y-3">
      <Header icone={conta ? <IconBank size={18} /> : <IconWallet size={18} />} tom="destaque"
        titulo={conta ? conta.name : 'Caixa do mês'}
        subtitulo={rotuloDoMes}
        direita={conta ? <><p class="text-[11px] text-muted-fg">Saldo</p><Money valor={dados.balance as string} moeda={moeda} class="text-[17px] font-semibold" /></> : undefined} />
      {mes && (
        <div class="flex items-center gap-1">
          <IconButton rotulo="Mês anterior" onClick={() => void carregar(mesVizinho(mes, -1))}><IconChevron size={16} class="rotate-180" /></IconButton>
          <span class="flex-1 text-center text-[13px] font-medium">{rotuloDoMes}</span>
          <IconButton rotulo="Próximo mês" onClick={() => void carregar(mesVizinho(mes, 1))}><IconChevron size={16} /></IconButton>
        </div>
      )}
      {/* No extrato completo (sem mês) o servidor não soma entradas e saídas. */}
      {dados.cash_in != null && (
        <div class="grid grid-cols-3 gap-2">
          <Stat rotulo="Entrou" tom="entrada">{money(dados.cash_in as string, moeda)}</Stat>
          <Stat rotulo="Saiu" tom="saida">{money(dados.cash_out as string, moeda)}</Stat>
          <Stat rotulo="Líquido">{money(dados.net_cash as string, moeda)}</Stat>
        </div>
      )}
      {aviso && <Aviso>{aviso}</Aviso>}
      {exec.erro && <Aviso tom="erro">{exec.erro.mensagem}</Aviso>}
      {ajustando ? (
        <div class="w-aparece space-y-3 rounded-lg border border-border p-3">
          <Campo rotulo="Saldo que o banco mostra hoje" dica="A diferença vira um ajuste de saldo; nenhum lançamento é alterado.">
            {(id) => <Dinheiro id={id} valor={real} aoMudar={setReal} moeda={moeda} />}
          </Campo>
          <div class="flex justify-end gap-2">
            <Button variante="ghost" onClick={() => setAjustando(false)}>Cancelar</Button>
            <Button variante="primary" disabled={!real} carregando={exec.estado === 'enviando'} onClick={() => void ajustar()}>Ajustar</Button>
          </div>
        </div>
      ) : (
        <div class="flex flex-wrap gap-2">
          {podeAjustar && <Button icone={<IconPencil size={14} />} onClick={() => setAjustando(true)}>Ajustar saldo</Button>}
          <span class="flex-1" />
          {typeof dados.app_url === 'string' && dados.app_url && (
            <Button variante="ghost" icone={<IconExternal size={14} />} onClick={() => bridge.openLink(dados.app_url as string)}>Abrir no app</Button>
          )}
        </div>
      )}
      <Entradas key={mes ?? 'tudo'} dados={dados} bridge={bridge} consulta={{ tool: 'accounts_statement', args }} />
    </div>
  );
}
