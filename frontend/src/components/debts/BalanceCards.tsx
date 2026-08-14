import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowRight, HandCoins } from 'lucide-react';
import { formatMoney } from '@/lib/money';
import type { MemberLike } from '@/components/debts/MonthlyLedgerBody';

/**
 * O par "Você deve" / "Você recebe" — sem hook nenhum.
 *
 * Extraído de `DebtsPage` para a tela global de acertos (ADR 0027) desenhar um
 * par POR CASA, com os mesmos rótulos e as mesmas cores. Copiá-lo faria as duas
 * telas divergirem no primeiro ajuste de layout.
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
}

export function BalanceCards({
  debts,
  currentUserId,
  members,
  canWrite,
  currency,
  onSettle,
  escopo,
}: Props) {
  const fmt = (v: string | number) => formatMoney(v, { currency });
  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;
  const memberInitial = (id: number) => memberName(id)[0] ?? '?';

  const meusDebitos = debts.filter((d) => d.debtor_id === currentUserId);
  const meusCreditos = debts.filter((d) => d.creditor_id === currentUserId);
  const sufixo = escopo ? ` em ${escopo}` : '';

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card className="bg-card border-border shadow-xl border-l-4 border-l-destructive">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <div className="p-2 bg-destructive/10 rounded-lg">
              <ArrowRight className="h-4 w-4 text-destructive rotate-180" />
            </div>
            Você deve
          </CardTitle>
          <CardDescription>Pagamentos que você precisa fazer para outros membros.</CardDescription>
        </CardHeader>
        <CardContent>
          {meusDebitos.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              Você não deve nada a ninguém{sufixo}! 🎉
            </p>
          ) : (
            <div className="space-y-4">
              {meusDebitos.map((debt) => (
                <div key={`${debt.debtor_id}-${debt.creditor_id}`} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary">
                      {memberInitial(debt.creditor_id)}
                    </div>
                    <div>
                      <p className="text-sm font-bold">{memberName(debt.creditor_id)}</p>
                      <p className="text-[10px] text-muted-foreground uppercase font-semibold">Credor</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <p className="text-lg font-semibold text-destructive">{fmt(debt.amount)}</p>
                    <Button size="sm" disabled={!canWrite} onClick={() => onSettle(debt)} className="gap-1.5 bg-primary text-primary-foreground font-bold">
                      <HandCoins className="h-3.5 w-3.5" /> Paguei
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="bg-card border-border shadow-xl border-l-4 border-l-emerald-500">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <div className="p-2 bg-emerald-500/10 rounded-lg">
              <ArrowRight className="h-4 w-4 text-emerald-500" />
            </div>
            Você recebe
          </CardTitle>
          <CardDescription>Pagamentos que outros membros devem fazer para você.</CardDescription>
        </CardHeader>
        <CardContent>
          {meusCreditos.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              Ninguém te deve nada{sufixo} no momento.
            </p>
          ) : (
            <div className="space-y-4">
              {meusCreditos.map((debt) => (
                <div key={`${debt.debtor_id}-${debt.creditor_id}`} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary">
                      {memberInitial(debt.debtor_id)}
                    </div>
                    <div>
                      <p className="text-sm font-bold">{memberName(debt.debtor_id)}</p>
                      <p className="text-[10px] text-muted-foreground uppercase font-semibold">Devedor</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <p className="text-lg font-semibold text-emerald-500">{fmt(debt.amount)}</p>
                    <Button size="sm" variant="outline" disabled={!canWrite} onClick={() => onSettle(debt)} className="gap-1.5 border-emerald-500/40 text-emerald-500 font-bold hover:bg-emerald-500/10">
                      <HandCoins className="h-3.5 w-3.5" /> Recebi
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
