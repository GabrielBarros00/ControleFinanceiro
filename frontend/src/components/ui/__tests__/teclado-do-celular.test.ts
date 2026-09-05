/**
 * O portão do teclado que o celular abre.
 *
 * O defeito que originou este gate: `MoneyInput` montava o `<Input>` sem `type`
 * e sem `inputMode`. Sem `type`, o HTML assume `text` — e `text` sem `inputMode`
 * é o QWERTY completo. Como TODO valor em dinheiro do app passa por aquele
 * componente, uma linha faltando servia teclado alfabético em quinze telas:
 * valor do lançamento, limite do cartão, pagamento de fatura, acerto, renda,
 * orçamento, financiamento.
 *
 * Nada disso quebra teste de comportamento: no desktop existe um teclado só, e
 * a suíte inteira digita igual. O erro só aparece com um dedo, num telefone —
 * que é justamente onde ninguém roda a suíte. Por isso o gate é sobre o CÓDIGO.
 *
 * As três regras cobrem os três jeitos de errar isto:
 *   1. campo numérico que não diz qual teclado quer;
 *   2. a fonte do dinheiro perder o `inputMode` num refactor;
 *   3. campo de e-mail sem `type="email"` — QWERTY sem a tecla `@`.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const RAIZ = join(__dirname, '..', '..', '..');

function fontes(dir: string): string[] {
  const achados: string[] = [];
  for (const nome of readdirSync(dir)) {
    const caminho = join(dir, nome);
    if (statSync(caminho).isDirectory()) {
      if (nome === '__tests__' || nome === 'node_modules') continue;
      achados.push(...fontes(caminho));
    } else if (nome.endsWith('.tsx')) {
      achados.push(caminho);
    }
  }
  return achados;
}

/**
 * Apaga comentários de dentro da tag, preservando aspas.
 *
 * Não é purismo: o JSX aceita comentário de linha e de bloco entre atributos, e
 * o `MoneyInput` explica ali mesmo, por escrito, POR QUE não usa um campo
 * numérico — a frase contém `type=` e aspas. Sem esta
 * limpeza o gate lia a prosa como se fosse atributo e acusava o MoneyInput de
 * ser um campo numérico sem `inputMode` — e, pior no outro sentido, um
 * comentário que mencionasse `inputMode` MASCARARIA um campo de verdade sem ele.
 */
function semComentarios(tag: string): string {
  let saida = '';
  let aspas: string | null = null;
  for (let i = 0; i < tag.length; i += 1) {
    const c = tag[i];
    if (aspas) {
      saida += c;
      if (c === aspas) aspas = null;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      aspas = c;
      saida += c;
      continue;
    }
    // `//` só é comentário fora de aspas — `placeholder="http://x"` fica intacto.
    if (c === '/' && tag[i + 1] === '*') {
      const fim = tag.indexOf('*/', i + 2);
      i = fim === -1 ? tag.length : fim + 1;
      saida += ' ';
      continue;
    }
    if (c === '/' && tag[i + 1] === '/') {
      const fim = tag.indexOf('\n', i);
      i = fim === -1 ? tag.length : fim - 1;
      saida += ' ';
      continue;
    }
    saida += c;
  }
  return saida;
}


/**
 * Apaga os comentários do ARQUIVO INTEIRO, preservando as quebras de linha.
 *
 * O `semComentarios` acima resolve o comentário DENTRO de uma tag; este resolve
 * o caso oposto, e igualmente real: uma tag escrita dentro de um comentário.
 * O `ui/NumberInput.tsx` documenta, em prosa, por que NÃO usa um campo numérico
 * — e para explicar isso precisa escrever a tag. Sem esta limpeza o gate lia a
 * explicação como se fosse um campo de verdade e acusava justamente o
 * componente que existe para não ter o defeito.
 *
 * As quebras de linha são preservadas para o número da linha do relatório
 * continuar apontando para o lugar certo.
 *
 * O sentido perigoso — um comentário APAGAR um defeito real — não é criado
 * aqui: só o conteúdo do comentário some, e um `<Input>` fora dele continua
 * inteiro. O teste `comentário não esconde um campo de verdade` guarda isso.
 */
