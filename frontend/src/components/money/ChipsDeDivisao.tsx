import { Check } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

/**
 * "Dividir com" — as pílulas de quem participa do rateio.
 *
 * ## Por que ela mora aqui e não dentro do formulário de despesa
 *
 * Ela nasceu em `transaction-form/SimpleSplitChips`, amarrada ao
 * `useFormContext<TransactionFormValues>`. Quando a RECORRÊNCIA precisou da
 * mesma pergunta — e ela precisa: aluguel dividido em três é uma despesa fixa
 * por definição —, havia dois caminhos: copiar as pílulas ou separar o desenho
 * da amarração.
 *
 * Copiar teria funcionado e envelhecido mal: as duas telas fazem a MESMA
 * pergunta, e "dividir com" que se parece com duas coisas diferentes em dois
 * lugares é o tipo de inconsistência que a auditoria de experiência levantou em
 * quatro telas deste app.
 *
 * Então aqui está só o desenho — quem participa, quem alterna, quanto dá para
 * cada um. Cada formulário liga isso ao seu próprio estado: o de despesa pelo
 * `react-hook-form`, o de recorrência por um `useState`.
 *
 * ## O "≈ X cada"
 *
 * Ele só aparece com valor e gente escolhida, e é aproximado de propósito: a
 * divisão real é calculada no servidor, com o arredondamento de centavos que
 * fecha a soma. Prometer o número exato aqui seria discordar dele em um centavo
 * numa despesa ímpar dividida em três.
 */
export interface ParticipanteDaDivisao {
  id: string;
  name: string;
}

interface ChipsDeDivisaoProps {
  participantes: ParticipanteDaDivisao[];
  /** Ids marcados. */
  selecionados: string[];
  onAlternar: (id: string) => void;
  /** Total da despesa, para o "≈ X cada". Sem ele, a dica não aparece. */
  total?: number;
  formatar?: (valor: number) => string;
  rotulo?: string;
}

export function ChipsDeDivisao({
  participantes,
  selecionados,
  onAlternar,
  total = 0,
  formatar,
  rotulo = 'Dividir com',
}: ChipsDeDivisaoProps) {
  const marcados = new Set(selecionados);
  const quantos = marcados.size;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-semibold text-foreground">{rotulo}</Label>
        {quantos > 0 && total > 0 && formatar && (
          <span className="text-xs font-semibold text-muted-foreground">
            ≈ {formatar(total / quantos)} cada
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {participantes.map((p) => {
          const ativo = marcados.has(p.id);
          return (
            <button
              key={p.id}
              type="button"
              aria-pressed={ativo}
              aria-label={p.name}
              onClick={() => onAlternar(p.id)}
              className={cn(
                'inline-flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-sm font-semibold transition-colors',
                ativo
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border bg-background text-muted-foreground hover:border-primary/50',
              )}
            >
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold uppercase',
                  ativo ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                )}
              >
                {ativo ? <Check className="h-3.5 w-3.5" /> : p.name.slice(0, 2)}
              </span>
              {p.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
