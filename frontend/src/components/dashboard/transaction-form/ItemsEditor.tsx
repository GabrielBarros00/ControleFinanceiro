import * as React from 'react';
import { useFormContext, useFieldArray, Controller } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Trash2, Plus } from 'lucide-react';
import { useCategories } from '@/hooks/use-categories';
import { SplitSummary } from './SplitSummary';
import { useFormCurrency } from './use-form-currency';
import type { Participant } from './SplitEditor';
import type { TransactionFormValues } from './schema';
// Era a única cópia divergente do `selectClass` (h-9/py-1, anel de 1px):
// convergir para o padrão alinha estes selects com os `Input` das MESMAS linhas
// do formulário de itens, que já são 40px — o desalinhamento que o comentário
// de `ui/input.tsx` descreve nascia justamente daqui.
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';

interface ItemsEditorProps {
  participants: Participant[];
  defaultUserId: string;
}

// Divisão por item: cada item tem valor (qtd × unitário ou direto), categoria
// e os próprios participantes/método — os splits da despesa são derivados
export function ItemsEditor({ participants, defaultUserId }: ItemsEditorProps) {
  const { control, watch, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: 'items' });
  const { fmt } = useFormCurrency();

  const watchedItems = watch('items');
  const watchedTotal = watch('total_amount');

  const itemsError = errors.items?.root?.message
    ?? (errors.items as { message?: string } | undefined)?.message;

  const itemsCents = (watchedItems ?? []).reduce(
    (acc, item) => acc + Math.round((Number.isFinite(item?.amount) ? item.amount : 0) * 100), 0
  );
  const totalCents = Math.round((watchedTotal ?? 0) * 100);
  const closed = totalCents > 0 && itemsCents === totalCents;
  const diff = Math.abs(totalCents - itemsCents) / 100;

  const appendItem = () => append({
    title: '',
    quantity: 1,
    unit_amount: null,
    amount: 0,
    category_id: '',
    share_method: 'equal',
    shares: defaultUserId ? [{ user_id: defaultUserId, value: 0 }] : [],
  });

  return (
    <div className="space-y-4 border-t border-border pt-6">
      <div className="flex items-center justify-between">
        <Label className="text-sm font-bold text-foreground">Itens da Despesa</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={appendItem}
          className="h-8 border-primary text-primary hover:bg-primary/10 gap-1"
        >
          <Plus className="h-3 w-3" /> Item
        </Button>
      </div>

      <div className="space-y-4">
        {fields.map((field, index) => (
          <ItemRow
            key={field.id}
            index={index}
            participants={participants}
            onRemove={() => remove(index)}
          />
        ))}
      </div>

      {/* Adicionar item também no rodapé: com vários itens, evita rolar até o
          topo toda vez. Nome acessível distinto do botão do cabeçalho ("Item"). */}
      <Button
        type="button"
        variant="outline"
        onClick={appendItem}
        className="w-full border-dashed border-primary/50 text-primary hover:bg-primary/10 gap-1"
      >
        <Plus className="h-4 w-4" /> Adicionar item
      </Button>

      <div className="space-y-1">
        <p
          data-testid="items-summary"
          className={`text-xs font-semibold ${closed ? 'text-emerald-500' : 'text-destructive'}`}
        >
          {closed
            ? `Itens fecham ${fmt(watchedTotal ?? 0)}`
            : itemsCents < totalCents
              ? `Itens: ${fmt(itemsCents / 100)} de ${fmt(totalCents / 100)} — faltam ${fmt(diff)}`
              : `Itens: ${fmt(itemsCents / 100)} de ${fmt(totalCents / 100)} — ${fmt(diff)} acima do total`}
        </p>
        {/* Resumo ao vivo acima é a fonte única da soma. O erro do schema só
            aparece quando NÃO há itens — evita a mensagem stale que contradizia
            o resumo (o amount de item com unitário é derivado via setValue). */}
        {fields.length === 0 && itemsError && (
          <p className="text-sm text-destructive font-medium">{itemsError}</p>
        )}
      </div>
    </div>
  );
}

interface ItemRowProps {
  index: number;
  participants: Participant[];
  onRemove: () => void;
}

