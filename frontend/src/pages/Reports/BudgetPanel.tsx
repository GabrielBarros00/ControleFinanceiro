import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Target, Trash2, Plus } from 'lucide-react';
import { useEstimates } from '@/hooks/use-estimates';
import { useCategories } from '@/hooks/use-categories';
import { getApiErrorMessage } from '@/lib/api-error';

const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';

const formatBRL = (value: number) =>
  `R$ ${value.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;

interface BudgetPanelProps {
  spentByCategory: { name: string; value: number }[];
  totalExpenses: number;
}

// Orçamento por categoria do mês corrente: meta vs. gasto real com progresso
export function BudgetPanel({ spentByCategory, totalExpenses }: BudgetPanelProps) {
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const { estimates, setCategoryBudget, removeEstimate } = useEstimates(month);
  const { categories } = useCategories();
  const [newCategory, setNewCategory] = React.useState('');
  const [newAmount, setNewAmount] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);

  const spentFor = (category: string): number => {
    if (category === 'Geral') return totalExpenses;
    return spentByCategory.find((c) => c.name === category)?.value ?? 0;
  };

  const addBudget = async () => {
    setError(null);
    if (!newCategory) {
      setError('Escolha uma categoria.');
      return;
    }
    if (newAmount <= 0) {
      setError('Informe um valor de orçamento maior que zero.');
      return;
    }
    try {
      await setCategoryBudget({ category: newCategory, amount: newAmount });
      setNewCategory('');
      setNewAmount(0);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao salvar o orçamento.'));
    }
  };

  const deleteBudget = async (id: number) => {
    setError(null);
    try {
      await removeEstimate(id);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao remover o orçamento.'));
    }
  };

  const availableCategories = [
    'Geral',
    ...categories.map((c) => c.name),
  ].filter((name) => !estimates.some((e) => e.category === name));

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Target className="h-5 w-5 text-primary" />
          Orçamento por Categoria — {now.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })}
        </CardTitle>
        <CardDescription>
          Defina uma meta de gasto por categoria e acompanhe o consumo do mês.
          A soma das metas vira o orçamento total usado na previsão.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {estimates.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            Nenhuma meta definida para este mês.
          </p>
        ) : (
          <div className="space-y-4">
            {estimates.map((estimate) => {
              const budget = parseFloat(estimate.amount);
              const spent = spentFor(estimate.category);
              const pct = budget > 0 ? Math.min(150, (spent / budget) * 100) : 0;
              const over = spent > budget;
              const near = !over && budget > 0 && spent / budget >= 0.75;
              const barColor = over ? 'bg-destructive' : near ? 'bg-amber-500' : 'bg-emerald-500';
              return (
                <div key={estimate.id} className="space-y-1.5" data-testid={`budget-row-${estimate.category}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-bold text-foreground capitalize">{estimate.category}</span>
                    <div className="flex items-center gap-3">
                      <span className={`text-xs font-semibold ${over ? 'text-destructive' : 'text-muted-foreground'}`}>
                        {formatBRL(spent)} de {formatBRL(budget)}
                        {over && ` — ${formatBRL(spent - budget)} acima`}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Remover orçamento de ${estimate.category}`}
                        onClick={() => deleteBudget(estimate.id)}
                        className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  <div className="h-2.5 w-full rounded-full bg-accent overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${barColor}`}
                      style={{ width: `${Math.min(100, pct)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-end gap-3 border-t border-border pt-4">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="budget-category" className="text-xs font-semibold">Categoria</Label>
            <select
              id="budget-category"
              className={selectClass}
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
            >
              <option value="">Selecione...</option>
              {availableCategories.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </div>
          <div className="w-40 space-y-1.5">
            <Label htmlFor="budget-amount" className="text-xs font-semibold">Meta do mês</Label>
            <MoneyInput id="budget-amount" value={newAmount} onChange={setNewAmount} />
          </div>
          <Button onClick={addBudget} className="gap-1.5 font-bold bg-primary text-primary-foreground">
            <Plus className="h-4 w-4" /> Definir
          </Button>
        </div>
        {error && <p role="alert" className="text-sm text-destructive font-medium">{error}</p>}
      </CardContent>
    </Card>
  );
}
