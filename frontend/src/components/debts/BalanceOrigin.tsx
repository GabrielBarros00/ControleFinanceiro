import { ChevronRight, CalendarDays } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import { monthCompactLabel } from '@/lib/date';
import type { DebtsByMonth } from '@/hooks/use-debts-by-month';

/**
 * De onde vem o saldo acumulado — a soma aberta, mês a mês.
 *
 * Existe por uma queixa concreta: o "Saldo geral a acertar" é cumulativo, e lido
 * sozinho passa a impressão de que aquele valor cheio tem de ser pago no mês
 * corrente. Ele pode ser a soma de três meses que ninguém fechou — e cada um
 * deles se acerta sozinho.
 *
 * **A conta fecha na tela.** As linhas somam o total, incluindo a linha "sem
 * mês" (acerto registrado a partir do acumulado, que derruba o saldo sem fechar
 * mês nenhum) e a linha dos meses antigos agrupados. Uma quebra que não fecha
 * seria pior do que não existir: a pessoa deixaria de confiar nos dois números,
 * não só no que falta.
 *
 * Ver `DebtService.get_balance_by_month` — a identidade é garantida lá e travada
 * em teste; aqui ela é só exibida.
 */
interface Props {
  origem: DebtsByMonth;
  currency: string;
  /** Abre a aba "Por mês" naquele mês. */
  onOpenMonth: (month: string) => void;
}

/** "você deve X" / "você recebe X" a partir do saldo com sinal. */
function frase(balance: string, currency: string): { texto: string; classe: string } {
  const n = Number(balance);
  const valor = formatMoney(Math.abs(n), { currency });
  if (n < 0) return { texto: `você deve ${valor}`, classe: 'text-expense' };
  if (n > 0) return { texto: `você recebe ${valor}`, classe: 'text-income' };
  return { texto: valor, classe: 'text-muted-foreground' };
}

export function BalanceOrigin({ origem, currency, onOpenMonth }: Props) {
  const temAntigos = origem.older.count > 0;
  const temSemMes = Number(origem.unassigned) !== 0;

  if (origem.months.length === 0 && !temSemMes && !temAntigos) {
    return (
      <p className="rounded-xl border border-border bg-card px-3 py-4 text-center text-sm text-muted-foreground">
        Nenhum mês em aberto.
      </p>
    );
  }

  const total = frase(origem.balance, currency);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <ul className="divide-y divide-border">
        {origem.months.map((mes) => {
          const { texto, classe } = frase(mes.balance, currency);
          const acertado = Number(mes.settled);
          return (
            <li key={mes.month}>
              <button
                type="button"
                onClick={() => onOpenMonth(mes.month)}
                /* Uma linha por mês, nunca grade: a 360px o rótulo do mês, o
                   valor e a seta já ocupam a largura toda. */
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/50"
              >
                <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground/70" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-foreground">
                    {monthCompactLabel(mes.month)}
                  </span>
                  {acertado > 0 && (
                    <span className="block text-[11px] text-muted-foreground">
                      {formatMoney(acertado, { currency })} já acertados
                    </span>
                  )}
                </span>
                <span className={`shrink-0 whitespace-nowrap text-sm font-semibold ${classe}`}>
                  {texto}
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/70" />
              </button>
            </li>
          );
        })}

        {temAntigos && (
          /* Os meses além do teto da lista somados, não descartados: truncar em
             silêncio devolveria um total que não bate com as linhas. */
          <li className="flex items-center gap-3 px-3 py-2.5">
            <span className="min-w-0 flex-1 text-sm text-muted-foreground">
              {origem.older.count} {origem.older.count === 1 ? 'mês mais antigo' : 'meses mais antigos'}
            </span>
            <span
              className={`shrink-0 whitespace-nowrap text-sm font-semibold ${frase(origem.older.balance, currency).classe}`}
            >
              {frase(origem.older.balance, currency).texto}
            </span>
          </li>
        )}

        {temSemMes && (
          /* O acerto registrado a partir do saldo acumulado não carrega mês:
             derruba o total sem fechar mês nenhum. Antes isso não aparecia em
             lugar nenhum da tela, e o saldo caía "sozinho". */
          <li className="flex items-center gap-3 px-3 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block text-sm text-muted-foreground">Acertos sem mês</span>
              <span className="block text-[11px] text-muted-foreground">
                registrados sobre o acumulado, não sobre um mês
              </span>
            </span>
            <span
              className={`shrink-0 whitespace-nowrap text-sm font-semibold ${frase(origem.unassigned, currency).classe}`}
            >
              {frase(origem.unassigned, currency).texto}
            </span>
          </li>
        )}
      </ul>

      <div className="flex items-center gap-3 border-t-2 border-border bg-muted/40 px-3 py-2.5">
        <span className="min-w-0 flex-1 text-sm font-semibold text-foreground">Total acumulado</span>
        <span className={`shrink-0 whitespace-nowrap text-sm font-bold ${total.classe}`}>
          {total.texto}
        </span>
      </div>
    </div>
  );
}
