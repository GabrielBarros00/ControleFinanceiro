import * as React from 'react';

/**
 * O atalho de teclado que abre a busca.
 *
 * `/` é a convenção de busca em produto de leitura; `Ctrl/⌘+K` é a de paleta de
 * comando. Os dois abrem a mesma coisa porque as duas expectativas convivem, e
 * qual delas a pessoa traz não é escolha nossa.
 *
 * O `/` só vale FORA de campo de texto — senão barra vira atalho no meio de um
 * título de despesa, e o app passa a comer o que se digita.
 */
export function useAtalhoDeBusca(abrir: () => void) {
  React.useEffect(() => {
    const emCampo = (alvo: EventTarget | null) => {
      const el = alvo as HTMLElement | null;
      if (!el) return false;
      return el.isContentEditable
        || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
    };
    const aoTeclar = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        abrir();
        return;
      }
      if (e.key === '/' && !emCampo(e.target)) {
        e.preventDefault();
        abrir();
      }
    };
    window.addEventListener('keydown', aoTeclar);
    return () => window.removeEventListener('keydown', aoTeclar);
  }, [abrir]);
}
