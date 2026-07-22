import * as React from 'react';
import { useFormContext } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Check, Plus, X, ChevronsUpDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTags } from '@/hooks/use-tags';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import type { TransactionFormValues } from './schema';

// Multi-seleção de tags do workspace (checkboxes) + criação rápida inline.
// Substitui o antigo campo "digite para adicionar".
export function TagMultiSelect() {
  const { tags, create } = useTags();
  const { watch, setValue } = useFormContext<TransactionFormValues>();
  const selected = watch('tag_ids') ?? [];
  const [open, setOpen] = React.useState(false);
  const [newTag, setNewTag] = React.useState('');
  const [creating, setCreating] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const selectedTags = tags.filter((t) => selected.includes(t.id));

  const toggle = (id: number) => {
    const next = selected.includes(id) ? selected.filter((t) => t !== id) : [...selected, id];
    setValue('tag_ids', next, { shouldValidate: true, shouldDirty: true });
  };

  const quickCreate = async () => {
    const name = newTag.trim();
    if (!name) return;
    setCreating(true);
    try {
      const tag = await create({ name });
      setValue('tag_ids', [...selected, tag.id], { shouldValidate: true, shouldDirty: true });
      setNewTag('');
    } catch (err) {
      toast.error('Erro ao criar a tag', getApiErrorMessage(err, 'Tente novamente.'));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-2">
      <Label className="text-sm font-semibold text-foreground">Tags</Label>
      <div ref={containerRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-label="Tags"
          className="flex min-h-10 w-full items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm transition-colors hover:border-primary/50 focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <span className="flex flex-1 flex-wrap items-center gap-1.5">
            {selectedTags.length === 0 ? (
              <span className="text-muted-foreground">Selecionar tags...</span>
            ) : (
              selectedTags.map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary"
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: tag.color || 'var(--primary)' }}
                  />
                  {tag.name}
                  <span
                    role="button"
                    tabIndex={-1}
                    aria-label={`Remover ${tag.name}`}
                    onClick={(e) => { e.stopPropagation(); toggle(tag.id); }}
                    className="ml-0.5 rounded-full hover:text-destructive"
                  >
                    <X className="h-3 w-3" />
                  </span>
                </span>
              ))
            )}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>

        {open && (
          <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-xl border border-border bg-card shadow-2xl animate-in fade-in slide-in-from-top-1 duration-150">
            <div className="max-h-48 overflow-y-auto py-1" role="listbox" aria-multiselectable>
              {tags.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  Nenhuma tag ainda — crie a primeira abaixo.
                </p>
              ) : (
                tags.map((tag) => {
                  const active = selected.includes(tag.id);
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      onClick={() => toggle(tag.id)}
                      className={cn(
                        'flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-accent',
                        active ? 'font-semibold text-foreground' : 'text-muted-foreground'
                      )}
                    >
                      <span
                        className={cn(
                          'flex h-4 w-4 items-center justify-center rounded border',
                          active ? 'border-primary bg-primary text-primary-foreground' : 'border-border'
                        )}
                      >
                        {active && <Check className="h-3 w-3" />}
                      </span>
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: tag.color || 'var(--muted-foreground)' }}
                      />
                      {tag.name}
                    </button>
                  );
                })
              )}
            </div>
            <div className="flex items-center gap-1 border-t border-border p-2">
              <Input
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    quickCreate();
                  }
                }}
                placeholder="Criar nova tag..."
                aria-label="Nova tag"
                className="h-8 flex-1 border-border bg-background text-xs"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label="Criar tag"
                onClick={quickCreate}
                disabled={creating || !newTag.trim()}
                className="h-8 w-8 p-0 text-primary hover:bg-primary/10"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
