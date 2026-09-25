/** @jsxImportSource preact */
/**
 * As peças do componente: dinheiro, selo, avatar, botões, cabeçalho, seção
 * recolhível, linhas, estados vazios/carregando e aviso de ação.
 *
 * Tudo lê as variáveis do host (via `widget.css`), então o componente fica com a
 * cara do app de chat — com o visual próprio como reserva.
 */
import type { ComponentChildren, JSX } from 'preact';
import { useState } from 'preact/hooks';
import { iniciais, matiz, money, percent } from '../format';
import { IconChevron } from './icons';

export type Tom = 'neutro' | 'ok' | 'aviso' | 'perigo' | 'destaque';

const TONS: Record<Tom, string> = {
  neutro: 'bg-muted text-muted-fg',
  ok: 'bg-ok-bg text-income',
  aviso: 'bg-warn-bg text-warn',
  perigo: 'bg-danger-bg text-expense',
  destaque: 'bg-accent-bg text-accent',
};

export function Badge({ children, tom = 'neutro', icone }: { children: ComponentChildren; tom?: Tom; icone?: JSX.Element }) {
  return (
    <span class={`inline-flex max-w-full items-center gap-1 truncate rounded-full px-2 py-0.5 text-[11px] font-medium ${TONS[tom]}`}>
      {icone}
      {children}
    </span>
  );
}

/** Dinheiro: números tabulares, sinal e cor só quando o contexto pede. */
export function Money({ valor, moeda = 'BRL', tom, class: cls = '' }: {
  valor: string | number | null | undefined; moeda?: string; tom?: 'entrada' | 'saida' | 'auto'; class?: string;
}) {
  const n = Number(valor);
  const cor = tom === 'entrada' ? 'text-income' : tom === 'saida' ? 'text-expense'
    : tom === 'auto' && Number.isFinite(n) ? (n > 0 ? 'text-income' : n < 0 ? 'text-expense' : '') : '';
  return <span class={`num whitespace-nowrap ${cor} ${cls}`}>{money(valor, moeda)}</span>;
}

export function Avatar({ nome, tamanho = 22 }: { nome: string; tamanho?: number }) {
  const h = matiz(nome);
  return (
    <span
      aria-hidden="true"
      class="inline-flex shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
      style={{ width: tamanho, height: tamanho, background: `hsl(${h} 70% 90%)`, color: `hsl(${h} 45% 30%)` }}
    >
      {iniciais(nome)}
    </span>
  );
}

type Variante = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({ children, variante = 'secondary', icone, carregando, disabled, class: cls = '', ...resto }: {
  children?: ComponentChildren; variante?: Variante; icone?: JSX.Element; carregando?: boolean; disabled?: boolean; class?: string;
} & Omit<JSX.HTMLAttributes<HTMLButtonElement>, 'icon'>) {
  return (
    <button type="button" {...resto} disabled={carregando || disabled} class={`w-btn w-btn-${variante} ${cls}`}>
      {carregando ? <span class="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" /> : icone}
      {children}
    </button>
  );
}

export function IconButton({ rotulo, children, ...resto }: { rotulo: string; children: ComponentChildren } & JSX.HTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" aria-label={rotulo} title={rotulo} {...resto} class="w-icon-btn">
      {children}
    </button>
  );
}

/** Cabeçalho de cartão: ícone num selo colorido, título, subtítulo e o destaque à direita. */
export function Header({ icone, tom = 'neutro', titulo, subtitulo, direita, riscado }: {
  icone?: JSX.Element; tom?: Tom; titulo: ComponentChildren; subtitulo?: ComponentChildren; direita?: ComponentChildren; riscado?: boolean;
}) {
  return (
    <div class="flex items-start gap-3">
      {icone && <span class={`mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-lg ${TONS[tom]}`}>{icone}</span>}
      <div class="min-w-0 flex-1">
        <p class={`truncate text-[15px] font-semibold leading-snug ${riscado ? 'line-through opacity-60' : ''}`}>{titulo}</p>
        {subtitulo && <p class="truncate text-[12px] text-muted-fg">{subtitulo}</p>}
      </div>
      {direita && <div class="shrink-0 text-right">{direita}</div>}
    </div>
  );
}

