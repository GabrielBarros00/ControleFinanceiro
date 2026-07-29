import * as React from 'react';
import { useSearchParams } from 'react-router-dom';
import { currentMonthLocal } from '@/lib/date';

/*
 * Mês selecionado (`YYYY-MM`) vivendo na URL, não em estado local.
 *
 * Antes cada tela guardava o mês num `useState`: ele sumia no reload e no botão
 * voltar, e não havia como compartilhar ou favoritar "as minhas dívidas de maio".
 * O `ProtectedRoute` chega a preservar `location.search` para voltar à rota certa
 * depois do login, citando `/transactions?month=2026-05` — um parâmetro que nada
 * escrevia.
 *
 * `replace: true` de propósito: navegar entre meses é ajuste de visualização, não
 * navegação. Com `push`, sair da tela exigiria um "voltar" por mês visitado.
 */
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

export function useMonthParam(
  paramName = 'month',
): [string, (month: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const bruto = searchParams.get(paramName);
  // Mês malformado na URL (link editado à mão) cai no mês corrente em vez de
  // propagar "2026-13" para a API e render um 400 sem explicação na tela.
  const month = bruto && MONTH_RE.test(bruto) ? bruto : currentMonthLocal();

  const setMonth = React.useCallback(
    (novo: string) => {
      setSearchParams(
        (anterior) => {
          const proximo = new URLSearchParams(anterior);
          proximo.set(paramName, novo);
          return proximo;
        },
        { replace: true },
      );
    },
    [paramName, setSearchParams],
  );

  return [month, setMonth];
}
