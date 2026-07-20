import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { PiggyBank, Loader2 } from 'lucide-react';
import { useEstimates } from '@/hooks/use-estimates';
import { formatCurrency } from '@/lib/money';

interface BudgetCardProps {
  totalBudget: number;
  isOverBudget: boolean;
}

export function BudgetCard({ totalBudget, isOverBudget }: BudgetCardProps) {
  const currentMonth = new Date().toISOString().slice(0, 7);
  const { setBudget, isSaving } = useEstimates(currentMonth);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [amount, setAmount] = React.useState(totalBudget);

  const openDialog = () => {
    setAmount(totalBudget);
    setDialogOpen(true);
  };

  const save = async () => {
    try {
      await setBudget(amount);
      setDialogOpen(false);
    } catch {
      alert('Erro ao salvar o orçamento.');
    }
  };

  return (
    <>
      <Card
        onClick={openDialog}
        className={`bg-card border-border hover:bg-accent/50 transition-all cursor-pointer group border-l-4 shadow-lg ${
          totalBudget > 0 && isOverBudget ? 'border-l-destructive' : 'border-l-amber-500'
        }`}
      >
        <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
          <CardTitle className="text-xs font-black uppercase tracking-widest text-amber-500">Orçamento do Mês</CardTitle>
          <PiggyBank className="h-4 w-4 text-amber-500 group-hover:scale-110 transition-transform" />
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-black text-foreground">
            {totalBudget > 0 ? formatCurrency(totalBudget) : '—'}
          </div>
          <p className="text-[10px] font-bold text-muted-foreground mt-1">
            {totalBudget > 0
              ? isOverBudget
                ? 'Previsão acima do orçamento!'
                : 'Previsão dentro do orçamento'
              : 'Clique para definir seu limite de gastos'}
          </p>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-card border-border sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>Orçamento do Mês</DialogTitle>
            <DialogDescription>
              Quanto você quer gastar no máximo este mês? A previsão avisa quando estourar.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-4">
            <Label htmlFor="budget-amount">Limite de gastos</Label>
            <MoneyInput id="budget-amount" value={amount} onChange={setAmount} className="bg-background/50" />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>Cancelar</Button>
            <Button type="button" onClick={save} disabled={isSaving || amount <= 0} className="bg-primary font-bold px-8">
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Salvar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
