/** @jsxImportSource preact */
/**
 * O componente MCP Apps (ADR 0035 §11): escolhe a vista pelo `_meta.view` do
 * resultado e oferece tela cheia quando o host deixa.
 *
 * Enquanto a tool roda, a entrada dela (`ui/notifications/tool-input`) já mostra o
 * que está sendo registrado; o resultado substitui a prévia.
 */
import type { ComponentChildren, FunctionComponent } from 'preact';
import { useEffect, useErrorBoundary, useState } from 'preact/hooks';
import type { Ambiente, Bridge, Tema, ToolResultLike } from './bridge';
import { money } from './format';
import type { Meta } from './tipos';
import { Aviso, Esqueleto } from './ui/base';
import { IconExpand, IconShrink } from './ui/icons';
import { ContaView } from './views/Conta';
import { FaturaView } from './views/Fatura';
import { LancamentoView } from './views/Lancamento';
import { ListaView } from './views/Lista';
import { PreviaDeMassa, ResultadoDeMassa } from './views/Massa';
import { APagarView, DividasView, MetasView } from './views/Obrigacoes';
import { FinanciamentoView, RecorrenciasView, RendaView } from './views/Planejamento';
import { HistoricoView, ImportacoesView, ReciboView } from './views/Recibo';
import { AnaliseView, ResumoView } from './views/Resumo';

type Vista = FunctionComponent<{ dados: Record<string, unknown>; meta: Meta; bridge: Bridge }>;

const VISTAS: Record<string, Vista> = {
  transaction: LancamentoView,
  transactions: ListaView,
  statement: FaturaView,
  summary: ResumoView,
  breakdown: AnaliseView,
  account: ContaView,
  cash: ContaView,
  debts: DividasView,
  payables: APagarView,
  budgets: MetasView,
  recurring: RecorrenciasView,
  income: RendaView,
  financing: FinanciamentoView,
  history: HistoricoView,
  imports: ImportacoesView,
  bulk_preview: PreviaDeMassa,
  bulk_result: ResultadoDeMassa,
  receipt: ReciboView,
};

/** Vistas que só confirmam uma escrita: não pedem tela cheia. */
const RECIBOS = new Set(['receipt', 'bulk_result']);

/** Host sem `_meta` (ou versão antiga do servidor): adivinha pela forma dos dados. */
function vistaDe(dados: Record<string, unknown>, meta: Meta): string {
  if (meta.tool === 'financings_installment') return 'financing';
  if (meta.view) return meta.view;
  if (dados.transaction) return 'transaction';
  if (dados.confirmation_token !== undefined) return 'bulk_preview';
  if (dados.purchases) return 'statement';
  if (dados.my_categories) return 'summary';
  return '';
}

/** O que a tool vai registrar, antes do resultado: título e valor, se houver. */
function Previa({ entrada }: { entrada: Record<string, unknown> }) {
  const titulo = typeof entrada.title === 'string' ? entrada.title : null;
  const valor = typeof entrada.amount === 'string' ? entrada.amount : null;
  if (!titulo && !valor) return <Esqueleto />;
  return (
    <div class="animate-pulse space-y-2" aria-busy="true">
      <div class="flex items-start gap-3">
        <div class="size-9 rounded-lg bg-muted" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-[15px] font-semibold">{titulo ?? 'Registrando…'}</p>
          <p class="text-[12px] text-muted-fg">Registrando…</p>
        </div>
        {valor && <p class="num text-[17px] font-semibold">{money(valor, typeof entrada.currency === 'string' ? entrada.currency : 'BRL')}</p>}
      </div>
      <div class="h-7 w-full rounded bg-muted" />
    </div>
  );
}

/**
 * Um campo inesperado não pode apagar a tela inteira: o erro de desenho vira um
 * aviso, e os dados continuam na resposta do assistente.
 */
function Protegida({ children }: { children: ComponentChildren }) {
  const [erro] = useErrorBoundary();
  if (erro) return <Aviso tom="info">Não deu para desenhar esta tela aqui; os dados estão na resposta do assistente.</Aviso>;
  return <>{children}</>;
}

export function Widget({ bridge }: { bridge: Bridge }) {
  const [resultado, setResultado] = useState<ToolResultLike | null>(null);
  const [entrada, setEntrada] = useState<Record<string, unknown> | null>(null);
  const [tema, setTema] = useState<Tema>('light');
  const [ambiente, setAmbiente] = useState<Ambiente>({ modo: 'inline', modos: ['inline'] });

  useEffect(() => {
    bridge.onResult(setResultado);
    bridge.onTheme(setTema);
    bridge.onToolInput?.(setEntrada);
    bridge.onAmbiente?.(setAmbiente);
  }, [bridge]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', tema === 'dark');
  }, [tema]);

  if (!resultado) return entrada ? <Previa entrada={entrada} /> : <Esqueleto />;
  if (resultado.isError) return null; // o texto do erro já está na conversa

  const bruto = (resultado.structuredContent ?? {}) as Record<string, unknown>;
  // `view_show` embrulha a saída da tool de dados em `data`.
  const dados = (bruto.source_tool && bruto.data ? bruto.data : bruto) as Record<string, unknown>;
  const meta = (resultado._meta ?? {}) as Meta;
  const vista = vistaDe(dados, meta);
  const Vista = VISTAS[vista];
  if (!Vista) return null;

  const cheia = ambiente.modo === 'fullscreen';
  // Resultado de uma escrita simples (recibo, renda, recorrência) é curto: tela
  // cheia só onde há o que explorar (listas, fatura, o lançamento com o editor).
  const escritaCurta = RECIBOS.has(vista) || (Boolean(meta.mode) && meta.mode !== 'read' && vista !== 'transaction');
  const podeCrescer = Boolean(bridge.requestDisplayMode) && ambiente.modos.includes('fullscreen') && !escritaCurta;
  const limite = !cheia && ambiente.alturaMaxima ? { maxHeight: ambiente.alturaMaxima, overflowY: 'auto' as const } : undefined;

  return (
    <div class={`text-fg ${cheia ? 'mx-auto max-w-3xl p-4' : ''}`} style={limite}>
      <Protegida key={`${vista}-${meta.mode ?? ''}`}>
        <Vista dados={dados} meta={meta} bridge={bridge} />
      </Protegida>
      {podeCrescer && (
        <div class="mt-2 flex justify-end">
          <button type="button" class="w-btn w-btn-ghost text-[12px]"
            onClick={() => void bridge.requestDisplayMode?.(cheia ? 'inline' : 'fullscreen')}>
            {cheia ? <IconShrink size={14} /> : <IconExpand size={14} />}
            {cheia ? 'Voltar à conversa' : 'Tela cheia'}
          </button>
        </div>
      )}
    </div>
  );
}
