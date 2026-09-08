import * as React from 'react';
import { Input } from '@/components/ui/input';

/*
 * NumberInput — campo de número inteiro que não guarda zero à esquerda.
 *
 * ## O defeito que ele existe para resolver
 *
 * O campo mostrava `0`, a pessoa digitava `5`, e ele passava a mostrar **`05`** —
 * e ficava assim. Acontecia em cinco campos de três telas (dia de fechamento e
 * de vencimento do cartão, número de parcelas do financiamento, dia do mês da
 * recorrência, quantidade do item). O valor enviado ao servidor estava certo; a
 * TELA é que mentia, e num app de dinheiro isso derruba a confiança no
 * formulário inteiro.
 *
 * ## Por que acontecia
 *
 * Para `<input type="number">` controlado, o React decide se reescreve o DOM com
 * uma comparação FROUXA:
 *
 *     if (node.value != value) node.value = toString(value);   // != , não !==
 *
 * Com `node.value === "05"` e `value === 5`, `"05" == 5` é **verdadeiro** em
 * JavaScript — a condição dá falso e o React não reescreve nada. O estado vira
 * 5, a tela continua com `05`, e não há novo render que corrija, porque o número
 * não muda mais.
 *
 * A prova estava na própria base: os sete campos numéricos da Administração
 * eram os únicos sem o defeito, e os únicos que renderizavam `value={String(…)}`
 * — com string, a comparação é `"05" !== "5"` e o React reescreve.
 *
 * ## Por que um componente, e não `String(value)` em cada lugar
 *
 * Porque `String(value)` resolve o zero à esquerda e cria outro problema: ele
 * reescreve o campo a CADA tecla, e aí não dá para apagar o conteúdo para
 * redigitar. Era o segundo sintoma da mesma família, e ele já existia nos campos
 * com fallback (`|| 5`, `Math.max(1, … || 1)`): digitar `0` fazia o valor saltar
 * para 5 ou para 1 no meio da digitação.
 *
 * A regra que resolve os dois é a mesma que o `MoneyInput` já usa para dinheiro:
 * **o texto digitado é estado local; o número é o que sai no `onChange`; a
 * normalização acontece no `blur`.** Enquanto a pessoa digita, o campo é dela.
 */
interface NumberInputProps
  extends Omit<React.ComponentProps<'input'>, 'onChange' | 'value' | 'min' | 'max' | 'type'> {
  /** `null` = campo vazio. É um estado legítimo DURANTE a digitação. */
  value: number | null | undefined;
  onChange: (valor: number | null) => void;
  min?: number;
  max?: number;
  /** Valor aplicado no `blur` quando o campo fica vazio. Sem isto, vazio continua vazio. */
  padraoAoSair?: number;
}

const NumberInput = React.forwardRef<HTMLInputElement, NumberInputProps>(
  ({ value, onChange, min, max, padraoAoSair, onBlur, ...props }, ref) => {
    const [texto, setTexto] = React.useState(() => (value == null ? '' : String(value)));

    /*
     * Sincroniza com o valor de fora — mas SÓ quando ele diverge numericamente
     * do que está digitado.
     *
     * Esta condição é o coração do componente. Se o texto é "05" e o valor é 5,
     * os dois concordam sobre o número e o campo NÃO é reescrito: a pessoa está
     * no meio da digitação e mexer no que ela escreveu move o cursor. A limpeza
     * do "05" fica para o `blur`, abaixo.
     *
     * Quando alguém de fora troca o valor de verdade (abrir um formulário de
     * edição, resetar), aí os números divergem e o campo é reescrito — que é o
     * comportamento de um campo controlado.
     */
    const temFoco = React.useRef(false);
    React.useEffect(() => {
      // Com o campo em FOCO, o texto é da pessoa — ponto.
      //
      // Sem esta linha, um pai que não sabe representar "vazio" (e são vários:
      // `day_of_month` é `number`, não `number | null`) coage o `null` para o
      // mínimo no mesmo instante, o valor volta diferente do texto, e o efeito
      // reescreve o campo. Na prática: apagar o conteúdo para redigitar era
      // impossível, porque o "1" reaparecia a cada tecla. A coerção do pai
      // continua valendo — ela só passa a ser aplicada na saída, junto com o
      // resto da normalização.
      if (temFoco.current) return;
      const numeroDigitado = texto.trim() === '' ? null : Number(texto);
      if (numeroDigitado === value) return;
      if (numeroDigitado != null && Number.isNaN(numeroDigitado)) return;
      setTexto(value == null ? '' : String(value));
      // `texto` fora das dependências de propósito: ele muda a cada tecla, e
      // incluí-lo faria este efeito rodar durante a digitação — exatamente o que
      // ele existe para não fazer.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value]);

    const aoDigitar = (e: React.ChangeEvent<HTMLInputElement>) => {
      const bruto = e.target.value;
      // Só dígitos (e o vazio). `type="number"` está fora pelo mesmo motivo do
      // `MoneyInput`: a comparação frouxa do React é dele, e o teclado numérico
      // do celular já vem do `inputMode`.
      if (bruto !== '' && !/^\d+$/.test(bruto)) return;
      setTexto(bruto);
      onChange(bruto === '' ? null : Number(bruto));
    };

    /**
     * A normalização — e ela acontece aqui, ao SAIR do campo, não a cada tecla.
     *
     * É o que apaga o zero à esquerda ("05" → "5"), aplica o mínimo e o máximo,
     * e preenche o padrão quando a pessoa deixou vazio. Fazer isso durante a
     * digitação é o que impedia de apagar o campo e de digitar um número que
     * comece por zero.
     */
    const aoSair = (e: React.FocusEvent<HTMLInputElement>) => {
      temFoco.current = false;
      let numero = texto.trim() === '' ? null : Number(texto);
      if (numero == null && padraoAoSair !== undefined) numero = padraoAoSair;
      if (numero != null) {
        if (min !== undefined) numero = Math.max(min, numero);
        if (max !== undefined) numero = Math.min(max, numero);
      }
      setTexto(numero == null ? '' : String(numero));
      if (numero !== value) onChange(numero);
      onBlur?.(e);
    };

    return (
      <Input
        {...props}
        ref={ref}
        inputMode="numeric"
        value={texto}
        onChange={aoDigitar}
        onFocus={(e) => { temFoco.current = true; props.onFocus?.(e); }}
        onBlur={aoSair}
      />
    );
  },
);

NumberInput.displayName = 'NumberInput';

export { NumberInput };
