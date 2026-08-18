import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Import de módulo, não `@import ... layer(base)` no CSS: o pipeline do Vite
// precisa resolver os URLs relativos do pacote e copiar os três `.woff2` para
// a imagem de produção. Pela cascade layer eles ficavam como `./files/...`,
// geravam warning no build e não eram emitidos — fonte quebrada só em produção.
import '@fontsource-variable/geist'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

/*
 * Service worker — só no build de produção.
 *
 * Em desenvolvimento ele seria ativamente nocivo: o Vite serve os módulos sem
 * hash e recarrega por HMR, e um SW cacheando isso faz a página parar de
 * refletir o que está no editor — o tipo de defeito em que se perde uma tarde
 * antes de desconfiar do cache.
 *
 * `load` e não imediato: registrar durante o carregamento inicial faz o SW
 * disputar banda com os bundles da primeira visita, que é justamente a mais
 * lenta.
 *
 * O registro FALHA em silêncio de propósito. Não ter service worker significa
 * "não dá para instalar como app e não há casca offline" — não afeta nenhuma
 * função do produto, e um alerta de erro aqui assustaria por nada.
 */
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