function ItemRow({ index, participants, onRemove }: ItemRowProps) {
  const { register, control, watch, setValue, formState: { errors } } = useFormContext<TransactionFormValues>();
  const { categories } = useCategories();
  const { currency, symbol, fmt } = useFormCurrency();
  const { fields, append, remove } = useFieldArray({ control, name: `items.${index}.shares` as const });

  const quantity = watch(`items.${index}.quantity` as const);
  const unitAmount = watch(`items.${index}.unit_amount` as const);
  const shareMethod = watch(`items.${index}.share_method` as const);
  const shares = watch(`items.${index}.shares` as const);
  const amount = watch(`items.${index}.amount` as const);

  const hasUnitPrice = unitAmount != null && unitAmount > 0;

  // Com preço unitário, o total da linha é derivado (qtd × unitário)
  React.useEffect(() => {
    if (!hasUnitPrice) return;
    const qty = Number.isFinite(quantity) ? quantity : 0;
    const computed = Math.round(qty * Math.round((unitAmount ?? 0) * 100)) / 100;
    setValue(`items.${index}.amount`, computed, { shouldValidate: true });
  }, [hasUnitPrice, quantity, unitAmount, index, setValue]);

  const itemErrors = errors.items?.[index];
  const sharesError = itemErrors?.shares?.root?.message
    ?? (itemErrors?.shares as { message?: string } | undefined)?.message;

  return (
    <div className="space-y-3 p-4 rounded-xl bg-accent/20 border border-border/50" data-testid={`item-row-${index}`}>
      {/* Título — linha própria e larga; a lixeira acompanha o input */}
      <div className="flex items-end gap-3">
        <div className="flex-1 space-y-1">
          <Label className="text-[11px] font-semibold text-muted-foreground">Item</Label>
          <Input
            placeholder="Ex: Carne"
            aria-label="Título do item"
            {...register(`items.${index}.title` as const)}
            className="bg-background border-border"
          />
        </div>
        <Button type="button" variant="ghost" size="sm" aria-label="Remover item" onClick={onRemove} className="h-9 w-9 p-0 text-destructive hover:bg-destructive/10">
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      {itemErrors?.title && <p className="text-[10px] text-destructive font-medium">{itemErrors.title.message as string}</p>}

      {/* Quantidade × unitário (ou total direto) — cada campo rotulado.
          Quebra em duas linhas abaixo de `sm`: três campos numa linha de 312px
          deixavam ~56px de dígitos em cada MoneyInput. */}
      <div className="flex flex-wrap items-start gap-3">
        <div className="w-20 shrink-0 space-y-1">
          <Label className="text-[11px] font-semibold text-muted-foreground">Qtd</Label>
          <Input
            type="number"
            step="0.001"
            min="0"
            aria-label="Quantidade"
            {...register(`items.${index}.quantity` as const, { valueAsNumber: true })}
            className="bg-background border-border"
          />
          {itemErrors?.quantity && <p className="text-[10px] text-destructive font-medium">{itemErrors.quantity.message as string}</p>}
        </div>
        <div className="flex-1 space-y-1">
          <Label className="text-[11px] font-semibold text-muted-foreground">
            Valor unitário <span className="font-normal">(opcional)</span>
          </Label>
          <Controller
            name={`items.${index}.unit_amount` as const}
            control={control}
            render={({ field }) => (
              <MoneyInput
                aria-label="Valor unitário"
                value={field.value ?? undefined}
                onChange={(v) => field.onChange(v > 0 ? v : null)}
                prefix={symbol}
                className="bg-background border-border"
              />
            )}
          />
        </div>
        <div className="flex-1 space-y-1">
          <Label className="text-[11px] font-semibold text-muted-foreground">Total</Label>
          {hasUnitPrice ? (
            <div className="h-9 flex items-center px-3 rounded-md border border-border bg-muted text-sm font-bold" aria-label="Total do item">
              {fmt(Number.isFinite(amount) ? amount : 0)}
            </div>
          ) : (
            <Controller
              name={`items.${index}.amount` as const}
              control={control}
              render={({ field }) => (
                <MoneyInput
                  aria-label="Total do item"
                  value={field.value}
                  onChange={field.onChange}
                  prefix={symbol}
                  className="bg-background border-border font-bold"
                />
              )}
            />
          )}
          {itemErrors?.amount && <p className="text-[10px] text-destructive font-medium">{itemErrors.amount.message as string}</p>}
        </div>
      </div>

      {/* Categoria — linha própria, rotulada e com largura total */}
      <div className="space-y-1">
        <Label className="text-[11px] font-semibold text-muted-foreground">Categoria</Label>
        <select
          aria-label="Categoria do item"
          className={selectClass}
          {...register(`items.${index}.category_id` as const)}
        >
          <option value="" className="bg-card">Sem categoria</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id} className="bg-card">{c.name}</option>
          ))}
        </select>
      </div>

      {/* Como dividir este item + participantes */}
      <div className="flex items-center gap-4 flex-wrap">
        <Label className="text-[11px] font-semibold text-muted-foreground">Dividir este item</Label>
        <Controller
          name={`items.${index}.share_method` as const}
          control={control}
          render={({ field }) => (
            <RadioGroup
              value={field.value}
              onValueChange={(value) => field.onChange(value as string)}
              // Mesmo motivo do SplitEditor, agravado: aqui a linha ainda tem o
              // recuo do item dentro do sheet.
              className="flex flex-wrap gap-x-4 gap-y-2"
            >
              <div className="flex items-center space-x-1.5">
                <RadioGroupItem value="equal" id={`item-${index}-equal`} className="border-primary text-primary" />
                <Label htmlFor={`item-${index}-equal`} className="text-xs font-medium text-foreground cursor-pointer">Igual</Label>
              </div>
              <div className="flex items-center space-x-1.5">
                <RadioGroupItem value="percentage" id={`item-${index}-percentage`} className="border-primary text-primary" />
                <Label htmlFor={`item-${index}-percentage`} className="text-xs font-medium text-foreground cursor-pointer">Porcentagem</Label>
              </div>
              <div className="flex items-center space-x-1.5">
                <RadioGroupItem value="fixed" id={`item-${index}-fixed`} className="border-primary text-primary" />
                <Label htmlFor={`item-${index}-fixed`} className="text-xs font-medium text-foreground cursor-pointer">Valor Fixo</Label>
              </div>
            </RadioGroup>
          )}
        />

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => append({ user_id: '', value: 0 })}
          className="h-7 text-xs text-primary hover:bg-primary/10 ml-auto"
        >
          + Participante
        </Button>
      </div>

      <div className="space-y-2">
        {fields.map((shareField, shareIndex) => (
          <div key={shareField.id} className="flex items-center gap-3">
            <div className="flex-1">
              <select
                aria-label={`Participante do item ${index + 1}`}
                className={selectClass}
                {...register(`items.${index}.shares.${shareIndex}.user_id` as const)}
              >
                <option value="" className="bg-card">Usuário...</option>
                {participants.map(p => (
                  <option key={p.id} value={p.id} className="bg-card">{p.name}</option>
                ))}
              </select>
              {itemErrors?.shares?.[shareIndex]?.user_id && (
                <p className="text-[10px] text-destructive mt-1 font-medium">{itemErrors.shares[shareIndex]?.user_id?.message as string}</p>
              )}
            </div>
            {shareMethod !== 'equal' && (
              // Elástico, não fixo: com o prefixo da moeda dentro do campo,
              // 96px cortavam "R$ 1.234,56", e mesmo 128px não davam conta de
              // um valor de milhão. O `min-w` garante o piso, o `flex-1` usa o
              // que sobrar da linha.
              <div
                className={
                  shareMethod === 'percentage'
                    ? 'w-24 shrink-0'
                    : 'min-w-28 flex-1 sm:max-w-40'
                }
              >
                {shareMethod === 'percentage' ? (
                  <Input
                    type="number"
                    step="0.01"
                    placeholder="%"
                    aria-label={`Percentual do item ${index + 1}`}
                    {...register(`items.${index}.shares.${shareIndex}.value` as const, { valueAsNumber: true })}
                    className="bg-background border-border h-9"
                  />
                ) : (
                  <Controller
                    name={`items.${index}.shares.${shareIndex}.value` as const}
                    control={control}
                    render={({ field }) => (
                      <MoneyInput
                        aria-label={`Valor fixo do item ${index + 1}`}
                        value={field.value}
                        onChange={field.onChange}
                        prefix={symbol}
                        className="bg-background border-border h-9"
                      />
                    )}
                  />
                )}
              </div>
            )}
            <Button type="button" variant="ghost" size="sm" aria-label="Remover participante do item" onClick={() => remove(shareIndex)} className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10">
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      <SplitSummary
        method={shareMethod}
        splits={shares ?? []}
        totalAmount={Number.isFinite(amount) ? amount : 0}
        currency={currency}
        testId={`item-summary-${index}`}
      />
      {/* Mesma regra do resumo dos itens: com participantes na tela, o resumo ao
          vivo acima JÁ diz quanto falta — repetir a soma em vermelho era a
          mesma frase duas vezes. Sem participantes não há resumo, e aí o erro
          ("adicione pelo menos um") é o único sinal. */}
      {fields.length === 0 && sharesError && (
        <p className="text-xs text-destructive font-medium">{sharesError}</p>
      )}
    </div>
  );
}
