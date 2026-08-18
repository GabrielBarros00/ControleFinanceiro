import * as React from 'react';

/**
 * Uma media query como estado do React.
 *
 * O app é responsivo por CSS, e essa é a regra: quem só muda de APARÊNCIA fica
 * no Tailwind. Este hook existe para o punhado de casos em que o celular precisa
 * de uma ÁRVORE diferente, não de estilos diferentes — filtros que viram uma
 * gaveta, por exemplo. Fazer isso com `sm:hidden` + `hidden sm:block` renderiza
 * os mesmos campos DUAS vezes: dois `<label for="x">` para o mesmo `id`, dois
 * elementos com o mesmo nome acessível, e um `getByLabelText` que passa a achar
 * dois resultados e falhar.
 *
 * `useSyncExternalStore` e não `useState` + `useEffect`: o valor é estado
 * externo ao React (o navegador é o dono), e é ele que garante leitura
 * consistente na primeira renderização, sem o quadro extra em que o componente
 * aparece na versão errada e troca em seguida.
 */
export function useMediaQuery(query: string): boolean {
  const mq = React.useMemo(() => window.matchMedia(query), [query]);
  return React.useSyncExternalStore(
    (onChange) => {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    },
    () => mq.matches,
    // Sem servidor de renderização neste app; o valor de fallback é "desktop"
    // porque é o que os testes em jsdom veem (o `matchMedia` de lá responde
    // `matches: false` a qualquer consulta).
    () => false,
  );
}

/**
 * Abaixo do `sm` do Tailwind (640px) — o mesmo ponto de corte usado nas classes,
 * escrito uma vez só para não divergir de `sm:` quando alguém mexer num lugar.
 */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 639px)');
}
