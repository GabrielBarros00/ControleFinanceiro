import * as React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Loader2 } from 'lucide-react';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { CURRENCIES } from '@/lib/currencies';

// <select> nativo: dentro de Dialog (Radix) o Select do Base UI foge do focus-trap
import { nativeSelectClass as selectClass } from '@/components/ui/native-select';

interface WorkspaceCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WorkspaceCreateDialog({ open, onOpenChange }: WorkspaceCreateDialogProps) {
  const { create } = useWorkspaces();
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [baseCurrency, setBaseCurrency] = React.useState('BRL');
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleCreate = async () => {
    if (name.trim().length < 2) {
      setError('O nome deve ter pelo menos 2 caracteres');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await create({
        name: name.trim(),
        description: description.trim() || undefined,
        base_currency: baseCurrency,
      });
      setName('');
      setDescription('');
      setBaseCurrency('BRL');
      onOpenChange(false);
    } catch {
      setError('Erro ao criar workspace. Tente novamente.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Novo espaço</DialogTitle>
          <DialogDescription>
            Um lugar separado para organizar finanças com outras pessoas — ou só suas (ex: casa, viagem, família).
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="ws-name">Nome</Label>
            <Input
              id="ws-name"
              placeholder="Ex: Casa, Família, Viagem..."
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="bg-background/50"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ws-desc">Descrição (opcional)</Label>
            <Textarea
              id="ws-desc"
              rows={3}
              placeholder="Para que serve este espaço?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="bg-background/50"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ws-currency">Moeda-base</Label>
            <select
              id="ws-currency"
              className={selectClass}
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
            >
              {CURRENCIES.map((c) => (
                <option key={c.code} value={c.code} className="bg-card">
                  {c.code} — {c.name}
                </option>
              ))}
            </select>
            {/* Trocar depois exige reconverter todo o histórico — escolher aqui
                é grátis, e o espaço ainda está vazio. */}
            <p className="text-xs text-muted-foreground">
              Todos os totais deste espaço são somados nesta moeda. Dá para mudar
              depois, mas aí o histórico inteiro é reconvertido.
            </p>
          </div>
          {error && <p className="text-xs text-destructive font-medium">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="button" onClick={handleCreate} disabled={loading} className="bg-primary font-bold px-8">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Criar espaço'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
