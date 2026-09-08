import type { FocusEvent } from 'react';

/**
 * Normaliza o número ao SAIR do campo, para os campos do react-hook-form.
 *
 * ## O defeito
 *
 * "Qtd" e os campos de porcentagem usam `register(..., { valueAsNumber: true })`,
 * o que os deixa **não controlados**: o RHF lê o valor e converte, mas nunca
 * reescreve o `<input>`. Consequência medida — digitar `5` num campo que
 * mostrava `0` deixava **`05`** na tela para sempre, mesmo com o formulário
 * guardando 5 corretamente. É o mesmo sintoma que o `ui/NumberInput` resolve
 * para os campos controlados, por um caminho diferente.
 *
 * ## Por que no blur
 *
 * Pelo mesmo motivo do `NumberInput`: normalizar a cada tecla impede de apagar o
 * campo para redigitar, e impede de digitar um número que comece por zero. O
 * texto pertence a quem digita enquanto o campo está em uso.
 *
 * ## Por que num arquivo próprio
 *
 * Porque o `ItemsEditor` e o `SplitEditor` precisam da mesma função, e exportar
 * um utilitário de um módulo de componente quebra o fast refresh do Vite (regra
 * `react-refresh/only-export-components`).
 *
 * `Number.isFinite` guarda contra `"1e999"` e afins; o retorno antecipado quando
 * o texto já é a forma canônica evita um `setValue` por blur em todo campo
 * intocado — que dispararia validação sem motivo.
 */
export function normalizarAoSair<N extends string>(
  // Genérico no NOME do campo: o `UseFormSetValue` do react-hook-form aceita só
  // os caminhos válidos do formulário (`items.0.quantity`, `splits.1.value`…),
  // e um `string` cru não é atribuível a essa união. Deixar o tipo do nome ser
  // inferido de quem chama mantém a checagem de caminho intacta em vez de
  // afrouxá-la com um `as`.
  setValue: (nome: N, valor: number, opcoes?: { shouldValidate?: boolean }) => void,
  nome: N,
) {
  return (e: FocusEvent<HTMLInputElement>) => {
    const bruto = e.target.value;
    if (bruto === '') return;
    const numero = Number(bruto);
    if (!Number.isFinite(numero)) return;
    if (String(numero) === bruto) return;
    setValue(nome, numero, { shouldValidate: true });
  };
}