/** Seção recolhível: o detalhe fica à mão sem ocupar a conversa. */
export function Section({ titulo, contagem, aberta = false, direita, children }: {
  titulo: string; contagem?: number | string; aberta?: boolean; direita?: ComponentChildren; children: ComponentChildren;
}) {
  const [aberto, setAberto] = useState(aberta);
  return (
    <div class="border-t border-border pt-1">
      <button
        type="button" aria-expanded={aberto} onClick={() => setAberto(!aberto)}
        class="flex w-full items-center gap-1.5 rounded-md py-1.5 text-left text-[12px] font-semibold uppercase tracking-wide text-muted-fg hover:text-fg"
      >
        <span class={`transition-transform ${aberto ? 'rotate-90' : ''}`}><IconChevron size={14} /></span>
        <span class="flex-1">{titulo}{contagem !== undefined && <span class="ml-1 font-normal normal-case">· {contagem}</span>}</span>
        {direita}
      </button>
      {aberto && <div class="w-aparece pb-2">{children}</div>}
    </div>
  );
}

export function Stat({ rotulo, children, tom }: { rotulo: string; children: ComponentChildren; tom?: 'entrada' | 'saida' }) {
  return (
    <div class="min-w-0 rounded-lg bg-subtle px-3 py-2">
      <p class="truncate text-[11px] text-muted-fg">{rotulo}</p>
      <p class={`num truncate text-[15px] font-semibold ${tom === 'entrada' ? 'text-income' : tom === 'saida' ? 'text-expense' : ''}`}>{children}</p>
    </div>
  );
}

/** Barra de progresso (meta × gasto, parcelas pagas). */
export function Progress({ valor, maximo, tom = 'destaque' }: { valor: number; maximo: number; tom?: 'destaque' | 'perigo' | 'ok' }) {
  const p = maximo > 0 ? Math.max(0, Math.min(100, (valor / maximo) * 100)) : 0;
  const cor = tom === 'perigo' ? 'bg-expense' : tom === 'ok' ? 'bg-income' : 'bg-accent';
  return (
    <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(p)} aria-valuemin={0} aria-valuemax={100}>
      <div class={`h-full rounded-full ${cor}`} style={{ width: `${p}%` }} />
    </div>
  );
}

export interface Fatia { chave: string; rotulo: string; valor: string; moeda: string; extra?: string; onClick?: () => void }

/** Participação de cada fatia no total, com a porcentagem escrita. */
export function Barras({ fatias, total }: { fatias: Fatia[]; total: string | number }) {
  return (
    <ul class="space-y-2">
      {fatias.map((f) => {
        const p = percent(f.valor, total);
        const corpo = (
          <>
            <div class="flex items-baseline justify-between gap-3 text-[13px]">
              <span class="min-w-0 truncate">{f.rotulo}</span>
              <span class="num shrink-0 text-muted-fg">{f.extra ?? `${p}%`} · <span class="text-fg">{money(f.valor, f.moeda)}</span></span>
            </div>
            <div class="mt-1 h-1.5 rounded-full bg-muted" aria-hidden="true">
              <div class="h-1.5 rounded-full bg-accent" style={{ width: `${p}%` }} />
            </div>
          </>
        );
        return (
          <li key={f.chave}>
            {f.onClick ? <button type="button" onClick={f.onClick} class="block w-full rounded-md text-left hover:opacity-80">{corpo}</button> : corpo}
          </li>
        );
      })}
    </ul>
  );
}

/** Colunas por mês (série), sem biblioteca de gráfico. A altura vai em px: em
 *  porcentagem, dentro de um item flex sem altura resolvida, a coluna sumia. */
