import * as React from 'react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/*
 * DecimalInput — número com casas decimais como a pessoa escreve: "39,90",
 * "5,899", "1,235".
 *
 * ## Por que não o MoneyInput
 *
 * O `MoneyInput` é uma máscara de CENTAVOS: consome só dígitos e produz a vírgula
 * duas casas antes do fim. Serve para dinheiro, e não serve para o preço do litro
 * (R$ 5,899) nem para o peso da balança (1,235 kg): com a máscara, digitar
 * "5899" viraria R$ 58,99 (ADR 0040).
 *
 * ## Por que não o campo numérico do navegador
 *
 * Porque a vírgula dele depende do idioma do navegador — num Chrome em inglês,
 * "1,235" é recusado ou lido como mil duzentos e trinta e cinco. Aqui o texto é
 * da pessoa e a conversão é nossa: vírgula OU ponto são o separador decimal, e o
 * teclado do celular é o decimal (`inputMode="decimal"`), que tem a vírgula.
 *
 * ## As regras
 *
 * - Aceita dígitos e UM separador; a tecla que passaria de `casas` é ignorada —
 *   é o jeito de o campo dizer o limite sem mensagem de erro.
 * - Mesmo contrato do `NumberInput`: o texto digitado é estado local, o número é
 *   o que sai no `onChange`, e a normalização ("39,9" → "39,90") acontece ao SAIR
 *   do campo, nunca durante a digitação.
 */
interface DecimalInputProps
  extends Omit<React.ComponentProps<'input'>, 'onChange' | 'value' | 'type' | 'prefix'> {
  /** `null` = campo vazio. */
  value: number | null | undefined;
  onChange: (valor: number | null) => void;
  /** Máximo de casas aceitas (preço: 4; quantidade: 3). */
  casas: number;
  /** Casas completadas ao sair ("39,9" → "39,90"). Padrão: nenhuma. */
  casasMinimas?: number;
  /** Símbolo dentro do campo, como no MoneyInput ("R$"). */
  prefix?: string;
}

// Mesmos números do MoneyInput, para os dois campos da linha se alinharem.
const PREFIX_LEFT = 12;
const PREFIX_GAP = 6;
const PREFIX_MIN_PADDING = 36;

/** Número → texto do campo: vírgula, sem separador de milhar, entre as casas pedidas. */
function formatarDecimal(valor: number, casasMinimas: number, casas: number): string {
  return valor.toLocaleString('pt-BR', {
    minimumFractionDigits: casasMinimas,
    maximumFractionDigits: casas,
    useGrouping: false,
  });
}

/** Texto do campo → número (`null` para vazio ou inválido). */
function lerDecimal(texto: string): number | null {
  const limpo = texto.trim().replace(',', '.');
  if (limpo === '' || limpo === '.') return null;
  const numero = Number(limpo);
  return Number.isFinite(numero) ? numero : null;
}

const DecimalInput = React.forwardRef<HTMLInputElement, DecimalInputProps>(
  ({ value, onChange, casas, casasMinimas = 0, prefix, className, style, onBlur, onFocus, ...props }, ref) => {
    const paraTexto = React.useCallback(
      (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '' : formatarDecimal(v, casasMinimas, casas)),
      [casasMinimas, casas],
    );
    const [texto, setTexto] = React.useState(() => paraTexto(value));
    const temFoco = React.useRef(false);
    const prefixRef = React.useRef<HTMLSpanElement>(null);
    const [padding, setPadding] = React.useState(PREFIX_MIN_PADDING);

    React.useLayoutEffect(() => {
      if (!prefix) return;
      const largura = prefixRef.current?.offsetWidth ?? 0;
      setPadding(Math.max(PREFIX_MIN_PADDING, PREFIX_LEFT + largura + PREFIX_GAP));
    }, [prefix]);

    // Valor de fora (abrir para editar, resetar) reescreve o campo — mas só
    // quando o número diverge do digitado e ninguém está digitando nele.
    React.useEffect(() => {
      if (temFoco.current) return;
      if (lerDecimal(texto) === (value ?? null)) return;
      setTexto(paraTexto(value));
      // `texto` fora de propósito: ele muda a cada tecla (ver NumberInput).
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value, paraTexto]);

    const permitido = React.useMemo(() => new RegExp(`^\\d*([.,]\\d{0,${casas}})?$`), [casas]);

    const aoDigitar = (e: React.ChangeEvent<HTMLInputElement>) => {
      const bruto = e.target.value.trim();
      if (!permitido.test(bruto)) return;
      setTexto(bruto);
      onChange(lerDecimal(bruto));
    };

    const aoSair = (e: React.FocusEvent<HTMLInputElement>) => {
      temFoco.current = false;
      setTexto(paraTexto(lerDecimal(texto)));
      onBlur?.(e);
    };

    return (
      <div className="relative">
        {prefix && (
          <span
            ref={prefixRef}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground font-bold text-sm pointer-events-none"
          >
            {prefix}
          </span>
        )}
        <Input
          {...props}
          ref={ref}
          inputMode="decimal"
          autoComplete="off"
          value={texto}
          onChange={aoDigitar}
          onFocus={(e) => { temFoco.current = true; onFocus?.(e); }}
          onBlur={aoSair}
          className={cn(className)}
          style={prefix ? { ...style, paddingLeft: padding } : style}
        />
      </div>
    );
  },
);

DecimalInput.displayName = 'DecimalInput';

export { DecimalInput };
