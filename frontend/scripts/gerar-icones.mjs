/**
 * Gera os ícones do app instalável a partir de `public/favicon.png`.
 *
 *     node scripts/gerar-icones.mjs
 *
 * Existe como script versionado, e não como quatro PNGs commitados sem
 * procedência: a fonte de hoje é um PNG de 256×256 — o único arquivo de marca do
 * repositório. O Android pede 512×512, então há um upscale, e o resultado é
 * levemente mais macio do que sairia de um vetor. No dia em que houver um SVG ou
 * um PNG maior, basta trocar `ORIGEM` e rodar de novo.
 *
 * Rasteriza com o **Chromium do Playwright**, que já é dependência de
 * desenvolvimento do projeto (a suíte e2e e o roteiro de capturas usam o mesmo).
 * A alternativa óbvia seria o `sharp`, mas ele é binário nativo e traria uma
 * árvore de dependências nova só para redimensionar quatro imagens que mudam uma
 * vez por ano — sob o portão do `npm audit` (scripts/audit-gate.mjs), toda
 * dependência nova é dívida permanente.
 *
 * O que sai:
 *
 * - `icon-192.png`, `icon-512.png` — os dois tamanhos que o Chrome exige para
 *   oferecer a instalação.
 * - `icon-maskable-512.png` — variante `maskable`. O Android recorta o ícone na
 *   forma do launcher (círculo, squircle, gota) e a área garantida é só o
 *   círculo central de 80% do lado; sem margem, a arte é cortada pelas bordas.
 *   A margem vai preenchida com a cor da marca, não transparente — área
 *   transparente num maskable vira preto em vários launchers.
 * - `apple-touch-icon-180.png` — o iOS NÃO lê o manifesto para o ícone da tela
 *   de início, lê esta tag. E compõe sobre preto o que for transparente, então
 *   este sai com fundo chapado.
 */
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';

const PUBLICO = path.resolve(import.meta.dirname, '..', 'public');
const ORIGEM = path.join(PUBLICO, 'favicon.png');

if (!fs.existsSync(ORIGEM)) {
  throw new Error(`fonte do ícone não encontrada: ${ORIGEM}`);
}
const fonteBase64 = fs.readFileSync(ORIGEM).toString('base64');

/**
 * Cor do FUNDO da própria arte, amostrada do centro da borda superior.
 *
 * O ícone do app é um quadrado arredondado escuro que preenche quase toda a
 * moldura. Preencher a margem do `maskable` com a cor da marca (índigo) produzia
 * um quadro indígo em volta de um quadrado escuro — duas peças, não um ícone.
 * Amostrando, a margem some visualmente e o resultado lê como um tile só,
 * qualquer que seja a forma que o launcher recorte.
 *
 * Amostrar em vez de fixar em hex: se a arte trocar, o script continua certo.
 */
async function corDeFundoDaArte(navegador) {
  const pagina = await navegador.newPage();
  const cor = await pagina.evaluate(async (base64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${base64}`;
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    // Centro do topo: dentro do quadrado arredondado (os cantos podem ser
    // transparentes) e acima de qualquer elemento do desenho.
    const [r, g, b] = ctx.getImageData(Math.floor(img.width / 2), 3, 1, 1).data;
    return `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
  }, fonteBase64);
  await pagina.close();
  return cor;
}

/**
 * @param {number} lado      tamanho final em px
 * @param {string} saida     nome do arquivo em public/
 * @param {object} opcoes
 * @param {number} opcoes.escala  fração do lado ocupada pela arte (1 = cheio)
 * @param {string|null} opcoes.fundo  cor de fundo, ou null para transparente
 */
async function gerar(navegador, lado, saida, { escala = 1, fundo = null } = {}) {
  const pagina = await navegador.newPage({
    viewport: { width: lado, height: lado },
    deviceScaleFactor: 1,
  });
  const arte = Math.round(lado * escala);
  await pagina.setContent(`
    <style>
      html, body { margin: 0; padding: 0; width: ${lado}px; height: ${lado}px; }
      body {
        background: ${fundo ?? 'transparent'};
        display: flex; align-items: center; justify-content: center;
      }
      img { width: ${arte}px; height: ${arte}px; image-rendering: auto; }
    </style>
    <img src="data:image/png;base64,${fonteBase64}" alt="">
  `);
  // `omitBackground` só quando o ícone é transparente de propósito; com fundo
  // chapado ele apagaria justamente a cor que o launcher precisa ver.
  await pagina.screenshot({
    path: path.join(PUBLICO, saida),
    omitBackground: fundo === null,
  });
  await pagina.close();
}

const navegador = await chromium.launch();
try {
  const fundo = await corDeFundoDaArte(navegador);
  await gerar(navegador, 192, 'icon-192.png');
  await gerar(navegador, 512, 'icon-512.png');
  await gerar(navegador, 512, 'icon-maskable-512.png', { escala: 0.8, fundo });
  await gerar(navegador, 180, 'apple-touch-icon-180.png', { fundo });
  console.log(`[icones] fundo amostrado da arte: ${fundo}`);
} finally {
  await navegador.close();
}

console.log('[icones] icon-192, icon-512, icon-maskable-512 e apple-touch-icon-180 gerados em public/');
