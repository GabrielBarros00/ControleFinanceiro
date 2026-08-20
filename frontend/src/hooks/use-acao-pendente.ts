import * as React from 'react';

function ehPromessa(valor: unknown): valor is PromiseLike<unknown> {
  return typeof (valor as PromiseLike<unknown> | null)?.then === 'function';
}

/**
 * Segura o gatilho de uma ação enquanto ela não termina.
 *
 * O `Button` usa isto por dentro, então a maioria das telas não precisa chamar
 * este hook. Ele existe para os gatilhos que NÃO passam pelo `Button`: um
 * `<button>` cru com estilo próprio (o cartão de crédito, o item da lista de
 * notificações) e o `Switch` — casos em que trocar pelo componente brigaria
 * com o layout.
 *
 * A regra é a mesma dos dois lados: se a ação devolve uma promessa, `pendente`
 * fica verdadeiro até ela ASSENTAR — resolvida ou rejeitada. Rejeição que não
 * destravasse deixaria o botão morto até a próxima navegação, que é pior que o
 * problema original.
 *
 * São duas travas de propósito. O `disabled` que a tela deriva de `pendente` só
 * vale depois do re-render; dois cliques rápidos caem no mesmo ciclo do React e
 * o segundo chega antes disso. A trava por `ref` cobre essa janela.
 */
export function useAcaoPendente<E>(acao?: (evento: E) => unknown) {
  const [pendente, setPendente] = React.useState(false);
  const emVoo = React.useRef(false);
  const montado = React.useRef(true);

  React.useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
    };
  }, []);

  const disparar = React.useCallback(
    (evento: E) => {
      if (emVoo.current) return;
      const retorno = acao?.(evento);
      if (!ehPromessa(retorno)) return;

      emVoo.current = true;
      setPendente(true);
      const solta = () => {
        emVoo.current = false;
        // A ação pode terminar com a tela já desmontada (diálogo que fecha no
        // sucesso, logout que navega). Sem a guarda, cada uma dessas vira um
        // aviso de estado em componente desmontado.
        if (montado.current) setPendente(false);
      };
      retorno.then(solta, solta);
    },
    [acao],
  );

  return { disparar, pendente };
}
