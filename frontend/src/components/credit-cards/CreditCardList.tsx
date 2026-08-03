import * as React from 'react';
import { CreditCard as CardIcon, Loader2, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { EmptyState } from '@/components/ui/empty-state';
import { CreditCardVisual } from './CreditCardVisual';
import { useCreditCards, type CardNextDue } from '@/hooks/use-credit-cards';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { currencySymbol } from '@/lib/money';
import { statementAlert } from '@/lib/statement-alert';
import { parseApiDay } from '@/lib/date';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';

interface CreditCardListProps {
  selectedCardId?: number | null;
  onSelectCard?: (id: number) => void;
}

interface CardRow {
  id: number;
  name: string;
  limit: string;
  closing_day: number;
  due_day: number;
  committed_amount: string;
  available_limit: string;
  next_due: CardNextDue | null;
}

// dd/mm do vencimento da fatura em aberto (o dia REAL, não o dia do ciclo)
const dueLabelOf = (next: CardNextDue | null) =>
  next
    ? parseApiDay(next.due_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
    : null;

export function CreditCardList({ selectedCardId, onSelectCard }: CreditCardListProps) {
  const { cards, isLoading, create, update, remove } = useCreditCards();
  const baseCurrency = useBaseCurrency();
  const confirm = useConfirm();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [name, setName] = React.useState('');
  const [limit, setLimit] = React.useState(0);
  const [closingDay, setClosingDay] = React.useState(1);
  const [dueDay, setDueDay] = React.useState(10);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Auto-seleciona o primeiro cartão (mata o "Selecione um cartão acima" — H6)
  React.useEffect(() => {
    if (!selectedCardId && cards.length > 0) onSelectCard?.((cards[0] as CardRow).id);
  }, [cards, selectedCardId, onSelectCard]);

  const resetForm = () => {
    setName('');
    setLimit(0);
    setClosingDay(1);
    setDueDay(10);
    setError(null);
  };

  const openCreate = () => {
    setEditingId(null);
    resetForm();
    setDialogOpen(true);
  };

  const openEdit = (card: CardRow) => {
    setEditingId(card.id);
    setName(card.name);
    setLimit(parseFloat(card.limit));
    setClosingDay(card.closing_day);
    setDueDay(card.due_day);
    setError(null);
    setDialogOpen(true);
  };

  const handleSubmit = async () => {
    if (!name.trim() || limit <= 0) {
      setError('Preencha nome e limite do cartão.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const data = { name: name.trim(), limit, closing_day: closingDay, due_day: dueDay };
      if (editingId != null) {
        await update({ id: editingId, data });
      } else {
        await create(data);
      }
      setDialogOpen(false);
      setEditingId(null);
      resetForm();
    } catch {
      setError(editingId != null ? 'Erro ao salvar cartão.' : 'Erro ao criar cartão.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (card: CardRow) => {
    const ok = await confirm({
      title: 'Excluir cartão',
      description: `Excluir o cartão ${card.name}?`,
      confirmLabel: 'Excluir',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(card.id);
    } catch {
      toast.error('Erro ao excluir cartão.');
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Meus cartões</h2>
        <Button onClick={openCreate} className="gap-2">
          <Plus className="h-4 w-4" /> Novo cartão
        </Button>
      </div>

      {cards.length === 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <EmptyState
            icon={CardIcon}
            title="Nenhum cartão cadastrado"
            description="Cadastre um cartão para acompanhar limite disponível e faturas mês a mês."
            action={
              <Button onClick={openCreate} className="gap-2">
                <Plus className="h-4 w-4" /> Novo cartão
              </Button>
            }
          />
        </div>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {(cards as CardRow[]).map((card) => (
            <CreditCardVisual
              key={card.id}
              name={card.name}
              limit={parseFloat(card.limit)}
              available={parseFloat(card.available_limit)}
              committed={parseFloat(card.committed_amount)}
              closingDay={card.closing_day}
              dueDay={card.due_day}
              currency={baseCurrency}
              alert={card.next_due ? statementAlert({ ...card.next_due, amount: parseFloat(card.next_due.amount) }, baseCurrency) : null}
              dueLabel={dueLabelOf(card.next_due)}
              selected={selectedCardId === card.id}
              onClick={() => onSelectCard?.(card.id)}
              onEdit={() => openEdit(card)}
              onDelete={() => handleDelete(card)}
            />
          ))}
          <button
            type="button"
            onClick={openCreate}
            className="flex aspect-[1.9/1] w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border text-muted-foreground transition-colors hover:border-brand/50 hover:text-foreground"
          >
            <Plus className="h-6 w-6" />
            <span className="text-sm font-medium">Adicionar cartão</span>
          </button>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-card border-border sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingId != null ? 'Editar cartão de crédito' : 'Novo cartão de crédito'}</DialogTitle>
            <DialogDescription>
              {editingId != null
                ? 'Atualize os dados do cartão. As faturas usam o novo fechamento/vencimento a partir de agora.'
                : 'Cadastre um cartão para vincular transações às faturas.'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="card-name">Nome</Label>
              <Input
                id="card-name"
                placeholder="Ex: Nubank, Inter..."
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="card-limit">Limite</Label>
              <MoneyInput id="card-limit" value={limit} onChange={setLimit} prefix={currencySymbol(baseCurrency)} />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="closing-day">Dia de fechamento</Label>
                <Input
                  id="closing-day"
                  type="number"
                  min={1}
                  max={31}
                  value={closingDay}
                  onChange={(e) => setClosingDay(Number(e.target.value))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="due-day">Dia de vencimento</Label>
                <Input
                  id="due-day"
                  type="number"
                  min={1}
                  max={31}
                  value={dueDay}
                  onChange={(e) => setDueDay(Number(e.target.value))}
                />
              </div>
            </div>
            {error && <p className="text-xs font-medium text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>
              Cancelar
            </Button>
            <Button type="button" onClick={handleSubmit} disabled={saving} className="px-8">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : editingId != null ? 'Salvar' : 'Criar cartão'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
