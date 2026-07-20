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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { AlertCircle, HandCoins } from 'lucide-react';
import { getApiErrorMessage } from '@/lib/api-error';
import { useSettlements } from '@/hooks/use-settlements';
import type { Member } from '@/hooks/use-members';

const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

export interface SettlementDraft {
  from_user_id: number;
  to_user_id: number;
  amount: number;
}

interface SettlementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: SettlementDraft | null;
  members: Member[];
}

// Registrar um acerto: from pagou amount para to (desconta do balanço)
export function SettlementDialog({ open, onOpenChange, draft, members }: SettlementDialogProps) {
  const { create, isMutating } = useSettlements();
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
            O valor registrado é abatido do balanço de dívidas do workspace.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="grid grid-cols-2 gap-4">
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
            <MoneyInput id="settlement-amount" value={amount} onChange={setAmount} className="font-bold" />
          </div>

          <div className="space-y-2">
            <Label htmlFor="settlement-note" className="text-sm font-semibold">Observação (opcional)</Label>
            <Input
              id="settlement-note"
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
