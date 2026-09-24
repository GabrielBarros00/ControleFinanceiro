import { History, Loader2, Undo2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { StatusPill } from '@/components/ui/status-pill';
import { useConfirm } from '@/components/ui/confirm';
import { useAccountImportHistory, useImportHistory, useUndoAccountImport, useUndoImport } from '@/hooks/use-imports';
import { getApiErrorMessage } from '@/lib/api-error';
import { parseApiDate } from '@/lib/date';
import { toast } from '@/stores/toast';

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

/** Um lote na tela, venha ele da importação de despesas ou do extrato de conta. */
interface Lote {
  id: number;
  filename?: string | null;
  created_at: string;
  imported: number;
  duplicate: number;
  ignored: number;
  /** O que o lote criou e ainda existe. */
  live: number;
  attachments: number;
  origem?: string;
}

/**
 * Importações anteriores, com "Desfazer" (ADR 0036/0037).
 *
 * Importar no espaço errado ou com as colunas trocadas criava dezenas de
 * registros que só saíam um a um. Desfazer exclui o que o lote criou e ainda
 * existe — com as regras da exclusão, tudo ou nada — e depois o arquivo pode ser
 * importado de novo.
 */
function ListaDeImportacoes({ lotes, isLoading, isError, refetch, desfazer, pendente, descricao, itens }: {
  lotes?: Lote[]; isLoading: boolean; isError: boolean; refetch: () => void;
  desfazer: (lote: Lote) => Promise<number>; pendente: boolean; descricao: string;
  /** Como contar o que sai ("lançamentos", "registros"). */
  itens: [string, string];
}) {
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
  if (isError) return <ErrorState message="Não foi possível carregar as importações." onRetry={refetch} />;
  if (!lotes?.length) return null;
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <History className="h-5 w-5 text-primary" /> Importações anteriores
        </CardTitle>
        <CardDescription>{descricao}</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-border">
          {lotes.map((lote) => <LinhaDeImportacao key={lote.id} lote={lote} desfazer={desfazer} pendente={pendente} itens={itens} />)}
        </ul>
      </CardContent>
    </Card>
  );
}

function LinhaDeImportacao({ lote, desfazer, pendente, itens }: {
  lote: Lote; desfazer: (lote: Lote) => Promise<number>; pendente: boolean; itens: [string, string];
}) {
  const confirm = useConfirm();
  const desfeita = lote.imported > 0 && lote.live === 0;
  const excluidos = lote.imported - lote.live;

  async function aoDesfazer() {
    const n = lote.live;
    const ok = await confirm({
      title: `Desfazer a importação de ${lote.filename ?? 'extrato'}?`,
      description:
        `${plural(n, `${itens[0]} criado por ela sai`, `${itens[1]} criados por ela saem`)}.` +
        (lote.attachments > 0
          ? ` ${plural(lote.attachments, 'recibo anexado será apagado', 'recibos anexados serão apagados')} para sempre.`
          : ' Depois dá para importar o arquivo de novo.'),
      confirmLabel: 'Desfazer importação',
      destructive: true,
    });
    if (!ok) return;
    try {
      const saiu = await desfazer(lote);
      toast.success('Importação desfeita', `${plural(saiu, `${itens[0]} desfeito`, `${itens[1]} desfeitos`)}.`);
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
          {lote.origem && ` · ${lote.origem}`}
          {' · '}{plural(lote.imported, 'importado', 'importados')}
          {lote.duplicate > 0 && ` · ${plural(lote.duplicate, 'duplicata', 'duplicatas')}`}
          {lote.ignored > 0 && ` · ${plural(lote.ignored, 'ignorado', 'ignorados')}`}
          {!desfeita && excluidos > 0 && ` · ${plural(excluidos, 'já excluído', 'já excluídos')}`}
        </p>
      </div>
      {lote.live > 0 && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0 gap-1.5 self-start sm:self-auto"
          disabled={pendente}
          onClick={() => void aoDesfazer()}
        >
          {pendente ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />}
          Desfazer
        </Button>
      )}
    </li>
  );
}

/** As importações de DESPESAS deste espaço (ADR 0036). */
export function ImportHistory() {
  const { data, isLoading, isError, refetch } = useImportHistory();
  const desfazer = useUndoImport();
  return (
    <ListaDeImportacoes
      lotes={data?.map((b) => ({ ...b, live: b.live_transactions }))}
      isLoading={isLoading} isError={isError} refetch={() => void refetch()}
      pendente={desfazer.isPending} itens={['lançamento', 'lançamentos']}
      descricao="Importou no lugar errado? Desfaça e importe de novo."
      desfazer={async (lote) => (await desfazer.mutateAsync({ batchId: lote.id, confirmAttachments: lote.attachments > 0 })).deleted}
    />
  );
}

/** As importações de EXTRATO DE CONTA da pessoa (ADR 0037). */
export function AccountImportHistory() {
  const { data, isLoading, isError, refetch } = useAccountImportHistory();
  const desfazer = useUndoAccountImport();
  return (
    <ListaDeImportacoes
      lotes={data?.map((b) => ({ ...b, origem: b.account_name }))}
      isLoading={isLoading} isError={isError} refetch={() => void refetch()}
      pendente={desfazer.isPending} itens={['registro', 'registros']}
      descricao="Despesas, rendas, transferências e pagamentos de fatura que o extrato criou saem juntos."
      desfazer={async (lote) => {
        const r = await desfazer.mutateAsync({ batchId: lote.id, confirmAttachments: lote.attachments > 0 });
        return Object.values(r.undone ?? {}).reduce((a, n) => a + n, 0);
      }}
    />
  );
}
