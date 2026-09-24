/**
 * Build do componente MCP Apps (ADR 0035) — separado do SPA.
 *
 * Sai UM arquivo HTML autocontido (JS e CSS embutidos pelo
 * `vite-plugin-singlefile`) em `backend/app/mcp/ui/widget.html`, que o servidor
 * MCP publica como o recurso `ui://controle-financeiro/widget-vN.html` (versão em
 * `backend/app/mcp/ui/__init__.py`: mudou o HTML, sobe a versão). Tudo
 * embutido porque a CSP do recurso é vazia: o componente não busca nada fora.
 *
 * O arquivo gerado é versionado, e o CI reconstrói e confere que não há diff —
 * o backend não depende do Node para subir.
 *
 * Preact, não React: o componente é baixado e executado de novo em cada
 * resposta que o desenha, e o React 19 sozinho eram ~215 KB. O JSX compila para
 * `preact` (o pragma `@jsxImportSource preact` nos arquivos diz o mesmo ao TS e
 * ao vitest). O SPA continua em React; nada daqui é compartilhado com ele.
 *
 *   npm run build:mcp-widget
 */
import path from 'path';
import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

const RAIZ = path.resolve(__dirname, 'src/mcp-widget');

export default defineConfig({
  root: RAIZ,
  plugins: [viteSingleFile({ removeViteModuleLoader: true })],
  oxc: { jsx: { runtime: 'automatic', importSource: 'preact' } },
  build: {
    outDir: path.resolve(__dirname, '../backend/app/mcp/ui'),
    // A pasta tem o `__init__.py` do pacote Python: não se apaga nada lá.
    emptyOutDir: false,
    target: 'es2022',
    // Um arquivo só e determinístico (o CI compara com o versionado).
    rollupOptions: { input: path.join(RAIZ, 'widget.html') },
    reportCompressedSize: false,
  },
});
