import { describe, expect, it } from 'vitest';
import { linhaFecha, totalDaLinha } from '../item-da-nota';

/*
 * A MESMA tabela e a MESMA varredura de `backend/tests/domain/test_item_da_nota.py`:
 * a tela e o servidor têm de concordar em toda leitura, ou a pessoa preenche uma
 * linha que a tela aceita e o servidor recusa — foi o caso de 2,050 × R$ 19,90.
 */

describe('linha da nota (ADR 0040)', () => {
  it.each([
    [1.235, 39.9, 49.28],
    [1.235, 39.9, 49.27],
    [2.05, 19.9, 40.8],
    [2.05, 19.9, 40.79],
    [40.123, 5.899, 236.69],
    [40.123, 5.899, 236.68],
    [2, 25, 50],
    [2, 25, 50.01],
  ])('%s × %s = %s é uma leitura honesta', (q, u, t) => {
    expect(linhaFecha(q, u, t)).toBe(true);
  });

  it.each([
    [1.235, 39.9, 49.4],
    [12.35, 39.9, 49.28],
    [2, 25, 50.02],
  ])('%s × %s = %s é leitura errada', (q, u, t) => {
    expect(linhaFecha(q, u, t)).toBe(false);
  });

  it('o total derivado arredonda ao centavo sem erro de ponto flutuante', () => {
    // 2.05 * 1990 = 4079.4999… em float: a conta antiga dava R$ 40,79.
    expect(totalDaLinha(2.05, 19.9)).toBe(40.8);
    expect(totalDaLinha(40.123, 5.899)).toBe(236.69);
    expect(totalDaLinha(1.235, 39.9)).toBe(49.28);
  });

  it('qualquer balança passa na varredura (arredondando e truncando)', () => {
    const precos = [0.99, 1.99, 3.99, 5.99, 7.99, 12.99, 19.9, 24.9, 29.99, 39.9, 45.9, 59.99, 89.9, 99.99];
    const recusas: string[] = [];
    for (let mil = 1; mil <= 5000; mil++) {
      const q = mil / 1000;
      for (const p of precos) {
        const centavosExatos = mil * Math.round(p * 100); // em milésimos de centavo
        const arredondado = Math.floor((centavosExatos + 500) / 1000) / 100;
        const truncado = Math.floor(centavosExatos / 1000) / 100;
        for (const t of [arredondado, truncado]) {
          if (!linhaFecha(q, p, t)) recusas.push(`${q} × ${p} = ${t}`);
        }
        // E o derivado é sempre o arredondado.
        if (totalDaLinha(q, p) !== arredondado) recusas.push(`derivado ${q} × ${p}`);
      }
    }
    expect(recusas).toEqual([]);
  });
});
