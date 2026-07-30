import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Target, Trash2, Plus } from 'lucide-react';
import { useEstimates, type Estimate, type EstimateScope } from '@/hooks/use-estimates';
import { useCategories } from '@/hooks/use-categories';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { ExcludedForeignNotice } from '@/components/money/ExcludedForeignNotice';
import { getApiErrorMessage } from '@/lib/api-error';
import { currencySymbol, formatMoney } from '@/lib/money';

const selectClass =
  'flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring';


interface BudgetPanelProps {
  spentByCategory: { category_id?: number | null; name: string; value: number }[];
  /** Gasto total da CASA — `null` quando o acesso é `involved_only` (ADR 0018). */
  totalExpenses: number | null;
  /** Mesma composição, recortada na parte do usuário (meta pessoal). */
  mySpentByCategory?: { category_id?: number | null; name: string; value: number }[];
  /** Soma dos splits do usuário no mês — o total contra a meta pessoal. */
  myExpenses?: number;
  /** Lançamentos fora da moeda-base que NÃO entraram nos totais (ADR 0006). */
  excludedForeignCount?: number | null;
  /** Mês exibido (YYYY-MM) — o mesmo do resto da tela de relatórios. */
  month: string;
}

const monthLabel = (month: string) => {
  const [y, m] = month.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
};

// Orçamento por categoria do mês exibido: meta vs. gasto real com progresso.
// Duas visões, porque são duas perguntas diferentes: quanto a CASA pode gastar e
// quanto EU posso. Antes só existia a da casa, e o Início comparava a despesa
// pessoal contra ela — num workspace de duas pessoas a barra mentia pela metade.
export function BudgetPanel({
  spentByCategory,
  totalExpenses,
  mySpentByCategory = [],
  myExpenses = 0,
  excludedForeignCount,
  month,
}: BudgetPanelProps) {
  const baseCurrency = useBaseCurrency();
  const formatBRL = (value: number) => formatMoney(value, { currency: baseCurrency });
  const [scope, setScope] = React.useState<EstimateScope>('workspace');
  const { estimatesByScope, setCategoryBudget, removeEstimate } = useEstimates(month);
  const { categories } = useCategories();
  // Chave do <select>: 'geral' ou o id da categoria (nunca o nome — ver spentFor)
  const [newCategoryKey, setNewCategoryKey] = React.useState('');
  const [newAmount, setNewAmount] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);

  // Sem acesso completo o gasto da casa não vem (ADR 0018), então a visão da
  // casa não tem denominador: o escopo pessoal passa a ser o único. Deixar o
  // usuário alternar mostraria barras contra `null` — 0%, ou NaN.
  const semVisaoDaCasa = totalExpenses == null;
  const pessoal = semVisaoDaCasa || scope === 'personal';
  const estimates = estimatesByScope(pessoal ? 'personal' : scope);
  const gastoPorCategoria = pessoal ? mySpentByCategory : spentByCategory;
  const gastoTotal = pessoal ? myExpenses : (totalExpenses ?? 0);

  const spentFor = (estimate: Estimate): number => {
    if (estimate.category === 'Geral') return gastoTotal;
    // Casa por id: renomear a categoria costumava zerar o consumo calado, porque
    // a meta guardava o nome antigo e o gasto vinha com o novo (BUD-001).
    if (estimate.category_id != null) {
      return gastoPorCategoria.find((c) => c.category_id === estimate.category_id)?.value ?? 0;
    }
    // Metas antigas (sem id): resta o nome
    return gastoPorCategoria.find((c) => c.name === estimate.category)?.value ?? 0;
  };

  // "Geral" é a meta agregada do mês, não uma categoria de verdade → id nulo.
  // O filtro olha só as metas do escopo ATIVO: a mesma categoria pode ter meta
  // da casa e meta pessoal ao mesmo tempo.
  const availableCategories = [
    { key: 'geral', id: null as number | null, name: 'Geral' },
    ...categories.map((c) => ({ key: String(c.id), id: c.id as number | null, name: c.name })),
  ].filter((opt) =>
    !estimates.some((e) =>
      opt.id != null && e.category_id != null ? e.category_id === opt.id : e.category === opt.name,
    ),
  );

  const addBudget = async () => {
    setError(null);
    const option = availableCategories.find((c) => c.key === newCategoryKey);
    if (!option) {
      setError('Escolha uma categoria.');
      return;
    }
    if (newAmount <= 0) {
      setError('Informe um valor de orçamento maior que zero.');
      return;
    }
    try {
      await setCategoryBudget({
        category: option.name,
        categoryId: option.id,
        amount: newAmount,
        scope,
      });
      setNewCategoryKey('');
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

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Target className="h-5 w-5 text-primary" />
          Orçamento por Categoria — {monthLabel(month)}
        </CardTitle>
        <CardDescription>
          {pessoal
            ? 'Sua meta de gasto: comparada com a SUA parte das despesas (o rateio), não com o total da casa.'
            : 'Meta da casa: comparada com o gasto total do workspace. A soma vira o orçamento usado na previsão.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Duas perguntas diferentes — "quanto a casa pode gastar" e "quanto eu
            posso" — e por isso duas listas de metas. Com acesso restrito só a
            segunda faz sentido, então o seletor nem aparece. */}
        <div
          role="tablist"
          aria-label="Escopo do orçamento"
          className={`inline-flex rounded-lg bg-accent p-1 ${semVisaoDaCasa ? 'hidden' : ''}`}
        >
          {([
            ['workspace', 'Da casa'],
            ['personal', 'Minha'],
          ] as const).map(([valor, rotulo]) => (
            <button
              key={valor}
              type="button"
              role="tab"
              aria-selected={scope === valor}
              onClick={() => {
                setScope(valor);
                setNewCategoryKey('');
                setError(null);
              }}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                scope === valor
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {rotulo}
            </button>
          ))}
        </div>
        <ExcludedForeignNotice count={excludedForeignCount} baseCurrency={baseCurrency} />
        {estimates.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            {pessoal
              ? 'Você ainda não definiu uma meta pessoal para este mês.'
              : 'Nenhuma meta da casa definida para este mês.'}
          </p>
        ) : (
          <div className="space-y-4">
            {estimates.map((estimate) => {
              const budget = parseFloat(estimate.amount);
              const spent = spentFor(estimate);
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
              value={newCategoryKey}
              onChange={(e) => setNewCategoryKey(e.target.value)}
            >
              <option value="">Selecione...</option>
              {availableCategories.map((opt) => (
                <option key={opt.key} value={opt.key}>{opt.name}</option>
              ))}
            </select>
          </div>
          <div className="w-40 space-y-1.5">
            <Label htmlFor="budget-amount" className="text-xs font-semibold">Meta do mês</Label>
            {/* Prefixo na moeda-base: o default do MoneyInput é "R$" e mentia
                num workspace configurado em outra moeda. */}
            <MoneyInput
              id="budget-amount"
              value={newAmount}
              onChange={setNewAmount}
              prefix={currencySymbol(baseCurrency)}
            />
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
