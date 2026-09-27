/*
 * Depois de um deploy, a aba que ficou aberta ainda roda o JS antigo. Ao abrir
 * uma tela que ela nunca visitou, pede o pedaço (chunk) daquela tela pelo nome
 * com o hash ANTIGO — que não existe mais no servidor. O `import()` falha, e
 * antes desta peça a tela ficava em branco (auditoria 2026-09-26, C6).
 *
 * O remédio é recarregar: o `index.html` novo aponta para os chunks novos. O
 * Vite avisa a falha pelo evento `vite:preloadError`, que pode ser cancelado;
 * cancelado, o erro não sobe, e a página recarrega.
 *
 * ## A trava contra o laço
 *
 * Se o chunk continua faltando DEPOIS de recarregar (deploy pela metade, CDN
 * atrasada), recarregar de novo daria um laço infinito — pior que a tela de
 * erro. Por isso a recarga automática acontece no máximo uma vez a cada
 * `JANELA_MS`: a segunda falha seguida deixa o erro subir até o error boundary,
 * que mostra a tela com o botão "Recarregar". A janela é de tempo, e não "uma
 * vez por sessão", porque a mesma aba pode atravessar dois deploys.
 */

const CHAVE = 'cf-recarga-por-chunk';
export const JANELA_MS = 30_000;

/** Recarrega se a última recarga automática foi há mais de `JANELA_MS` (ou nunca). */
export function deveRecarregar(agora: number, ultima: number | null): boolean {
  return ultima == null || !Number.isFinite(ultima) || agora - ultima > JANELA_MS;
}

function lerUltima(): number | null {
  try {
    const bruto = sessionStorage.getItem(CHAVE);
    return bruto == null ? null : Number(bruto);
  } catch {
    return null;
  }
}

function gravar(agora: number): boolean {
  try {
    sessionStorage.setItem(CHAVE, String(agora));
    return true;
  } catch {
    // Sem armazenamento (aba privada restrita), não há como lembrar que já
    // recarregou — e recarregar sem essa memória é o laço. Melhor a tela de erro.
    return false;
  }
}

/** Instala o ouvinte; devolve a função que o remove (usada pelos testes). */
export function instalarRecargaPorChunk(
  recarregar: () => void = () => window.location.reload(),
): () => void {
  const aoFalhar = (evento: Event) => {
    const agora = Date.now();
    if (!deveRecarregar(agora, lerUltima())) return;
    if (!gravar(agora)) return;
    evento.preventDefault();
    recarregar();
  };
  window.addEventListener('vite:preloadError', aoFalhar);
  return () => window.removeEventListener('vite:preloadError', aoFalhar);
}
