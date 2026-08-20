import { Button } from '@/components/ui/button';
import { HandCoins, Users } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import { Avatar } from '@/components/ui/avatar';
import { EmptyState } from '@/components/ui/empty-state';
import type { MemberLike } from '@/components/debts/MonthlyLedgerBody';

/**
 * Com quem eu me acerto — **uma linha por pessoa**, não dois cards por direção.
 *
 * Substitui o `BalanceCards`, que desenhava "Você deve" e "Você recebe" lado a
 * lado. Três razões, e a primeira é a que decide:
 *
 * 1. **Os rótulos repetiam os do topo da tela.** Ler "Você deve" como título de
 *    um card logo abaixo de um número chamado "Você deve" é o que fazia ninguém
 *    saber qual dos dois era o quê — foi a queixa que originou este redesenho.
 * 2. **Dentro de UM espaço, um dos dois cards está sempre vazio.** O pareamento
 *    de `_settle_balances` põe cada pessoa em UM lado só: quem tem saldo negativo
 *    é devedora de todas as linhas dela, quem tem positivo é credora. Metade do
 *    bloco era, por construção, um estado vazio.
 * 3. Altura. Na tela global isto se repete por espaço, e dois cards × N espaços
 *    empurravam o resto da página para fora da primeira dobra.
 *
 * A direção continua explícita — agora escrita na própria linha, junto do nome de
 * quem está do outro lado, que é a informação que se procura.
 */
export interface DebtLike {
  debtor_id: number;
  creditor_id: number;
  amount: string | number;
}

interface Props {
  debts: DebtLike[];
  currentUserId?: number;
  members: MemberLike[];
  canWrite: boolean;
  currency: string;
  onSettle: (debt: DebtLike) => void;
  /** Texto do estado vazio: na casa é "aqui"; na global, o nome dela. */
  escopo?: string;
  /** Estado vazio compacto — na tela global, um por espaço, o card grande
   *  ocuparia mais espaço do que a informação vale. */
  compacto?: boolean;
}

export function CounterpartyList({
  debts,
  currentUserId,
  members,
  canWrite,
  currency,
  onSettle,
  escopo,
  compacto = false,
}: Props) {
  const fmt = (v: string | number) => formatMoney(v, { currency });
  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;
  const memberAvatar = (id: number) => members.find((m) => m.user_id === id)?.avatar_version;

  const minhas = debts.filter(
    (d) => d.debtor_id === currentUserId || d.creditor_id === currentUserId,
  );
  const sufixo = escopo ? ` em ${escopo}` : '';

  if (minhas.length === 0) {
    const titulo = `Nada a acertar${sufixo}`;
    return compacto ? (
      <p className="rounded-xl border border-border bg-card px-3 py-4 text-center text-sm text-muted-foreground">
        {titulo}. 🎉
      </p>
    ) : (
      <EmptyState
        icon={Users}
        title={titulo}
        description="Quando uma despesa dividida deixar saldo entre você e outra pessoa, ela aparece aqui."
      />
    );
  }

  return (
    <ul className="space-y-2">
      {minhas.map((debt) => {
        const euDevo = debt.debtor_id === currentUserId;
        const outro = euDevo ? debt.creditor_id : debt.debtor_id;
        return (
          <li
            key={`${debt.debtor_id}-${debt.creditor_id}`}
            /*
             * `flex-wrap` + `min-w-0`: a 360px, avatar + nome + "você deve" +
             * um valor na casa dos milhões + botão não cabem numa linha. Com
             * `flex-wrap` o bloco do valor desce inteiro em vez de o número
             * quebrar no meio — truncar dinheiro nunca é opção.
             */
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border border-border bg-accent/30 p-3"
          >
            <div className="flex min-w-0 items-center gap-3">
              <Avatar
                name={memberName(outro)}
                userId={outro}
                version={memberAvatar(outro)}
                size="lg"
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-bold text-foreground">{memberName(outro)}</p>
                <p className="text-xs text-muted-foreground">
                  {euDevo ? 'você deve' : 'você recebe'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <p
                className={`whitespace-nowrap text-lg font-semibold ${
                  euDevo ? 'text-expense' : 'text-income'
                }`}
              >
                {fmt(debt.amount)}
              </p>
              <Button
                size="sm"
                variant={euDevo ? 'default' : 'outline'}
                disabled={!canWrite}
                onClick={() => onSettle(debt)}
                className="gap-1.5 font-bold"
              >
                <HandCoins className="h-3.5 w-3.5" /> {euDevo ? 'Paguei' : 'Recebi'}
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
