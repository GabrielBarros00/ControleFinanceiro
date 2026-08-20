import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { CardsOrTable, DataCard } from '@/components/ui/data-card';
import { StatusPill } from '@/components/ui/status-pill';
import { Trash2 } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import { monthCompactLabel, parseApiDate } from '@/lib/date';

/**
 * O histórico de acertos — o ÚNICO lugar onde os acertos são listados.
 *
 * Antes existiam três listas: a tabela do rodapé de cada tela e mais as linhas
 * "fulano pagou X a beltrano" dentro do retrato do mês. A pessoa via o mesmo
 * pagamento duas vezes na mesma rolagem e não sabia se eram um ou dois. Agora o
 * mês mostra só o ESTADO ("R$ 40,00 já acertados") e manda para cá.
 *
 * **A pílula do mês é a novidade que importa.** `billing_month` sempre existiu
 * no banco e na resposta, e nunca apareceu na tela — então os dois tipos de
 * acerto eram indistinguíveis: o registrado a partir de um mês fecha AQUELE mês;
 * o registrado a partir do saldo acumulado derruba o total sem fechar mês
 * nenhum. É a explicação do saldo que "cai sozinho", e ela estava escondida.
 *
 * As duas telas mapeiam o payload delas para `HistoryRow` — a da casa tem os
 * nomes e o desfazer, a global tem a coluna de espaço e o eixo "eu". A tabela, os
 * cartões do celular e a pílula moram aqui, uma vez só.
 */
export interface HistoryRow {
  id: number;
  /** ISO da API. */
  settledAt: string;
  /** Quem está do outro lado, já escrito: "Ana → Bruno" ou "Você pagou Ana". */
  who: ReactNode;
  /** Só na tela global: o espaço a que o acerto pertence. */
  workspace?: { id: number; name: string };
  billingMonth?: string | null;
  note?: string | null;
  amount: string | number;
  currency: string;
  /** Cor e sinal do valor, do ponto de vista de quem olha. `neutral` = acerto
   *  entre terceiros, que a tela da casa mostra a quem tem acesso completo e no
   *  qual não há "para mim" nenhum. */
  kind: 'sent' | 'received' | 'neutral';
  /** Ausente = não dá para desfazer daqui (é o caso da tela global). */
  onUndo?: () => void;
  canUndo?: boolean;
}

interface Props {
  rows: HistoryRow[];
  /** Rótulo da coluna de quem: "Com quem" na global, "Acerto" na casa. */
  whoLabel?: string;
}

function MesPill({ month }: { month?: string | null }) {
  return month ? (
    <StatusPill tone="brand">{monthCompactLabel(month)}</StatusPill>
  ) : (
    /* "Sem mês" não é ausência de dado, é um TIPO de acerto — o que abate o
       acumulado sem fechar mês nenhum. Um traço faria parecer campo vazio. */
    <StatusPill tone="neutral">sem mês</StatusPill>
  );
}

function Valor({ row }: { row: HistoryRow }) {
  const sinal = row.kind === 'sent' ? '−' : row.kind === 'received' ? '+' : '';
  // `neutral` é NEUTRO de verdade. A tela da casa pintava todo acerto de verde,
  // inclusive os que eu paguei e os entre terceiros — verde ali quer dizer
  // "entrou para mim", que é falso nos dois casos.
  const cor =
    row.kind === 'sent' ? 'text-expense' : row.kind === 'received' ? 'text-income' : 'text-foreground';
  return (
    <span className={`whitespace-nowrap font-semibold ${cor}`}>
      {sinal}
      {formatMoney(row.amount, { currency: row.currency })}
    </span>
  );
}

export function SettlementHistory({ rows, whoLabel = 'Com quem' }: Props) {
  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Nenhum acerto registrado ainda.
      </p>
    );
  }

  const data = (row: HistoryRow) => parseApiDate(row.settledAt).toLocaleDateString('pt-BR');

  // Uma vez, não uma por linha: dentro do `map` estes dois viravam uma varredura
  // completa da lista a cada célula. Com 50 acertos e duas colunas condicionais
  // são 5.000 passagens para decidir duas coisas que não mudam.
  const temEspaco = rows.some((r) => r.workspace);
  const temDesfazer = rows.some((r) => r.onUndo);

  return (
    <CardsOrTable
      cards={
        <div className="space-y-2 p-3">
          {rows.map((row) => (
            <DataCard
              key={row.id}
              title={row.who}
              badge={<MesPill month={row.billingMonth} />}
              meta={
                <>
                  {data(row)}
                  {row.workspace && ` · ${row.workspace.name}`}
                  {row.note && ` · ${row.note}`}
                </>
              }
              value={<Valor row={row} />}
              actions={
                row.onUndo && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={row.canUndo === false}
                    onClick={row.onUndo}
                    className="gap-1.5 text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Desfazer
                  </Button>
                )
              }
            />
          ))}
        </div>
      }
      table={
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead className="text-xs font-semibold text-muted-foreground">Data</TableHead>
              {temEspaco && (
                <TableHead className="text-xs font-semibold text-muted-foreground">Espaço</TableHead>
              )}
              <TableHead className="text-xs font-semibold text-muted-foreground">{whoLabel}</TableHead>
              <TableHead className="w-24 text-xs font-semibold text-muted-foreground">Mês</TableHead>
              <TableHead className="text-xs font-semibold text-muted-foreground">Obs.</TableHead>
              <TableHead className="w-32 text-right text-xs font-semibold text-muted-foreground">Valor</TableHead>
              {temDesfazer && <TableHead className="w-12" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} className="border-border hover:bg-accent/30">
                <TableCell className="whitespace-nowrap text-xs">{data(row)}</TableCell>
                {temEspaco && (
                  <TableCell className="text-xs">
                    {row.workspace && (
                      <Link
                        to={`/w/${row.workspace.id}/debts`}
                        className="font-medium text-brand hover:underline"
                      >
                        {row.workspace.name}
                      </Link>
                    )}
                  </TableCell>
                )}
                <TableCell className="text-sm">{row.who}</TableCell>
                <TableCell>
                  <MesPill month={row.billingMonth} />
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">{row.note || '—'}</TableCell>
                <TableCell className="text-right">
                  <Valor row={row} />
                </TableCell>
                {temDesfazer && (
                  <TableCell className="text-center">
                    {row.onUndo && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label="Desfazer acerto"
                        disabled={row.canUndo === false}
                        onClick={row.onUndo}
                        className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    />
  );
}
