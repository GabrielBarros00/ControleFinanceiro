import * as React from 'react';
import { useSearchParams } from 'react-router-dom';

/*
 * Aba selecionada vivendo na URL, não em `useState`.
 *
 * Mesma razão do `use-month-param.ts`: sem isso a aba some no reload e no botão
 * voltar, e não há como mandar a alguém "olha a tua parte de agosto" — o link
 * cairia sempre no Resumo. Em Acertos isso pesa mais que nas outras telas com
 * aba, porque o `?month=` já mora na URL e as duas coisas juntas é que
 * identificam o que está na tela.
 *
 * `replace: true` pelo mesmo motivo de lá: trocar de aba é ajuste de
 * visualização, não navegação — com `push`, sair da tela exigiria um "voltar"
 * por aba visitada.
 */
export function useTabParam<T extends string>(
  validos: readonly T[],
  padrao: T,
  paramName = 'tab',
): [T, (aba: T) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const bruto = searchParams.get(paramName) as T | null;
  // Valor inventado à mão na URL cai no padrão, em vez de renderizar aba
  // nenhuma — o Radix simplesmente não casa nenhum `TabsContent` e a tela fica
  // em branco, sem erro em log nenhum.
  const aba = bruto && validos.includes(bruto) ? bruto : padrao;

  const setAba = React.useCallback(
    (nova: T) => {
      setSearchParams(
        (anterior) => {
          const proximo = new URLSearchParams(anterior);
          proximo.set(paramName, nova);
          return proximo;
        },
        { replace: true },
      );
    },
    [paramName, setSearchParams],
  );

  return [aba, setAba];
}
