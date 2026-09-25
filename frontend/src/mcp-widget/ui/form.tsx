/** @jsxImportSource preact */
/**
 * Campos do editor do componente.
 *
 * Dinheiro segue o `MoneyInput` do app: `inputMode="numeric"` e máscara de
 * centavos (os dígitos entram pela direita). Nunca `type="number"` nem
 * `inputMode="decimal"`: no celular isso abre teclado sem vírgula, ou com a
 * vírgula que a máscara comeria. Todo campo tem 16 px, senão o iPhone dá zoom.
 */
import type { ComponentChildren } from 'preact';
import { useId } from 'preact/hooks';

export function Campo({ rotulo, children, dica }: { rotulo: string; children: (id: string) => ComponentChildren; dica?: string }) {
  const id = useId();
  return (
    <div class="min-w-0">
      <label class="w-label" for={id}>{rotulo}</label>
      {children(id)}
      {dica && <p class="mt-0.5 text-[11px] text-muted-fg">{dica}</p>}
    </div>
  );
}

export function Texto({ id, valor, aoMudar, placeholder, max = 200 }: {
  id?: string; valor: string; aoMudar: (v: string) => void; placeholder?: string; max?: number;
}) {
  return (
    <input id={id} class="w-input text-[16px] sm:text-[14px]" value={valor} maxLength={max} placeholder={placeholder}
      onInput={(e) => aoMudar((e.target as HTMLInputElement).value)} />
  );
}

/** "8990" → "89,90" → devolve o decimal "89.90". */
function mascara(digitos: string): string {
  const d = digitos.replace(/\D/g, '').replace(/^0+(?=\d)/, '');
  if (!d) return '';
  const centavos = d.padStart(3, '0');
  const inteiro = centavos.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return `${inteiro},${centavos.slice(-2)}`;
}

export function Dinheiro({ id, valor, aoMudar, moeda = 'BRL' }: {
  id?: string; valor: string; aoMudar: (decimal: string) => void; moeda?: string;
}) {
  // `valor` é o decimal do servidor ("89.90"); a tela mostra "89,90".
  const visivel = valor ? mascara(Number(valor).toFixed(2).replace('.', '')) : '';
  return (
    <div class="relative">
      <span class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[13px] text-muted-fg">{moeda === 'BRL' ? 'R$' : moeda}</span>
      <input
        id={id} inputMode="numeric" autoComplete="off" class="w-input num pl-9 text-right text-[16px] sm:text-[14px]" value={visivel}
        onInput={(e) => {
          const alvo = e.target as HTMLInputElement;
          const txt = mascara(alvo.value);
          alvo.value = txt;
          aoMudar(txt ? (Number(txt.replace(/\./g, '').replace(',', '.'))).toFixed(2) : '');
        }}
      />
    </div>
  );
}

export function Data({ id, valor, aoMudar }: { id?: string; valor: string; aoMudar: (v: string) => void }) {
  return <input id={id} type="date" class="w-input text-[16px] sm:text-[14px]" value={valor} onInput={(e) => aoMudar((e.target as HTMLInputElement).value)} />;
}

/**
 * Seleção NATIVA: dentro do iframe do app de chat, um popover próprio escaparia do
 * foco e do recorte do host; o `<select>` do sistema funciona em todo lugar.
 */
export function Escolha({ id, valor, aoMudar, opcoes, vazio }: {
  id?: string; valor: string; aoMudar: (v: string) => void; opcoes: Array<{ valor: string; rotulo: string }>; vazio?: string;
}) {
  return (
    <select id={id} class="w-input text-[16px] sm:text-[14px]" value={valor} onChange={(e) => aoMudar((e.target as HTMLSelectElement).value)}>
      {vazio !== undefined && <option value="">{vazio}</option>}
      {opcoes.map((o) => <option key={o.valor} value={o.valor}>{o.rotulo}</option>)}
    </select>
  );
}

/** Tags como chips que ligam e desligam. */
export function Chips({ opcoes, marcadas, aoMudar }: { opcoes: string[]; marcadas: string[]; aoMudar: (v: string[]) => void }) {
  if (!opcoes.length) return <p class="text-[12px] text-muted-fg">Nenhuma tag neste espaço.</p>;
  return (
    <div class="flex flex-wrap gap-1.5">
      {opcoes.map((t) => {
        const ligada = marcadas.includes(t);
        return (
          <button key={t} type="button" aria-pressed={ligada}
            onClick={() => aoMudar(ligada ? marcadas.filter((x) => x !== t) : [...marcadas, t])}
            class={`rounded-full border px-2.5 py-1 text-[12px] transition-colors ${ligada ? 'border-accent bg-accent-bg text-accent' : 'border-border text-muted-fg hover:bg-muted'}`}>
            #{t}
          </button>
        );
      })}
    </div>
  );
}

/** Escolha entre poucas opções, lado a lado. */
export function Segmentos<T extends string>({ valor, aoMudar, opcoes, rotulo }: {
  valor: T; aoMudar: (v: T) => void; opcoes: Array<{ valor: T; rotulo: string }>; rotulo: string;
}) {
  return (
    <div role="radiogroup" aria-label={rotulo} class="inline-flex flex-wrap rounded-md bg-muted p-0.5">
      {opcoes.map((o) => (
        <button key={o.valor} type="button" role="radio" aria-checked={valor === o.valor} onClick={() => aoMudar(o.valor)}
          class={`rounded px-2.5 py-1 text-[12px] font-medium transition-colors ${valor === o.valor ? 'bg-surface text-fg shadow-sm' : 'text-muted-fg hover:text-fg'}`}>
          {o.rotulo}
        </button>
      ))}
    </div>
  );
}
