import { renderHook, act } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import React from 'react';
import { useMonthParam } from '../use-month-param';
import { currentMonthLocal } from '@/lib/date';

/*
 * O mês vive na URL, não em estado local: sem isso ele sumia no reload e no
 * botão voltar, e não havia como compartilhar "as minhas dívidas de maio".
 */
function wrapper(entries: string[]) {
  return ({ children }: { children: React.ReactNode }) => (
    <MemoryRouter initialEntries={entries}>{children}</MemoryRouter>
  );
}

describe('useMonthParam', () => {
  it('lê o mês da query string', () => {
    const { result } = renderHook(() => useMonthParam(), {
      wrapper: wrapper(['/transactions?month=2026-05']),
    });
    expect(result.current[0]).toBe('2026-05');
  });

  it('sem parâmetro, cai no mês corrente LOCAL', () => {
    const { result } = renderHook(() => useMonthParam(), {
      wrapper: wrapper(['/transactions']),
    });
    // currentMonthLocal, não toISOString: em fuso negativo o mês em UTC já é o
    // seguinte depois das 21h do último dia
    expect(result.current[0]).toBe(currentMonthLocal());
  });

  it.each(['2026-13', '2026-00', 'abril', '2026', ''])(
    'mês malformado na URL (%s) cai no corrente em vez de ir para a API',
    (bruto) => {
      const { result } = renderHook(() => useMonthParam(), {
        wrapper: wrapper([`/transactions?month=${bruto}`]),
      });
      expect(result.current[0]).toBe(currentMonthLocal());
    },
  );

  it('escrever o mês atualiza a URL e preserva os outros parâmetros', () => {
    const { result } = renderHook(
      () => ({ mes: useMonthParam(), loc: useLocation() }),
      { wrapper: wrapper(['/transactions?month=2026-05&tab=itens']) },
    );

    act(() => result.current.mes[1]('2026-06'));

    expect(result.current.mes[0]).toBe('2026-06');
    const params = new URLSearchParams(result.current.loc.search);
    expect(params.get('month')).toBe('2026-06');
    expect(params.get('tab')).toBe('itens');
  });
});
