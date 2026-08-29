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
import { Textarea } from "@/components/ui/textarea";
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { AlertCircle, HandCoins } from 'lucide-react';
import { getApiErrorMessage } from '@/lib/api-error';
import { useSettlements } from '@/hooks/use-settlements';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { currencySymbol } from '@/lib/money';
import { monthLabel } from '@/lib/date';
import type { Member } from '@/hooks/use-members';
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';

export interface SettlementDraft {
  from_user_id: number;
  to_user_id: number;
  amount: number;
  // Quando o acerto vem do ledger mensal, quita a dívida daquele mês (YYYY-MM)
  billing_month?: string;
  // Preenchidos pela tela GLOBAL (ADR 0027), onde a casa não vem da URL e sim da
  // linha clicada. Vazios na tela da casa, que continua lendo o workspace da URL.
  workspace_id?: number;
  workspace_name?: string;
  currency?: string;
}

interface SettlementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: SettlementDraft | null;
  /** Só precisa de `user_id` e `user_name`: na tela global as pessoas vêm do
   *  `people` de cada casa, não de `/{ws}/members`. */
  members: Pick<Member, 'user_id' | 'user_name'>[];
}

// Registrar um acerto: from pagou amount para to (desconta do balanço)
export function SettlementDialog({ open, onOpenChange, draft, members }: SettlementDialogProps) {
  // A casa do DRAFT vence a da URL: na tela global não há workspace na URL, e o
  // acerto pertence à casa da linha em que a pessoa clicou. `undefined` (tela da
  // casa) mantém o comportamento de sempre — ver `useSettlements`.
  const { create, isMutating } = useSettlements(draft?.workspace_id, { list: false });
  const workspaceCurrency = useBaseCurrency();
  const baseCurrency = draft?.currency ?? workspaceCurrency;
  const [fromId, setFromId] = React.useState('');
  const [toId, setToId] = React.useState('');
  const [amount, setAmount] = React.useState(0);
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open && draft) {
      setFromId(String(draft.from_user_id));
      setToId(String(draft.to_user_id));
      setAmount(draft.amount);
      setNote('');
      setError(null);
    }
  }, [open, draft]);

  const submit = async () => {
    setError(null);
    if (!fromId || !toId) {
      setError('Selecione quem pagou e quem recebeu.');
      return;
    }
    if (fromId === toId) {
      setError('Pagador e recebedor devem ser pessoas diferentes.');
      return;
    }
    if (amount <= 0) {
      setError('Informe um valor maior que zero.');
      return;
    }
    try {
      await create({
        from_user_id: Number(fromId),
        to_user_id: Number(toId),
        amount,
        note: note.trim() || undefined,
        billing_month: draft?.billing_month,
      });
      onOpenChange(false);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao registrar o acerto.'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px] bg-card border-border shadow-2xl">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold flex items-center gap-2">
            <HandCoins className="h-5 w-5 text-primary" /> Registrar pagamento
          </DialogTitle>
          <DialogDescription>
            {draft?.workspace_name
              // Na tela global há várias casas na mesma página: dizer em qual o
              // acerto vai cair é o que impede o registro na casa errada.
              ? `O valor é abatido do balanço de ${draft.workspace_name}.`
              : 'O valor registrado é abatido do balanço de dívidas deste espaço.'}{' '}
            {/* Os dois tipos de acerto (ADR 0009): o que FECHA um mês e o que só
                abate o acumulado. A distinção estava escrita na tela de Acertos,
                mas não aqui — onde a escolha realmente acontece —, e o histórico
                depois marcava um "jul/2026" e outro "sem mês" sem que se pudesse
                saber onde aquilo tinha sido decidido. */}
            {draft?.billing_month
              ? `Fecha o mês de ${monthLabel(draft.billing_month)}.`
              : 'Abate o saldo acumulado, sem fechar mês nenhum.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="settlement-from" className="text-sm font-semibold">Quem pagou</Label>
              <select id="settlement-from" className={selectClass} value={fromId} onChange={(e) => setFromId(e.target.value)}>
                <option value="">Selecione...</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>{m.user_name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="settlement-to" className="text-sm font-semibold">Quem recebeu</Label>
              <select id="settlement-to" className={selectClass} value={toId} onChange={(e) => setToId(e.target.value)}>
                <option value="">Selecione...</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>{m.user_name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="settlement-amount" className="text-sm font-semibold">Valor</Label>
            <MoneyInput id="settlement-amount" value={amount} onChange={setAmount} prefix={currencySymbol(baseCurrency)} className="font-bold" />
          </div>

          <div className="space-y-2">
            <Label htmlFor="settlement-note" className="text-sm font-semibold">Observação (opcional)</Label>
            <Textarea
              id="settlement-note"
              rows={2}
              placeholder="Ex: Pix em 18/07"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>

          {error && (
            <p role="alert" className="flex items-center gap-2 text-sm text-destructive font-medium">
              <AlertCircle className="h-4 w-4 shrink-0" /> {error}
            </p>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="button" onClick={submit} disabled={isMutating} className="bg-primary text-primary-foreground font-bold">
            Registrar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
