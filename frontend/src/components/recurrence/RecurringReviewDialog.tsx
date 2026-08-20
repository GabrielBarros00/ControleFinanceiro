import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { StatusPill, type PillTone } from '@/components/ui/status-pill';
import { nativeSelectClass } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { formatMoney } from '@/lib/money';
import { parseApiDay } from '@/lib/date';
import type { RecurringPlanItem } from '@/hooks/use-recurring';

/**
 * Revisão da edição de recorrência (ADR 0030).
 *
 * O que ela substitui: um `<select>` "Aplicar alterações a" no rodapé de um
 * modal longo, sem contagem, sem lista, e que **não movia a data** — mudar "todo
 * dia 5" para "todo dia 20" deixava os lançamentos já criados no dia 5 para
 * sempre. Excluir ou desativar o template não tocava em nada.
 *
 * Aqui a pessoa vê exatamente o que vai acontecer com cada lançamento, escolhe
 * a partir de quando, e marca linha a linha. Nada é aplicado sem estar marcado:
 * um default "aplica tudo" traria de volta a ação invisível que este diálogo
 * veio remover.
 *
 * A lista vem do servidor (`POST .../preview`), da MESMA função que executa a
 * escrita — é isso que impede a tela de prometer uma coisa e o servidor fazer
 * outra.
 */

export type ReviewAction = 'update' | 'deactivate' | 'delete';

interface RecurringReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  action: ReviewAction;
  items: RecurringPlanItem[];
  isLoading: boolean;
  /** Refaz o preview quando a pessoa muda o "aplicar a partir de". */
  onSinceChange: (since: string) => void;
  since: string;
  onConfirm: (escolha: { applyTo: number[]; createOccurrences: string[] }) => Promise<void>;
  isSaving?: boolean;
}

const ACAO: Record<string, { rotulo: string; tom: PillTone }> = {
  move: { rotulo: 'muda de data', tom: 'brand' },
  update: { rotulo: 'atualiza', tom: 'neutral' },
  cancel: { rotulo: 'cancela', tom: 'danger' },
  create: { rotulo: 'cria', tom: 'success' },
  none: { rotulo: 'não muda', tom: 'neutral' },
};

const TITULO: Record<ReviewAction, string> = {
  update: 'Aplicar a quais lançamentos?',
  deactivate: 'Desativar — e os lançamentos já criados?',
  delete: 'Excluir — e os lançamentos já criados?',
};

const DESCRICAO: Record<ReviewAction, string> = {
  update:
    'A alteração do modelo já vale para os próximos meses. Escolha o que fazer com os lançamentos que já existem.',
  deactivate:
    'O modelo para de gerar novos lançamentos. Os que já foram criados continuam onde estão, a menos que você os cancele aqui.',
  delete:
    'O modelo será excluído. Os lançamentos que já foram criados continuam onde estão, a menos que você os cancele aqui.',
};

/** Uma linha só é escolhível se de fato houver algo a fazer com ela. */
const acionavel = (item: RecurringPlanItem) => item.action !== 'none';

/** Chave estável de uma linha — as de `create` ainda não têm id. */
const chaveDe = (item: RecurringPlanItem) =>
  item.transaction_id != null ? `tx-${item.transaction_id}` : `new-${item.occurrence_date}`;

const dia = (iso: string) => parseApiDay(iso).toLocaleDateString('pt-BR');

