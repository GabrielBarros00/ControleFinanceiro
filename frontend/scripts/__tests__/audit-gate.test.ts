/**
 * O gate de auditoria tem de falhar FECHADO.
 *
 * O defeito era `relatorio.vulnerabilities ?? {}`: qualquer payload sem essa
 * chave virava laço vazio e o gate imprimia "Sem vulnerabilidades" com código
 * zero. Quando o registry falha, o npm imprime um JSON de ERRO **em stdout** e
 * sai com código != 0 — ele passava pelo catch, era parseado sem problema, e o
 * CI ficava verde tendo auditado exatamente nada.
 *
 * A falha que importa aqui é a mais difícil de observar por acidente: só
 * acontece com o registry fora do ar. Por isso o gate aceita `--relatorio`, e
 * estes testes alimentam payloads ruins direto.
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const GATE = join(process.cwd(), 'scripts', 'audit-gate.mjs');
const DIR = mkdtempSync(join(tmpdir(), 'audit-gate-'));

/** `spawnSync` (não `execFileSync`) para capturar stdout E stderr também no
 *  caminho de sucesso — os avisos do gate saem por stderr. */
function rodar(payload: unknown, aceitos?: unknown[]): { code: number; saida: string } {
  const sufixo = Math.random().toString(36).slice(2);
  const arquivo = join(DIR, `relatorio-${sufixo}.json`);
  writeFileSync(arquivo, typeof payload === 'string' ? payload : JSON.stringify(payload));
  const args = [GATE, '--relatorio', arquivo];
  // A lista de exceções também é injetada: em produção ela é VAZIA (exceção
  // aberta é dívida de segurança), e testar as regras dela contra a lista real
  // fazia estes casos dependerem de haver alguma vulnerabilidade tolerada no
  // momento — eles quebraram quando a última saiu.
  if (aceitos) {
    const arquivoAceitos = join(DIR, `aceitos-${sufixo}.json`);
    writeFileSync(arquivoAceitos, JSON.stringify(aceitos));
    args.push('--aceitos', arquivoAceitos);
  }
  const r = spawnSync(process.execPath, args, { encoding: 'utf8' });
  return { code: r.status ?? 1, saida: `${r.stdout ?? ''}${r.stderr ?? ''}` };
}

/** Uma exceção fictícia e vigente, no formato real da lista. */
const ACEITO_FICTICIO = [{
  id: 'GHSA-tttt-uuuu-vvvv',
  pacote: 'pacote-de-teste',
  motivo: 'Exceção de teste — não corresponde a nada real.',
  revisar_em: '2099-01-01',
}];

/** Relatório limpo mínimo, no formato real do `npm audit --json`. */
const LIMPO = {
  vulnerabilities: {},
  metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 0, critical: 0 } },
};

describe('audit-gate', () => {
  it('passa quando o relatório é válido e não há high/critical', () => {
    const { code, saida } = rodar(LIMPO);
    expect(code).toBe(0);
    expect(saida).toContain('Sem vulnerabilidades');
  });

  it('falha quando o registry devolve um erro em vez de um relatório', () => {
    // Este é EXATAMENTE o payload que passava verde.
    const { code, saida } = rodar({
      error: { code: 'ENETUNREACH', summary: 'request to registry failed', detail: '' },
    });
    expect(code).toBe(1);
    expect(saida).toContain('Não foi possível auditar');
    expect(saida).not.toContain('Sem vulnerabilidades');
  });

  it('falha quando falta a seção `vulnerabilities`', () => {
    const { code, saida } = rodar({ metadata: {} });
    expect(code).toBe(1);
    expect(saida).toContain('Não foi possível auditar');
  });

  it('falha quando faltam os contadores de metadata', () => {
    const { code } = rodar({ vulnerabilities: {} });
    expect(code).toBe(1);
  });

  it('falha quando a saída não é JSON', () => {
    const { code } = rodar('isto não é json');
    expect(code).toBe(1);
  });

  it('falha quando metadata discorda da varredura (formato mudou)', () => {
    const { code, saida } = rodar({
      vulnerabilities: {},
      metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 2, critical: 0 } },
    });
    expect(code).toBe(1);
    expect(saida).toContain('metadata');
  });

  it('falha numa high sem exceção registrada', () => {
    const { code, saida } = rodar({
      vulnerabilities: {
        'pacote-qualquer': {
          severity: 'high',
          via: [{ url: 'https://github.com/advisories/GHSA-aaaa-bbbb-cccc', title: 'RCE' }],
        },
      },
      metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 1, critical: 0 } },
    });
    expect(code).toBe(1);
    expect(saida).toContain('sem decisão registrada');
  });

  it('silencia a high que tem exceção vigente', () => {
    const { code, saida } = rodar({
      vulnerabilities: {
        'pacote-de-teste': {
          severity: 'high',
          via: [{ url: 'https://github.com/advisories/GHSA-tttt-uuuu-vvvv', title: 'CSRF' }],
        },
      },
      metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 1, critical: 0 } },
    }, ACEITO_FICTICIO);
    expect(code).toBe(0);
    expect(saida).toContain('GHSA-tttt-uuuu-vvvv');
  });

  it('avisa quando uma exceção não corresponde a nada no relatório', () => {
    const { code, saida } = rodar(LIMPO, ACEITO_FICTICIO);
    expect(code).toBe(0);
    expect(saida).toContain('não corresponde a nenhuma vulnerabilidade');
  });

  it('a lista de produção está vazia', () => {
    // Uma exceção que sobrevive à vulnerabilidade que a justificou é uma porta
    // destrancada de que ninguém lembra. Se este teste falhar, a entrada nova
    // precisa de `revisar_em` e de um motivo — e de sair assim que der.
    const { code, saida } = rodar(LIMPO);
    expect(code).toBe(0);
    expect(saida).toContain('0 aceita(s)');
  });
});
