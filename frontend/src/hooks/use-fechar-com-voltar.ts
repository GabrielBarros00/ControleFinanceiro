import * as React from 'react';

/*
 * O botão VOLTAR fecha a camada aberta, em vez de sair da página.
 *
 * ## O problema
 *
 * No celular, "voltar" é o gesto mais usado do aparelho — e é com ele que se
 * fecha qualquer coisa aberta por cima. No app ele fazia outra coisa: com a
 * gaveta "Mais" aberta, voltar levava para a página ANTERIOR e a gaveta ia
 * junto. A pessoa perdia a tela em que estava para fechar um menu.
 *
 * Verificado: valia para a gaveta e também para "Nova despesa" — ou seja, para
 * qualquer sobreposição. Por isso a correção é um hook usado pelo primitivo
 * `ui/dialog.tsx`, e não um remendo na gaveta.
 *
 * ## Como funciona
 *
 * Ao abrir, empilha uma entrada de histórico com a MESMA URL e uma MARCA própria
 * em `history.state`. O "voltar" gasta essa entrada em vez de sair da página, e
 * o `popstate` que ele dispara é o sinal para fechar.
 *
 * A URL não muda: o React Router re-renderiza a mesma rota e nada mais acontece.
 * Guardar a camada na URL foi considerado e descartado — um `?menu=aberto`
 * copiado ou favoritado reabriria a gaveta, e camadas não são endereços.
 *
 * ## Por que a marca, e não apenas "eu empilhei, então eu desempilho"
 *
 * Porque a contabilidade ingênua NÃO COMPÕE, e o preço de errar é alto: um
 * `history.back()` a mais joga a pessoa para fora do aplicativo. Aconteceu
 * durante a implementação — o teste terminou em `about:blank`.
 *
 * Dois casos quebram a contagem:
 *
 * - **Camadas sobrepostas** (a confirmação "Descartar esta despesa?" por cima do
 *   formulário): duas instâncias do hook vivas ao mesmo tempo.
 * - **A remontagem do modo estrito**: em desenvolvimento o React monta, desmonta
 *   e remonta cada efeito, e `pushState` é síncrono enquanto `history.back()` é
 *   assíncrono — a ordem real embaralha as contas, e empilhar com um `back`
 *   pendente ainda TRUNCA as entradas à frente.
 *
 * Com a marca, a pergunta deixa de ser "quantas empilhei?" e passa a ser "a
 * entrada do topo AGORA é minha?". Essa pergunta tem resposta certa nos dois
 * casos, e ela é a única condição para desempilhar.
 *
 * ## O que acontece quando a pessoa navega com a camada aberta
 *
 * Tocar num item da gaveta "Mais" fecha a camada E navega. Aí o topo da pilha
 * passa a ser a rota nova (o React Router escreve o `state` dele, sem a nossa
 * marca), a condição falha e não desempilhamos nada — que é o certo:
 * desempilhar ali desfaria a navegação que a pessoa acabou de pedir. Isto também
 * foi um defeito real durante a implementação, e três specs o pegaram.
 */

/** Identifica cada camada. Módulo, e não `ref`: precisa ser único no documento. */
let proximaMarca = 1;

/**
 * Módulo pelo mesmo motivo: o `popstate` é global e pode chegar a um efeito
 * diferente daquele que pediu o `history.back()` — é o que acontece na
 * remontagem do modo estrito.
 */
let voltandoProgramaticamente = false;

export function useFecharComVoltar(aberto: boolean, fechar: () => void) {
  // O callback vive num `ref` para não entrar nas dependências do efeito: ele
  // costuma ser recriado a cada render, e uma dependência instável faria o
  // efeito empilhar uma entrada de histórico por render.
  const fecharRef = React.useRef(fechar);
  // A atualização vai num efeito, e não no corpo do componente: escrever num
  // `ref` durante o render é o que a regra `react-hooks/refs` proíbe (e com
  // razão — o render pode ser descartado). O `popstate` só chega depois da
  // pintura, então o valor sempre está em dia quando importa.
  React.useEffect(() => { fecharRef.current = fechar; }, [fechar]);

  React.useEffect(() => {
    if (!aberto) return;

    const marca = proximaMarca;
    proximaMarca += 1;
    window.history.pushState({ ...window.history.state, camadaSobreposta: marca }, '');

    const aoVoltar = () => {
      if (voltandoProgramaticamente) {
        voltandoProgramaticamente = false;
        return;
      }
      fecharRef.current();
    };
    window.addEventListener('popstate', aoVoltar);

    return () => {
      window.removeEventListener('popstate', aoVoltar);
      // A ÚNICA condição: a entrada do topo ainda é a nossa. Se não for, ou ela
      // já foi gasta por um "voltar", ou alguém empilhou por cima (navegação,
      // outra camada) — nos dois casos, mexer na pilha faria estrago.
      if (window.history.state?.camadaSobreposta !== marca) return;
      voltandoProgramaticamente = true;
      window.history.back();
    };
  }, [aberto]);
}
