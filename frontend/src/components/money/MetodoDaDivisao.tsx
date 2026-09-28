import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { DecimalInput } from '@/components/ui/DecimalInput';
import type { ParticipanteDaDivisao } from './ChipsDeDivisao';

export type MetodoDeDivisao = 'equal' | 'percentage' | 'fixed';

const ROTULO: Record<MetodoDeDivisao, string> = {
  equal: 'Igual',
  percentage: 'Porcentagem',
  fixed: 'Valor fixo',
};

interface MetodoDaDivisaoProps {
  /** Só quem está na divisão (os marcados nas pílulas). */
  participantes: ParticipanteDaDivisao[];
  metodo: MetodoDeDivisao;
  onMetodo: (metodo: MetodoDeDivisao) => void;
  /** Percentual ou valor de cada um, por id. Ignorado na divisão igual. */
  valores: Record<string, number>;
  onValor: (id: string, valor: number) => void;
  /** Símbolo da moeda, para o valor fixo. */
  simbolo: string;
  /** A soma que não fecha, já em texto (vem da validação do formulário). */
  erro?: string;
  idPrefix: string;
}

/**
 * COMO dividir, depois do "com quem" das pílulas: igual, por porcentagem ou por
 * valor fixo.
 *
 * Nasceu para a despesa recorrente, que só sabia dividir igual. O contrato
 * sempre aceitou os três métodos, e o agente de IA os grava ("aluguel, 60% meu
 * e 40% do João"); a tela, sem saber mostrá-los, reenviava tudo como partes
 * iguais a cada edição — e a divisão 60/40 virava 50/50 sem ninguém pedir.
 */
export function MetodoDaDivisao({
  participantes, metodo, onMetodo, valores, onValor, simbolo, erro, idPrefix,
}: MetodoDaDivisaoProps) {
  return (
    <div className="space-y-3" data-testid={`${idPrefix}-metodo-divisao`}>
      <RadioGroup
        value={metodo}
        onValueChange={(v) => onMetodo(v as MetodoDeDivisao)}
        className="flex flex-wrap gap-x-5 gap-y-2"
        aria-label="Como dividir"
      >
        {(Object.keys(ROTULO) as MetodoDeDivisao[]).map((m) => (
          <div key={m} className="flex items-center gap-2">
            <RadioGroupItem value={m} id={`${idPrefix}-metodo-${m}`} className="border-primary text-primary" />
            <Label htmlFor={`${idPrefix}-metodo-${m}`} className="cursor-pointer text-sm font-medium">{ROTULO[m]}</Label>
          </div>
        ))}
      </RadioGroup>

      {metodo !== 'equal' && (
        <div className="space-y-2">
          {participantes.map((p) => (
            <div key={p.id} className="flex items-center gap-3">
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">{p.name}</span>
              <div className="w-36 shrink-0">
                {metodo === 'percentage' ? (
                  <div className="flex items-center gap-1.5">
                    <DecimalInput
                      aria-label={`Percentual de ${p.name}`}
                      casas={2}
                      value={valores[p.id] ?? null}
                      onChange={(v) => onValor(p.id, v ?? 0)}
                      className="bg-background/50"
                    />
                    <span className="text-sm text-muted-foreground">%</span>
                  </div>
                ) : (
                  <MoneyInput
                    aria-label={`Valor de ${p.name}`}
                    value={valores[p.id] ?? 0}
                    onChange={(v) => onValor(p.id, v)}
                    prefix={simbolo}
                    className="bg-background/50"
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {erro && <p className="text-xs font-medium text-destructive">{erro}</p>}
    </div>
  );
}
