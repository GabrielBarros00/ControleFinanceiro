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
// Era 460 KB: a ponte oficial do MCP Apps (com zod, ~227 KB) e o React 19
// (~215 KB). O componente é baixado e executado de novo em cada resposta que o
// desenha, e no ChatGPT, em modo agente, isso virou memória do navegador sem
// parar. Hoje são ~37 KB: Preact e uma ponte escrita à mão, cuja conformidade é
// provada contra o host OFICIAL (`bridge.conformidade.test.ts`) em vez de
// presumida. Os tetos seguram a volta do peso: passar deles é decisão consciente.
//
// A v4 (ADR 0035 §11) subiu o teto de 64/24 KiB para 160/48 KiB, de propósito:
// a escrita passou a desenhar o resultado (com editor, diferença e Desfazer) e
// há uma tela por assunto (lista, fatura, extrato, dívidas, metas…). O peso vem
// de código nosso — nenhuma biblioteca nova. Medido no harness do Playwright
// antes de o teto mudar: ~4 MB de memória do navegador por instância com 30
// seguidas (a v3 ficava em ~3 MB), heap estável e sem laço de redimensionamento.
const TETO_BYTES = 160 * 1024;
const TETO_GZIP = 48 * 1024;

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
