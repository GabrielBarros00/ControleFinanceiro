/**
 * Falha o build quando a fonte declarada no CSS não foi empacotada pelo Vite.
 *
 * O `@import ... layer(base)` anterior deixava URLs `./files/...` sem resolver:
 * o build terminava com warning, a imagem não continha nenhum WOFF2 e o defeito
 * só aparecia no navegador de produção como três 404 + fallback de fonte.
 */
import fs from 'node:fs';
import path from 'node:path';

const distDir = path.resolve(import.meta.dirname, '..', 'dist');
const assetsDir = path.join(distDir, 'assets');
const files = fs.readdirSync(assetsDir);
const css = files
  .filter((file) => file.endsWith('.css'))
  .map((file) => fs.readFileSync(path.join(assetsDir, file), 'utf8'))
  .join('\n');

const expectedPrefixes = [
  'geist-cyrillic-wght-normal-',
  'geist-latin-ext-wght-normal-',
  'geist-latin-wght-normal-',
];

for (const prefix of expectedPrefixes) {
  const font = files.find((file) => file.startsWith(prefix) && file.endsWith('.woff2'));
  if (!font) {
    throw new Error(`build incompleto: fonte ${prefix}*.woff2 não foi emitida`);
  }
  if (!css.includes(font)) {
    throw new Error(`build incompleto: ${font} existe, mas nenhum CSS a referencia`);
  }
}

console.log('[build] fontes Geist emitidas e referenciadas');

/*
 * PWA: o que a instalação exige tem de estar no `dist`.
 *
 * São arquivos de `public/`, que o Vite copia sem processar — e é exatamente por
 * isso que precisam de portão: nada no build reclama se um deles for renomeado
 * ou apagado. O sintoma seria só o Chrome parar de oferecer "Instalar
 * aplicativo", em produção, sem erro em lugar nenhum. Mesmo motivo do gate de
 * fontes acima: o silêncio é o problema.
 */
const ARQUIVOS_DO_PWA = [
  'manifest.webmanifest',
  'sw.js',
  'icon-192.png',
  'icon-512.png',
  'icon-maskable-512.png',
  'apple-touch-icon-180.png',
];

for (const arquivo of ARQUIVOS_DO_PWA) {
  if (!fs.existsSync(path.join(distDir, arquivo))) {
    throw new Error(
      `build incompleto: ${arquivo} não foi emitido — sem ele o app deixa de ser instalável `
      + '(regere os ícones com `node scripts/gerar-icones.mjs`)',
    );
  }
}

// Um manifesto que não parseia é servido com 200 e ignorado em silêncio pelo
// navegador; e sem `icons` ou sem `start_url` o Chrome não oferece a instalação.
const manifesto = JSON.parse(fs.readFileSync(path.join(distDir, 'manifest.webmanifest'), 'utf8'));
for (const campo of ['name', 'short_name', 'start_url', 'display', 'icons']) {
  if (!manifesto[campo]) {
    throw new Error(`manifest.webmanifest sem "${campo}" — o navegador não oferece a instalação`);
  }
}
const tamanhos = new Set(manifesto.icons.map((i) => i.sizes));
for (const exigido of ['192x192', '512x512']) {
  if (!tamanhos.has(exigido)) {
    throw new Error(`manifest.webmanifest sem ícone ${exigido} — exigido pelo Chrome para instalar`);
  }
}
if (!manifesto.icons.some((i) => String(i.purpose ?? '').includes('maskable'))) {
  throw new Error('manifest.webmanifest sem ícone `maskable` — o launcher do Android corta a arte');
}

// O service worker sem handler de `fetch` não conta como service worker para o
// critério de instalabilidade do Chrome; e `/api/` cacheado é a regra do
// arquivo, não uma preferência (ver o comentário em public/sw.js).
const sw = fs.readFileSync(path.join(distDir, 'sw.js'), 'utf8');
if (!sw.includes("addEventListener('fetch'")) {
  throw new Error('sw.js sem handler de `fetch` — o Chrome não oferece a instalação');
}
// A guarda de `/api/` hoje é redundante (nada abaixo dela cachearia a API), e o
// portão existe justamente por isso: sem ele, alguém a remove por parecer morta
// — e ela volta a importar no dia em que aparecer um "cache-first para todo
// GET". Aí é saldo em cache, com cara de atual.
if (!sw.includes("startsWith('/api/')")) {
  throw new Error(
    'sw.js perdeu a guarda de `/api/` — leia o comentário dela em public/sw.js antes de remover',
  );
}

console.log('[build] manifesto, service worker e ícones do PWA emitidos');
