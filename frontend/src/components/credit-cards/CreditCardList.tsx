import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CreditCard as CardIcon, Calendar, Info, Loader2, Trash2 } from 'lucide-react';
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { useCreditCards } from '@/hooks/use-credit-cards';
import { formatCurrency } from '@/lib/money';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';

interface CreditCardListProps {
  selectedCardId?: number | null;
  onSelectCard?: (id: number) => void;
}

export function CreditCardList({ selectedCardId, onSelectCard }: CreditCardListProps) {
  const { cards, isLoading, create, remove } = useCreditCards();
  const confirm = useConfirm();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [name, setName] = React.useState('');
  const [limit, setLimit] = React.useState(0);
  const [closingDay, setClosingDay] = React.useState(1);
  const [dueDay, setDueDay] = React.useState(10);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleCreate = async () => {
    if (!name.trim() || limit <= 0) {
      setError('Preencha nome e limite do cartão.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await create({ name: name.trim(), limit, closing_day: closingDay, due_day: dueDay });
      setDialogOpen(false);
      setName(''); setLimit(0); setClosingDay(1); setDueDay(10);
    } catch {
      setError('Erro ao criar cartão.');
    } finally {
      setSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="h-[200px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-foreground">Meus Cartões</h2>
        <Button onClick={() => setDialogOpen(true)} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold">+ Novo Cartão</Button>
      </div>

      {cards.length === 0 ? (
        <Card className="bg-card border-border p-12 text-center">
          <p className="text-muted-foreground">Nenhum cartão cadastrado neste workspace.</p>
        </Card>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {cards.map((card: { id: number; name: string; limit: string; closing_day: number; due_day: number; committed_amount: string; available_limit: string }) => (
            <Card
              key={card.id}
              className={`bg-card transition-colors group cursor-pointer ${
                selectedCardId === card.id ? 'border-primary ring-1 ring-primary/40' : 'border-border hover:border-primary/50'
              }`}
              onClick={() => onSelectCard?.(card.id)}
            >
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-primary/10 rounded-lg group-hover:bg-primary/20 transition-colors">
                    <CardIcon className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <CardTitle className="text-foreground">{card.name}</CardTitle>
                    <CardDescription>Limite: {formatCurrency(parseFloat(card.limit))}</CardDescription>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {selectedCardId === card.id && (
                    <Badge className="bg-primary/10 text-primary border-none">Selecionado</Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={async (e) => {
                      e.stopPropagation();
                      const ok = await confirm({
                        title: 'Excluir cartão',
                        description: `Excluir o cartão ${card.name}?`,
                        confirmLabel: 'Excluir',
                        destructive: true,
                      });
                      if (!ok) return;
                      try { await remove(card.id); } catch { toast.error('Erro ao excluir cartão.'); }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Limite disponível = limite − faturas ainda não pagas (ADR 0011) */}
                <div className="pt-2 border-t border-border space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Disponível</span>
                    <span className={`font-bold ${parseFloat(card.available_limit) < 0 ? 'text-destructive' : 'text-emerald-500'}`}>
                      {formatCurrency(parseFloat(card.available_limit))}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>Comprometido</span>
                    <span>{formatCurrency(parseFloat(card.committed_amount))}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Calendar className="h-4 w-4" />
                    <span>Fecha dia {card.closing_day}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Info className="h-4 w-4" />
                    <span>Vence dia {card.due_day}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-card border-border sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Novo Cartão de Crédito</DialogTitle>
            <DialogDescription>Cadastre um cartão para vincular transações às faturas.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="card-name">Nome</Label>
              <Input id="card-name" placeholder="Ex: Nubank, Inter..." value={name} onChange={(e) => setName(e.target.value)} className="bg-background/50" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="card-limit">Limite</Label>
              <MoneyInput id="card-limit" value={limit} onChange={setLimit} className="bg-background/50" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="closing-day">Dia de Fechamento</Label>
                <Input id="closing-day" type="number" min={1} max={31} value={closingDay} onChange={(e) => setClosingDay(Number(e.target.value))} className="bg-background/50" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="due-day">Dia de Vencimento</Label>
                <Input id="due-day" type="number" min={1} max={31} value={dueDay} onChange={(e) => setDueDay(Number(e.target.value))} className="bg-background/50" />
              </div>
            </div>
            {error && <p className="text-xs text-destructive font-medium">{error}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>Cancelar</Button>
            <Button type="button" onClick={handleCreate} disabled={saving} className="bg-primary font-bold px-8">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Criar Cartão'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
