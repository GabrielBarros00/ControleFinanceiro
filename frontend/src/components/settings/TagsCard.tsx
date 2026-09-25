import * as React from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useConfirm } from '@/components/ui/confirm';
import { useTags, type WorkspaceTag } from '@/hooks/use-tags';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';

/**
 * Tags do espaço: renomear, excluir e criar.
 *
 * A tag nasce no próprio lançamento, com um clique, e até aqui só existia lá: não
 * havia onde corrigir um nome nem apagar uma tag que sobrou. E, sem uma tela ao
 * lado das categorias dizendo o que é cada uma, "a tag das metas" (a categoria)
 * e "a tag do lançamento" pareciam a mesma coisa em dois lugares.
 */
export function TagsCard() {
  const { tags, create, update, remove } = useTags();
  const { canWrite } = useWorkspaceRole();
  const confirm = useConfirm();
  const [nova, setNova] = React.useState('');
  const [editando, setEditando] = React.useState<number | null>(null);
  const [nome, setNome] = React.useState('');

  const criar = async () => {
    const n = nova.trim();
    if (!n) return;
    try {
      await create({ name: n });
      setNova('');
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível criar a tag.'));
    }
  };

  const renomear = async (tag: WorkspaceTag) => {
    const n = nome.trim();
    if (!n || n === tag.name) { setEditando(null); return; }
    try {
      await update({ id: tag.id, data: { name: n } });
      setEditando(null);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível renomear a tag.'));
    }
  };

  const excluir = async (tag: WorkspaceTag) => {
    const sim = await confirm({
      title: 'Excluir tag',
      description: `Excluir a tag "${tag.name}"? Ela sai de todos os lançamentos que a têm; os lançamentos continuam.`,
      confirmLabel: 'Excluir',
      destructive: true,
    });
    if (!sim) return;
    try {
      await remove(tag.id);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível excluir a tag.'));
    }
  };

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader>
        <CardTitle>Tags</CardTitle>
        <CardDescription>
          Várias por despesa, livres: viagem, presente, trabalho. Servem para achar e agrupar
          lançamentos (o filtro da lista), mas não entram nas metas. Você também cria uma tag
          direto no lançamento.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {canWrite && (
          <div className="flex flex-wrap gap-3">
            <Input
              aria-label="Nova tag"
              placeholder="Nova tag..."
              value={nova}
              maxLength={60}
              onChange={(e) => setNova(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void criar()}
              className="min-w-48 flex-1 bg-background/50 border-border"
            />
            <Button onClick={() => void criar()} disabled={!nova.trim()} className="gap-2">
              <Plus className="h-4 w-4" /> Criar
            </Button>
          </div>
        )}
        {tags.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhuma tag ainda.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <li key={tag.id} className="group flex items-center gap-1 rounded-full border border-border/60 bg-accent/30 py-1 pl-3 pr-1 text-sm">
                {editando === tag.id ? (
                  <>
                    <Input
                      aria-label={`Novo nome da tag ${tag.name}`}
                      value={nome}
                      maxLength={60}
                      autoFocus
                      onChange={(e) => setNome(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void renomear(tag);
                        if (e.key === 'Escape') setEditando(null);
                      }}
                      className="h-7 w-36 bg-background/50"
                    />
                    <Button size="sm" className="h-7" onClick={() => void renomear(tag)}>OK</Button>
                  </>
                ) : (
                  <>
                    <span className="font-medium">#{tag.name}</span>
                    {canWrite && (
                      <>
                        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                          aria-label={`Renomear a tag ${tag.name}`}
                          onClick={() => { setEditando(tag.id); setNome(tag.name); }}>
                          Renomear
                        </Button>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                          aria-label={`Excluir a tag ${tag.name}`} onClick={() => void excluir(tag)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </>
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
