import { History, Loader2, Undo2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { StatusPill } from '@/components/ui/status-pill';
import { useConfirm } from '@/components/ui/confirm';
import { useImportHistory, useUndoImport, type ImportBatch } from '@/hooks/use-imports';
import { getApiErrorMessage } from '@/lib/api-error';
import { parseApiDate } from '@/lib/date';
import { toast } from '@/stores/toast';

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

/**
 * Importações anteriores, com "Desfazer" (ADR 0036).
 *
 * Importar no espaço errado ou com as colunas trocadas criava dezenas de
 * lançamentos que só saíam um a um. Desfazer exclui o que o lote criou e ainda
 * existe — com as regras da exclusão, tudo ou nada — e depois o arquivo pode ser
 * importado de novo.
 */
export function ImportHistory() {
  const { data, isLoading, isError, refetch } = useImportHistory();
  if (isLoading) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="space-y-2 p-4">
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-12 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (isError) return <ErrorState message="Não foi possível carregar as importações." onRetry={() => void refetch()} />;
  if (!data?.length) return null;
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <History className="h-5 w-5 text-primary" /> Importações anteriores
        </CardTitle>
        <CardDescription>Importou no lugar errado? Desfaça e importe de novo.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-border">
          {data.map((lote) => <LinhaDeImportacao key={lote.id} lote={lote} />)}
        </ul>
      </CardContent>
    </Card>
  );
}

function LinhaDeImportacao({ lote }: { lote: ImportBatch }) {
  const confirm = useConfirm();
  const desfazer = useUndoImport();
  const desfeita = lote.imported > 0 && lote.live_transactions === 0;
  const excluidos = lote.imported - lote.live_transactions;

  async function aoDesfazer() {
    const n = lote.live_transactions;
    const ok = await confirm({
      title: `Desfazer a importação de ${lote.filename ?? 'extrato'}?`,
      description:
        `${plural(n, 'lançamento criado por ela será excluído', 'lançamentos criados por ela serão excluídos')}.` +
        (lote.attachments > 0
          ? ` ${plural(lote.attachments, 'recibo anexado será apagado', 'recibos anexados serão apagados')} para sempre.`
          : ' Depois dá para importar o arquivo de novo.'),
      confirmLabel: 'Desfazer importação',
      destructive: true,
    });
    if (!ok) return;
    try {
      const r = await desfazer.mutateAsync({ batchId: lote.id, confirmAttachments: lote.attachments > 0 });
      toast.success('Importação desfeita', `${plural(r.deleted, 'lançamento excluído', 'lançamentos excluídos')}.`);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Não foi possível desfazer a importação.'));
    }
  }

  return (
    <li className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{lote.filename ?? `Importação #${lote.id}`}</span>
          {desfeita && <StatusPill>Desfeita</StatusPill>}
        </div>
        <p className="text-xs text-muted-foreground">
          {parseApiDate(lote.created_at).toLocaleDateString('pt-BR')}
          {' · '}{plural(lote.imported, 'importado', 'importados')}
          {lote.duplicate > 0 && ` · ${plural(lote.duplicate, 'duplicata', 'duplicatas')}`}
          {lote.ignored > 0 && ` · ${plural(lote.ignored, 'ignorado', 'ignorados')}`}
          {!desfeita && excluidos > 0 && ` · ${plural(excluidos, 'já excluído', 'já excluídos')}`}
        </p>
      </div>
      {lote.live_transactions > 0 && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0 gap-1.5 self-start sm:self-auto"
          disabled={desfazer.isPending}
          onClick={() => void aoDesfazer()}
        >
          {desfazer.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />}
          Desfazer
        </Button>
      )}
    </li>
  );
}
