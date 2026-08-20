/**
 * O portão que impede o defeito de voltar pela porta que ele já usou.
 *
 * A trava de duplo clique mora no `Button`: `onClick` que devolve promessa
 * tranca o botão sozinho. Só que existe UM caminho em que o clique não dispara
 * a ação e o `Button` não tem como perceber nada — o `type="submit"`, em que
 * quem submete é o `<form>`. Ali a trava tem de ser dita à mão, com `pending`.
 *
 * É exatamente o tipo de detalhe que ninguém lembra ao escrever a próxima tela,
 * e que nenhum teste de comportamento pega: o formulário funciona, salva certo,
 * e só falha quando alguém clica duas vezes rápido. Por isso o gate é sobre o
 * CÓDIGO — ele lê os fontes e reprova o botão de submit que não se protege.
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

/** Conteúdo de cada `<Button ...>`, respeitando chaves e aspas aninhadas. */
function tagsDeBotao(fonte: string): { linha: number; tag: string }[] {
  const achados: { linha: number; tag: string }[] = [];
  const re = /<Button\b/g;
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
      tag: fonte.slice(re.lastIndex, i),
    });
  }
  return achados;
}

describe('gate: toda ação se tranca enquanto corre', () => {
  it('nenhum <Button type="submit"> fica sem `pending`', () => {
    const faltando: string[] = [];

    for (const arquivo of fontes(RAIZ)) {
      const fonte = readFileSync(arquivo, 'utf-8');
      if (!fonte.includes('<Button')) continue;

      for (const { linha, tag } of tagsDeBotao(fonte)) {
        const ehSubmit = /\btype=(["'])submit\1/.test(tag);
        const temPending = /\bpending[=\s/>]/.test(tag);
        if (ehSubmit && !temPending) {
          faltando.push(`${arquivo.replace(RAIZ, 'src')}:${linha}`);
        }
      }
    }

    expect(faltando, [
      'Botão de submit sem `pending`: o clique não roda o handler (quem submete',
      'é o <form>), então o Button não consegue se travar sozinho e um duplo',
      'clique manda o formulário duas vezes.',
      'Passe `pending={isSubmitting}` (react-hook-form) ou o `isPending` da',
      'mutação. Encontrados:',
      ...faltando.map((f) => `  - ${f}`),
    ].join('\n')).toEqual([]);
  });

  it('o gate enxerga um submit desprotegido', () => {
    // Sem esta prova, um erro no parser deixaria a lista sempre vazia e o teste
    // acima passaria para sempre sem olhar nada.
    const exemplo = '<Button type="submit" className="x">Salvar</Button>';
    const [{ tag }] = tagsDeBotao(exemplo);
    expect(/\btype=(["'])submit\1/.test(tag)).toBe(true);
    expect(/\bpending[=\s/>]/.test(tag)).toBe(false);

    const protegido = '<Button type="submit" pending={isSubmitting}>Salvar</Button>';
    expect(/\bpending[=\s/>]/.test(tagsDeBotao(protegido)[0].tag)).toBe(true);
  });

  it('o parser encontra os botões de verdade do projeto', () => {
    const total = fontes(RAIZ)
      .map((a) => tagsDeBotao(readFileSync(a, 'utf-8')).length)
      .reduce((a, b) => a + b, 0);
    // Se um refactor quebrar o parser, o gate silencia. Este piso o denuncia.
    expect(total).toBeGreaterThan(100);
  });
});