export function RecurringReviewDialog({
  open,
  onOpenChange,
  action,
  items,
  isLoading,
  onSinceChange,
  since,
  onConfirm,
  isSaving = false,
}: RecurringReviewDialogProps) {
  const [marcadas, setMarcadas] = React.useState<Set<string>>(new Set());

  // Toda linha acionável começa MARCADA. Não contradiz o "nada sem escolha": o
  // opt-in é o diálogo inteiro — ele só fecha por Confirmar ou Cancelar. Vir
  // tudo desmarcado obrigaria a marcar doze meses um a um para o caso comum
  // ("sim, aplique"), e a tela viraria trabalho em vez de conferência.
  React.useEffect(() => {
    setMarcadas(new Set(items.filter(acionavel).map(chaveDe)));
  }, [items]);

  const alterna = (chave: string) =>
    setMarcadas((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(chave)) proximo.delete(chave);
      else proximo.add(chave);
      return proximo;
    });

  const escolhidos = items.filter((i) => marcadas.has(chaveDe(i)));
  const contagem = escolhidos.reduce<Record<string, number>>((acc, i) => {
    acc[i.action] = (acc[i.action] ?? 0) + 1;
    return acc;
  }, {});
  const congeladas = items.filter((i) => i.frozen_reason);

  const confirmar = () =>
    onConfirm({
      applyTo: escolhidos
        .filter((i) => i.transaction_id != null)
        .map((i) => i.transaction_id as number),
      createOccurrences: escolhidos
        .filter((i) => i.transaction_id == null)
        .map((i) => i.occurrence_date),
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto bg-card border-border sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{TITULO[action]}</DialogTitle>
          <DialogDescription>{DESCRICAO[action]}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="review-since">Aplicar a partir de</Label>
            <input
              id="review-since"
              type="month"
              value={since.slice(0, 7)}
              onChange={(e) => onSinceChange(`${e.target.value}-01`)}
              className={nativeSelectClass}
            />
            <p className="text-[11px] text-muted-foreground">
              Meses anteriores a este ficam de fora da lista.
            </p>
          </div>

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <p className="rounded-lg border border-border bg-accent/20 p-4 text-center text-sm text-muted-foreground">
              Nenhum lançamento a ajustar neste período.
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {items.map((item) => {
                const chave = chaveDe(item);
                const podeEscolher = acionavel(item);
                const info = ACAO[item.action] ?? ACAO.none;
                const destino = item.new_occurrence_date;
                return (
                  <li key={chave} className="flex items-start gap-3 p-3">
                    <input
                      type="checkbox"
                      id={`rev-${chave}`}
                      checked={marcadas.has(chave)}
                      disabled={!podeEscolher}
                      onChange={() => alterna(chave)}
                      className="mt-0.5 h-5 w-5 shrink-0 rounded border-border accent-primary disabled:opacity-40"
                    />
                    <label
                      htmlFor={`rev-${chave}`}
                      className={`min-w-0 flex-1 ${podeEscolher ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}
                    >
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm font-medium text-foreground">
                          {dia(item.occurrence_date)}
                          {destino && ` → ${dia(destino)}`}
                        </span>
                        <StatusPill tone={info.tom}>{info.rotulo}</StatusPill>
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {item.frozen_reason ?? descreveMudancas(item)}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}

          {congeladas.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              {congeladas.length} lançamento(s) já pago(s) ou cancelado(s) não serão alterados.
            </p>
          )}
        </div>

        <DialogFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">{resumo(contagem)}</p>
          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="button" onClick={confirmar} pending={isSaving} className="font-bold">
              Confirmar
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** "R$ 1.000,00 → R$ 1.200,00 · Aluguel → Aluguel novo" */
function descreveMudancas(item: RecurringPlanItem): string {
  const mudancas = (item.changes ?? {}) as Record<
    string,
    { from?: string | null; to?: string | null }
  >;
  const partes: string[] = [];
  const valor = mudancas.amount;
  if (valor?.from != null && valor?.to != null) {
    partes.push(`${formatMoney(Number(valor.from))} → ${formatMoney(Number(valor.to))}`);
  }
  const titulo = mudancas.title;
  if (titulo?.from != null && titulo?.to != null) {
    partes.push(`${titulo.from} → ${titulo.to}`);
  }
  if (partes.length > 0) return partes.join(' · ');
  if (item.action === 'create') {
    return item.amount != null
      ? `Novo lançamento de ${formatMoney(Number(item.amount))}`
      : 'Novo lançamento';
  }
  if (item.action === 'cancel') return 'Sai dos totais do mês';
  // Divisão, categoria e forma de pagamento acompanham sempre — listá-las campo
  // a campo transformaria a revisão numa tabela de diferenças.
  return 'Valor, divisão e categoria acompanham o modelo';
}

function resumo(contagem: Record<string, number>): string {
  const ordem: [string, string][] = [
    ['move', 'muda(m) de data'],
    ['update', 'atualizado(s)'],
    ['cancel', 'cancelado(s)'],
    ['create', 'criado(s)'],
  ];
  const partes = ordem
    .filter(([chave]) => (contagem[chave] ?? 0) > 0)
    .map(([chave, rotulo]) => `${contagem[chave]} ${rotulo}`);
  return partes.length > 0 ? partes.join(' · ') : 'Nada selecionado';
}
