#!/usr/bin/env node
/*
 * Conferência do componente MCP Apps depois do build (ADR 0035).
 *
 * O recurso é servido com CSP VAZIA — `connectDomains` e `resourceDomains`
 * sem nada —, então qualquer `<script src="https://…">` ou folha externa que o
 * build deixasse passar seria bloqueada NO HOST, em silêncio: o componente
 * simplesmente não apareceria no ChatGPT/Claude, e nenhum teste daqui veria.
 * E ele é carregado a cada resposta de tool, então o tamanho tem teto.
 */
import { readFileSync, statSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ARQUIVO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../backend/app/mcp/ui/widget.html');
// O grosso não é o componente: é a ponte OFICIAL do MCP Apps, que valida o
// protocolo com zod (~2/3 do arquivo). Reimplementar o postMessage à mão
// economizaria ~300 KB e trocaria por um protocolo que a gente teria de seguir
// sozinho a cada versão — não compensa. O teto que importa para quem carrega é
// o comprimido (o host serve o recurso com gzip); o bruto só barra o absurdo.
const TETO_BYTES = 512 * 1024;
const TETO_GZIP = 160 * 1024;

const html = readFileSync(ARQUIVO, 'utf8');
const tamanho = statSync(ARQUIVO).size;
const erros = [];

const comprimido = gzipSync(html).length;
if (tamanho > TETO_BYTES) erros.push(`widget.html tem ${tamanho} bytes (teto ${TETO_BYTES})`);
if (comprimido > TETO_GZIP) erros.push(`widget.html comprimido tem ${comprimido} bytes (teto ${TETO_GZIP})`);
if (/<script[^>]+\bsrc=/i.test(html)) erros.push('há <script src=…>: tudo precisa estar embutido');
if (/<link[^>]+rel=["']?(stylesheet|modulepreload)/i.test(html)) erros.push('há <link rel=stylesheet|modulepreload>: CSS/JS precisam estar embutidos');
if (!html.includes('<div id="root">')) erros.push('não achei o ponto de montagem #root');

if (erros.length) {
  console.error(`check-mcp-widget: ${erros.join('; ')}`);
  process.exit(1);
}
console.log(`check-mcp-widget: ok (${(tamanho / 1024).toFixed(1)} KiB; ${(comprimido / 1024).toFixed(1)} KiB com gzip; tudo embutido)`);
