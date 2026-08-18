import * as React from 'react';

type Theme = 'light' | 'dark' | 'system';

/*
 * Cor da barra de status do navegador (e da moldura do app instalado).
 *
 * São os `--background` de `index.css` convertidos para hex: claro
 * oklch(0.988 0.003 95) e escuro oklch(0.185 0.006 285). Precisam ser hex
 * literais — a meta `theme-color` é lida pelo navegador antes de qualquer CSS,
 * então `var(--background)` não resolveria.
 */
const THEME_COLOR: Record<'light' | 'dark', string> = {
  light: '#fcfbf9',
  dark: '#121215',
};

function aplicar(efetivo: 'light' | 'dark') {
  const root = window.document.documentElement;
  root.classList.remove('light', 'dark');
  root.classList.add(efetivo);
  // Instalado como app, esta meta é a cor da barra de status — sem atualizá-la
  // o topo da tela fica claro sobre um app escuro (e vice-versa) a cada troca.
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', THEME_COLOR[efetivo]);
}

export function useTheme() {
  const [theme, setThemeState] = React.useState<Theme>(() => {
    return (localStorage.getItem('theme') as Theme) || 'system';
  });

  const setTheme = (theme: Theme) => {
    localStorage.setItem('theme', theme);
    setThemeState(theme);
  };

  React.useEffect(() => {
    if (theme !== 'system') {
      aplicar(theme);
      return;
    }

    // 'system' precisa ACOMPANHAR o sistema, não só lê-lo uma vez: quem deixa o
    // celular trocar de tema ao anoitecer ficava com o app no tema da manhã até
    // recarregar a página.
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const sincronizar = () => aplicar(mq.matches ? 'dark' : 'light');
    sincronizar();
    mq.addEventListener('change', sincronizar);
    return () => mq.removeEventListener('change', sincronizar);
  }, [theme]);

  return { theme, setTheme };
}
