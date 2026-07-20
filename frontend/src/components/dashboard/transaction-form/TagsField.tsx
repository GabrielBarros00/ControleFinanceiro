import * as React from 'react';
import { useFormContext } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Plus } from 'lucide-react';
import { useTags } from '@/hooks/use-tags';
import { getApiErrorMessage } from '@/lib/api-error';
import type { TransactionFormValues } from './schema';

// Chips de tags do workspace com criação rápida inline
export function TagsField() {
  const { tags, create } = useTags();
  const { watch, setValue } = useFormContext<TransactionFormValues>();
  const selected = watch('tag_ids') ?? [];
  const [newTag, setNewTag] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const toggle = (id: number) => {
    const next = selected.includes(id)
      ? selected.filter((t) => t !== id)
      : [...selected, id];
    setValue('tag_ids', next, { shouldValidate: true });
  };

  const quickCreate = async () => {
    const name = newTag.trim();
    if (!name) return;
    setError(null);
    try {
      const tag = await create({ name });
      setValue('tag_ids', [...selected, tag.id], { shouldValidate: true });
      setNewTag('');
    } catch (err) {
      setError(getApiErrorMessage(err, 'Erro ao criar a tag.'));
    }
  };

  return (
    <div className="space-y-2">
      <Label className="text-sm font-semibold text-foreground">Tags</Label>
      <div className="flex flex-wrap items-center gap-2">
        {tags.map((tag) => {
          const active = selected.includes(tag.id);
          return (
            <button
              key={tag.id}
              type="button"
              aria-pressed={active}
              onClick={() => toggle(tag.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                active
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border bg-background text-muted-foreground hover:border-primary/50'
              }`}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: tag.color || 'var(--muted-foreground)' }}
              />
              {tag.name}
            </button>
          );
        })}
        <div className="flex items-center gap-1">
          <Input
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                quickCreate();
              }
            }}
            placeholder="Nova tag..."
            aria-label="Nova tag"
            className="h-7 w-28 text-xs bg-background border-border"
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Criar tag"
            onClick={quickCreate}
            className="h-7 w-7 p-0 text-primary hover:bg-primary/10"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      {error && <p className="text-xs text-destructive font-medium">{error}</p>}
    </div>
  );
}