const ALTURA_DA_COLUNA = 88;
export function Colunas({ pontos, moeda }: { pontos: Array<{ rotulo: string; valor: number; tom?: 'entrada' | 'saida' }>; moeda: string }) {
  const maximo = Math.max(1, ...pontos.map((p) => Math.abs(p.valor)));
  return (
    <div class="flex items-end gap-1.5" role="img" aria-label={`Série: ${pontos.map((p) => `${p.rotulo} ${money(p.valor, moeda)}`).join(', ')}`}>
      {pontos.map((p) => (
        <div key={p.rotulo} class="flex min-w-0 flex-1 flex-col items-center justify-end gap-1" title={`${p.rotulo}: ${money(p.valor, moeda)}`}>
          <div
            class={`w-full rounded-t-sm ${p.tom === 'entrada' ? 'bg-income' : p.tom === 'saida' ? 'bg-expense' : 'bg-accent'} opacity-80`}
            style={{ height: `${Math.max(3, Math.round((Math.abs(p.valor) / maximo) * ALTURA_DA_COLUNA))}px` }}
          />
          <span class="w-full truncate text-center text-[10px] text-muted-fg">{p.rotulo}</span>
        </div>
      ))}
    </div>
  );
}

export function Esqueleto({ linhas = 3 }: { linhas?: number }) {
  return (
    <div class="animate-pulse space-y-2" aria-busy="true" aria-label="Carregando">
      <div class="flex items-center gap-3">
        <div class="size-9 rounded-lg bg-muted" />
        <div class="flex-1 space-y-1.5">
          <div class="h-3.5 w-1/2 rounded bg-muted" />
          <div class="h-3 w-1/3 rounded bg-muted" />
        </div>
      </div>
      {Array.from({ length: linhas }, (_, i) => <div key={i} class="h-7 w-full rounded bg-muted" />)}
    </div>
  );
}

export function Vazio({ children }: { children: ComponentChildren }) {
  return <p class="rounded-lg bg-subtle px-3 py-4 text-center text-[13px] text-muted-fg">{children}</p>;
}

/** Resultado de uma ação, anunciado por leitor de tela (`role=status`). */
export function Aviso({ tom = 'ok', children }: { tom?: 'ok' | 'erro' | 'info'; children: ComponentChildren }) {
  const cor = tom === 'erro' ? 'bg-danger-bg text-expense' : tom === 'info' ? 'bg-accent-bg text-accent' : 'bg-ok-bg text-income';
  return <p role="status" class={`w-aparece rounded-md px-3 py-2 text-[13px] ${cor}`}>{children}</p>;
}

/** Linha de lista: data/ícone à esquerda, título e detalhe, valor à direita. */
export function Linha({ esquerda, titulo, detalhe, direita, onClick, expandida, children, riscada }: {
  esquerda?: ComponentChildren; titulo: ComponentChildren; detalhe?: ComponentChildren; direita?: ComponentChildren;
  onClick?: () => void; expandida?: boolean; children?: ComponentChildren; riscada?: boolean;
}) {
  const conteudo = (
    <>
      {esquerda}
      <span class="min-w-0 flex-1">
        <span class={`block truncate text-[14px] ${riscada ? 'line-through opacity-60' : ''}`}>{titulo}</span>
        {detalhe && <span class="block truncate text-[12px] text-muted-fg">{detalhe}</span>}
      </span>
      {direita && <span class="shrink-0 text-right">{direita}</span>}
    </>
  );
  return (
    <li class="list-none">
      {onClick
        ? <button type="button" aria-expanded={expandida} onClick={onClick} class="w-row w-row-click">{conteudo}</button>
        : <div class="w-row">{conteudo}</div>}
      {expandida && children && <div class="w-aparece mb-2 ml-2 border-l-2 border-border pl-3">{children}</div>}
    </li>
  );
}

/** Chip de data (dia/mês) para listas. */
export function Dia({ data }: { data?: string | null }) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(data ?? '');
  const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  return (
    <span class="flex w-9 shrink-0 flex-col items-center rounded-md bg-subtle py-0.5 leading-tight">
      <span class="num text-[13px] font-semibold">{m ? m[3] : '—'}</span>
      <span class="text-[10px] uppercase text-muted-fg">{m ? MES[Number(m[2]) - 1] : ''}</span>
    </span>
  );
}
