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
import { Label } from "@/components/ui/label";
import { Loader2 } from 'lucide-react';
import { useWorkspaces } from '@/hooks/use-workspaces';

interface WorkspaceCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WorkspaceCreateDialog({ open, onOpenChange }: WorkspaceCreateDialogProps) {
  const { create } = useWorkspaces();
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
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
      await create({ name: name.trim(), description: description.trim() || undefined });
      setName('');
      setDescription('');
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
          <DialogTitle>Novo Workspace</DialogTitle>
          <DialogDescription>
            Crie um espaço separado para organizar finanças (ex: casa, viagem, família).
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
            <Input
              id="ws-desc"
              placeholder="Para que serve este workspace?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="bg-background/50"
            />
          </div>
          {error && <p className="text-xs text-destructive font-medium">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="button" onClick={handleCreate} disabled={loading} className="bg-primary font-bold px-8">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Criar Workspace'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
