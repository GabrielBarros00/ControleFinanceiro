/**
 * Falha o build quando a fonte declarada no CSS não foi empacotada pelo Vite.
 *
 * O `@import ... layer(base)` anterior deixava URLs `./files/...` sem resolver:
 * o build terminava com warning, a imagem não continha nenhum WOFF2 e o defeito
 * só aparecia no navegador de produção como três 404 + fallback de fonte.
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

/**
 * Lê um PNG RGBA de 8 bits sem dependência nenhuma.
 *
 * Trinta linhas em vez de `pngjs`/`sharp` porque a única pergunta a responder é
 * "este pixel é transparente?", e sob o portão do `npm audit`
 * (scripts/audit-gate.mjs) toda dependência nova é dívida permanente — a mesma
 * decisão que `scripts/gerar-icones.mjs` já tomou ao rasterizar com o Chromium
 * que o projeto já tem.
 *
 * Aceita só o que o gerador produz: 8 bits, cor tipo 6 (RGBA), sem entrelace.
 * Qualquer outra coisa levanta erro em vez de devolver pixel errado — um leitor
 * que "quase" lê é pior do que nenhum num arquivo que ninguém olha.
 */
function lerPngRgba(buffer) {
  if (buffer.readUInt32BE(0) !== 0x89504e47) throw new Error('não é um PNG');

  let largura = 0;
  let altura = 0;
  const idat = [];
  for (let pos = 8; pos < buffer.length; ) {
    const tamanho = buffer.readUInt32BE(pos);
    const tipo = buffer.toString('ascii', pos + 4, pos + 8);
    const dados = buffer.subarray(pos + 8, pos + 8 + tamanho);
    if (tipo === 'IHDR') {
      largura = dados.readUInt32BE(0);
      altura = dados.readUInt32BE(4);
      const [profundidade, cor, , , entrelace] = dados.subarray(8, 13);
      if (profundidade !== 8 || cor !== 6 || entrelace !== 0) {
        throw new Error(
          `PNG fora do formato esperado (bits=${profundidade}, cor=${cor}, entrelace=${entrelace}); `
          + 'o leitor de scripts/verify-build-assets.mjs só sabe RGBA 8 bits sem entrelace',
        );
      }
    } else if (tipo === 'IDAT') {
      idat.push(dados);
    } else if (tipo === 'IEND') {
      break;
    }
    pos += 12 + tamanho; // tamanho(4) + tipo(4) + dados + crc(4)
  }

  const cru = zlib.inflateSync(Buffer.concat(idat));
  const canais = 4;
  const linha = largura * canais;
  const pixels = Buffer.alloc(altura * linha);
  // Desfaz os filtros por scanline (PNG §9). Cada linha vem prefixada pelo
  // filtro usado, e `a`/`b`/`c` são o pixel à esquerda, o de cima e o diagonal.
  for (let y = 0; y < altura; y += 1) {
    const filtro = cru[y * (linha + 1)];
    const origem = y * (linha + 1) + 1;
    for (let i = 0; i < linha; i += 1) {
      const x = cru[origem + i];
      const a = i >= canais ? pixels[y * linha + i - canais] : 0;
      const b = y > 0 ? pixels[(y - 1) * linha + i] : 0;
      const c = y > 0 && i >= canais ? pixels[(y - 1) * linha + i - canais] : 0;
      let valor;
      if (filtro === 0) valor = x;
      else if (filtro === 1) valor = x + a;
      else if (filtro === 2) valor = x + b;
      else if (filtro === 3) valor = x + ((a + b) >> 1);
      else if (filtro === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        valor = x + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c);
      } else throw new Error(`filtro PNG desconhecido: ${filtro}`);
      pixels[y * linha + i] = valor & 0xff;
    }
  }

  return {
    largura,
    altura,
    pixel: (x, y) => pixels.subarray(y * linha + x * canais, y * linha + x * canais + canais),
  };
}

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
  'badge-96.png',
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
// `prefer_related_applications: true` diz ao Chrome "prefira o app nativo": ele
// PARA de disparar `beforeinstallprompt` e para de oferecer "Instalar". O app
// continua abrindo normalmente e nada aparece em log nenhum.
//
// O campo fica a uma palavra de distância de `related_applications`, logo abaixo
// dele no manifesto, que existe para o `getInstalledRelatedApps()` do
// diagnóstico em Configurações. Quem mexer num tropeça no outro — e é por isso
// que o portão está AQUI, no build, e não só na suíte mobile do Playwright: este
// roda a cada `npm run build`, sempre.
if (manifesto.prefer_related_applications !== false) {
  throw new Error(
    'manifest.webmanifest com `prefer_related_applications` diferente de false — '
    + 'o Chrome para de oferecer a instalação do app',
  );
}
if (!(manifesto.related_applications ?? []).some((a) => a.platform === 'webapp')) {
  throw new Error(
    'manifest.webmanifest sem a entrada auto-referente em `related_applications` — '
    + 'getInstalledRelatedApps() volta vazio e o app não sabe dizer se está instalado',
  );
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

// O aviso de vencimento (ADR 0033) VIVE aqui: o `push` é o único código do app
// que roda sem nenhuma aba aberta, e é o que faz o aviso chegar com o celular no
// bolso. Perdê-lo não quebra teste nenhum — a interface segue oferecendo
// "ativar", o navegador segue aceitando a inscrição, o servidor segue enviando,
// e a notificação simplesmente nunca aparece. É falha silenciosa de ponta a
// ponta, e por isso o portão é no build.
if (!sw.includes("addEventListener('push'")) {
  throw new Error(
    'sw.js sem handler de `push` — o aviso de vencimento não chega em aparelho nenhum (ADR 0033)',
  );
}
// Sem `notificationclick` a notificação aparece e o toque não leva a lugar
// nenhum: o Chrome apenas foca alguma janela, ou nada acontece.
if (!sw.includes("addEventListener('notificationclick'")) {
  throw new Error(
    'sw.js sem handler de `notificationclick` — tocar no aviso não abriria a tela da conta',
  );
}

/*
 * O `badge` da notificação tem de ser SILHUETA — e este portão existe porque o
 * defeito já aconteceu.
 *
 * O Android descarta as cores do badge e desenha só o canal ALFA. `badge`
 * apontava para `icon-192.png`, que é 100% opaco: o alfa é o quadrado inteiro, e
 * a notificação chegava com um retângulo preto no lugar do ícone do app.
 *
 * São duas verificações porque são dois jeitos diferentes de reintroduzir o
 * mesmo defeito: apontar o badge para a arte colorida de novo, ou regerar
 * `badge-96.png` sem transparência (basta trocar `omitBackground` em
 * `scripts/gerar-icones.mjs`). Nenhum dos dois quebra teste, aparece em log ou
 * muda uma linha de tela — só quem recebe a notificação vê.
 */
for (const uso of sw.matchAll(/badge:\s*'([^']+)'/g)) {
  if (uso[1] !== '/badge-96.png') {
    throw new Error(
      `sw.js com \`badge: '${uso[1]}'\` — o badge da notificação é desenhado só pelo `
      + 'canal alfa. Arte opaca (como icon-192.png) vira um quadrado preto na '
      + 'notificação. Use /badge-96.png, a silhueta de scripts/gerar-icones.mjs.',
    );
  }
}

