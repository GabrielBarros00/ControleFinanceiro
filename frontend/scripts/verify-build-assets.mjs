/**
 * Falha o build quando a fonte declarada no CSS não foi empacotada pelo Vite.
 *
 * O `@import ... layer(base)` anterior deixava URLs `./files/...` sem resolver:
 * o build terminava com warning, a imagem não continha nenhum WOFF2 e o defeito
 * só aparecia no navegador de produção como três 404 + fallback de fonte.
 */
import fs from 'node:fs';
import path from 'node:path';

const assetsDir = path.resolve(import.meta.dirname, '..', 'dist', 'assets');
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
