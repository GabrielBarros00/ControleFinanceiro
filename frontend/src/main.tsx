import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Import de módulo, não `@import ... layer(base)` no CSS: o pipeline do Vite
// precisa resolver os URLs relativos do pacote e copiar os três `.woff2` para
// a imagem de produção. Pela cascade layer eles ficavam como `./files/...`,
// geravam warning no build e não eram emitidos — fonte quebrada só em produção.
import '@fontsource-variable/geist'
import './index.css'
import App from './App.tsx'
import { iniciarCapturaDeInstalacao } from './lib/install'

/*
 * ANTES do `createRoot`, e é o ponto todo.
 *
 * `beforeinstallprompt` dispara uma vez por carregamento e o Chrome não o repete
 * em navegação de SPA. Enquanto a captura morava dentro do hook — que só é usado
 * por um cartão no fim de Configurações —, o evento chegava em `/login`, não
 * havia ninguém escutando, e o botão "Instalar" nunca mais aparecia. Ver o
 * cabeçalho de `lib/install.ts`.
 *
 * Sem o guarda de `import.meta.env.PROD` que envolve o service worker abaixo: em
 * desenvolvimento o evento simplesmente não dispara (não há SW para satisfazer o
 * critério do Chrome), então o guarda não protegeria nada — só impediria os
 * testes de exercitarem este caminho.
 */
iniciarCapturaDeInstalacao()

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