const badge = lerPngRgba(fs.readFileSync(path.join(distDir, 'badge-96.png')));
const alfa = (x, y) => badge.pixel(x, y)[3];
if (alfa(0, 0) !== 0 || alfa(badge.largura - 1, badge.altura - 1) !== 0) {
  throw new Error(
    'badge-96.png tem os cantos OPACOS — no Android ele vira um quadrado chapado na '
    + 'notificação. Regere com `node scripts/gerar-icones.mjs` (o badge sai com '
    + '`omitBackground: true`).',
  );
}
if (alfa(Math.floor(badge.largura / 2), Math.floor(badge.altura / 2)) === 0) {
  throw new Error(
    'badge-96.png está transparente no CENTRO — não há silhueta para o Android '
    + 'desenhar, e a notificação chega sem símbolo nenhum.',
  );
}

console.log('[build] badge da notificação é silhueta (cantos transparentes)');

/*
 * A cor da barra de status precisa servir aos DOIS temas.
 *
 * O app instalado no Android pinta a barra de status com o `theme_color` do
 * MANIFESTO — não com a meta `theme-color` que o `use-theme.ts` mantém em dia,
 * porque o manifesto é lido na instalação e não em tempo de execução. Com
 * `#fcfbf9` (o que havia aqui), a barra ficava branca por cima de um app no tema
 * escuro, e os ícones do sistema — hora, bateria, notificações — desapareciam
 * nela: 1,03:1 de contraste contra branco.
 *
 * A regra abaixo exige uma cor **escura o bastante para ícone branco**, e a
 * escolha merece justificativa porque a alternativa parece igualmente válida:
 *
 * - Exigir só "que algum dos dois jogos de ícone passe" NÃO serve de portão:
 *   `#fcfbf9` dá 20:1 com ícone preto e passaria folgado — era exatamente a cor
 *   que produziu o defeito.
 * - Quem decide a cor do ícone é o sistema, pela luminância, e nem todo Android
 *   troca para ícone escuro numa cor clara. Ícone branco sobre cor escura é a
 *   única combinação que TODOS resolvem igual.
 * - E é a que serve aos dois temas do app: uma barra na cor da marca não briga
 *   nem com o tema claro nem com o escuro, enquanto uma barra branca só combina
 *   com um deles.
 *
 * O mesmo vale para `background_color`, que é a cor da splash de toda abertura a
 * frio: branca num app escuro é um clarão na cara de quem abre à noite.
 */
const luminancia = (hex) => {
  const canal = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const linear = canal.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
};
const contrasteComBranco = (hex) => 1.05 / (luminancia(hex) + 0.05);

const MINIMO_DE_ICONE = 4.5;
for (const campo of ['theme_color', 'background_color']) {
  const cor = manifesto[campo];
  if (typeof cor !== 'string' || !/^#[0-9a-f]{6}$/i.test(cor)) {
    throw new Error(`manifest.${campo} precisa ser um hex de 6 dígitos (veio ${JSON.stringify(cor)})`);
  }
  const contraste = contrasteComBranco(cor);
  if (contraste < MINIMO_DE_ICONE) {
    throw new Error(
      `manifest.${campo} = ${cor} dá apenas ${contraste.toFixed(2)}:1 contra ícone branco. `
      + 'A barra de status do app instalado usa esta cor e não acompanha o tema — '
      + 'clara demais, ela engole hora, bateria e notificações. '
      + 'Use uma cor escura o bastante para ícone branco (a da marca serve aos dois temas).',
    );
  }
}

console.log('[build] manifesto, service worker e ícones do PWA emitidos');