function semComentariosNoArquivo(fonte: string): string {
  let saida = '';
  let aspas: string | null = null;
  for (let i = 0; i < fonte.length; i += 1) {
    const c = fonte[i];
    if (aspas) {
      saida += c;
      // Escape antes da aspa: uma barra invertida a precedendo nao fecha a string.
      if (c === aspas && fonte[i - 1] !== String.fromCharCode(92)) aspas = null;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      aspas = c;
      saida += c;
      continue;
    }
    if (c === '/' && fonte[i + 1] === '*') {
      const fim = fonte.indexOf('*/', i + 2);
      const trecho = fonte.slice(i, fim === -1 ? fonte.length : fim + 2);
      saida += trecho.replace(/[^\n]/g, ' ');
      i = fim === -1 ? fonte.length : fim + 1;
      continue;
    }
    if (c === '/' && fonte[i + 1] === '/') {
      const fim = fonte.indexOf('\n', i);
      const trecho = fonte.slice(i, fim === -1 ? fonte.length : fim);
      saida += trecho.replace(/./g, ' ');
      i = fim === -1 ? fonte.length : fim - 1;
      continue;
    }
    saida += c;
  }
  return saida;
}

/**
 * Conteúdo de cada `<Input>`/`<input>`, respeitando chaves e aspas aninhadas —
 * um atributo como `max={Math.floor(x / 2)}` tem `>` dentro que não fecha a tag.
 * Mesmo parser do gate de `acoes-travam`, aqui com o nome da tag por parâmetro.
 */
function tags(fonteBruta: string, nome: string): { linha: number; tag: string }[] {
  const fonte = semComentariosNoArquivo(fonteBruta);
  const achados: { linha: number; tag: string }[] = [];
  const re = new RegExp(`<${nome}\\b`, 'g');
  let m: RegExpExecArray | null;
  while ((m = re.exec(fonte))) {
    let i = re.lastIndex;
    let profundidade = 0;
    let aspas: string | null = null;
    while (i < fonte.length) {
      const c = fonte[i];
      if (aspas) {
        if (c === aspas) aspas = null;
      } else if (c === '"' || c === "'" || c === '`') {
        aspas = c;
      } else if (c === '{') {
        profundidade += 1;
      } else if (c === '}') {
        profundidade -= 1;
      } else if (c === '>' && profundidade === 0) {
        break;
      }
      i += 1;
    }
    achados.push({
      linha: fonte.slice(0, m.index).split('\n').length,
      tag: semComentarios(fonte.slice(re.lastIndex, i)),
    });
  }
  return achados;
}

/** Todo campo de entrada do projeto: `<Input>` do design system e `<input>` cru. */
function campos(arquivo: string): { linha: number; tag: string }[] {
  const fonte = readFileSync(arquivo, 'utf-8');
  return [...tags(fonte, 'Input'), ...tags(fonte, 'input')];
}

const temAtributo = (tag: string, nome: string) =>
  new RegExp(`\\b${nome}[=\\s/>]`).test(tag);

const valorDe = (tag: string, nome: string) =>
  new RegExp(`\\b${nome}=(["'])(.*?)\\1`).exec(tag)?.[2] ?? null;

const rotulo = (arquivo: string, linha: number) =>
  `${arquivo.replace(RAIZ, 'src')}:${linha}`;

/**
 * Lê `id` e `aria-label` — de propósito, NÃO o `placeholder`: a busca por pessoa
 * da Administração diz "Buscar por nome ou e-mail" e é um `type="search"`.
 */
