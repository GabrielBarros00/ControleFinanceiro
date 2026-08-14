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