const pareceEmail = (tag: string) =>
  /\bid=(["'])[^"']*e-?mail[^"']*\1/i.test(tag) ||
  /\baria-label=(["'])[^"']*e-?mail[^"']*\1/i.test(tag);

describe('gate: o celular abre o teclado do campo', () => {
  it('todo type="number" diz qual teclado quer', () => {
    const faltando: string[] = [];

    for (const arquivo of fontes(RAIZ)) {
      for (const { linha, tag } of campos(arquivo)) {
        if (valorDe(tag, 'type') !== 'number') continue;
        if (!temAtributo(tag, 'inputMode')) faltando.push(rotulo(arquivo, linha));
      }
    }

    expect(faltando, [
      '`type="number"` sem `inputMode`: o Android abre teclado numérico, mas o',
      'iPhone abre o layout de números E pontuação em vez do teclado grande de',
      'dígitos.',
      'Use `inputMode="numeric"` (inteiro: dia, parcelas, quantidade de vezes) ou',
      '`inputMode="decimal"` (fracionário: percentual, quantidade com casas).',
      'Encontrados:',
      ...faltando.map((f) => `  - ${f}`),
    ].join('\n')).toEqual([]);
  });

  it('o campo de dinheiro nasce com teclado numérico', () => {
    // O gate acima não alcança o MoneyInput: ele não usa `type="number"` — não
    // pode, porque exibe "1.234,56", que um campo numérico recusa e apaga. A
    // garantia dele mora aqui, na fonte única por onde passam os quinze campos.
    const fonte = readFileSync(join(RAIZ, 'components', 'ui', 'MoneyInput.tsx'), 'utf-8');
    const [{ tag }] = tags(fonte, 'Input');

    expect(
      valorDe(tag, 'inputMode'),
      'MoneyInput sem inputMode="numeric" serve QWERTY em todo campo de valor do app.',
    ).toBe('numeric');

    // `numeric` e não `decimal`: `maskCurrency` faz `replace(/\D/g, '')`, então
    // a vírgula é PRODUZIDA pela máscara e nunca digitada. Com `decimal` o
    // iPhone mostraria uma tecla de vírgula que não faz nada ao ser tocada.
    expect(readFileSync(join(RAIZ, 'lib', 'money.ts'), 'utf-8')).toContain(
      "replace(/\\D/g, '')",
    );
  });

  it('todo campo de e-mail se declara como e-mail', () => {
    const faltando: string[] = [];

    for (const arquivo of fontes(RAIZ)) {
      for (const { linha, tag } of campos(arquivo)) {
        if (!pareceEmail(tag)) continue;
        if (valorDe(tag, 'type') !== 'email') faltando.push(rotulo(arquivo, linha));
      }
    }

    expect(faltando, [
      'Campo de e-mail sem `type="email"`: o teclado do celular vem sem a tecla',
      '`@`, o navegador não oferece autofill e não valida o formato.',
      'Encontrados:',
      ...faltando.map((f) => `  - ${f}`),
    ].join('\n')).toEqual([]);
  });

  it('o gate enxerga os três defeitos de verdade', () => {
    // Sem esta prova, um erro no parser ou nos regex deixaria as listas sempre
    // vazias e os testes acima passariam para sempre sem olhar nada.
    const cru = '<Input type="number" min={1} max={Math.floor(a / 2)} />';
    const [{ tag }] = tags(cru, 'Input');
    expect(valorDe(tag, 'type')).toBe('number');
    expect(temAtributo(tag, 'inputMode')).toBe(false);
    expect(temAtributo(tags('<Input type="number" inputMode="numeric" />', 'Input')[0].tag, 'inputMode')).toBe(true);

    const email = tags('<Input id="convite-email" value={x} />', 'Input')[0].tag;
    expect(/\bid=(["'])[^"']*e-?mail[^"']*\1/i.test(email)).toBe(true);
    expect(valorDe(email, 'type')).toBeNull();

    const rotulado = tags('<Input aria-label="E-mail de teste" type="email" />', 'Input')[0].tag;
    expect(/\baria-label=(["'])[^"']*e-?mail[^"']*\1/i.test(rotulado)).toBe(true);
    expect(valorDe(rotulado, 'type')).toBe('email');

    // A busca por pessoa cita "e-mail" no placeholder e NÃO pode virar
    // type="email" — a regra lê `id`/`aria-label`, não o texto do placeholder.
    const busca = tags('<Input type="search" placeholder="Buscar por nome ou e-mail" aria-label="Buscar pessoa" />', 'Input')[0].tag;
    expect(pareceEmail(busca)).toBe(false);
  });

  it('tag escrita DENTRO de um comentário não conta como campo', () => {
    /*
     * O caso oposto do teste seguinte, e igualmente real: o `ui/NumberInput`
     * documenta em prosa por que não usa um campo numérico — e para explicar
     * isso precisa escrever a tag. O gate acusava justamente o componente
     * criado para não ter o defeito.
     */
    const soProsa = [
      '/**',
      ' * Sobre `<input type="number">` e por que ele não serve aqui.',
      ' */',
      'export function X() { return null; }',
    ].join('\n');
    expect(tags(soProsa, 'input')).toEqual([]);

    // O SENTIDO PERIGOSO: um comentário logo acima não pode esconder um campo
    // de verdade. Sem esta metade, "ignorar comentários" viraria um jeito de
    // silenciar o gate — bastaria comentar acima do campo defeituoso.
    const comentarioEDepoisOCampo = [
      '// explica alguma coisa sobre <input type="number">',
      '<Input type="number" />',
    ].join('\n');
    const achados = tags(comentarioEDepoisOCampo, 'Input');
    expect(achados).toHaveLength(1);
    expect(valorDe(achados[0].tag, 'type')).toBe('number');
    expect(temAtributo(achados[0].tag, 'inputMode')).toBe(false);

    // E a linha reportada continua certa depois da limpeza — o relatório do
    // gate aponta arquivo:linha, e um deslocamento aqui mandaria quem for
    // corrigir para o lugar errado.
    expect(achados[0].linha).toBe(2);
  });

  it('comentário dentro da tag não conta como atributo', () => {
    // Este caso é real: o MoneyInput explica entre os atributos por que NÃO usa
    // `type="number"`. Antes da limpeza o gate lia a frase e acusava o campo.
    const comentado = tags(
      ['<Input', '  // `type="number"` está descartado aqui', '  inputMode="numeric"', '/>'].join('\n'),
      'Input',
    )[0].tag;
    expect(valorDe(comentado, 'type')).toBeNull();
    expect(valorDe(comentado, 'inputMode')).toBe('numeric');

    // E o sentido perigoso: comentário NÃO pode fazer um defeito sumir.
    const mascarado = tags(
      ['<Input type="number"', '  /* falta o inputMode aqui */', '/>'].join('\n'),
      'Input',
    )[0].tag;
    expect(valorDe(mascarado, 'type')).toBe('number');
    expect(temAtributo(mascarado, 'inputMode')).toBe(false);

    // `//` dentro de aspas é conteúdo, não comentário.
    const url = tags('<Input placeholder="http://exemplo.com" type="number" inputMode="numeric" />', 'Input')[0].tag;
    expect(valorDe(url, 'placeholder')).toBe('http://exemplo.com');
    expect(temAtributo(url, 'inputMode')).toBe(true);
  });

  it('o parser encontra os campos de verdade do projeto', () => {
    const total = fontes(RAIZ)
      .map((a) => campos(a).length)
      .reduce((a, b) => a + b, 0);
    // Se um refactor quebrar o parser, os gates silenciam varrendo zero campo.
    // O piso denuncia isso. Fica FOLGADO de propósito (são ~80 hoje): apertá-lo
    // no número exato transforma o gate num contador de campos, e a próxima tela
    // legítima o deixa vermelho sem haver defeito nenhum.
    expect(total).toBeGreaterThan(60);
  });
});
