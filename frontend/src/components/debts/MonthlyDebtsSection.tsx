import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, HandCoins, Loader2, CalendarDays } from 'lucide-react';
import { useMonthlyDebts } from '@/hooks/use-monthly-debts';
import type { SettlementDraft } from '@/components/debts/SettlementDialog';

interface MemberLike {
  user_id: number;
  user_name?: string;
}

interface MonthlyDebtsSectionProps {
  members: MemberLike[];
  currentUserId?: number;
  canWrite: boolean;
  onSettle: (draft: SettlementDraft) => void;
}

const formatBRL = (value: number | string) =>
  `R$ ${Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;

function monthLabel(month: string) {
  const [y, m] = month.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
}

function shiftMonth(month: string, delta: number) {
  const [y, m] = month.split('-').map(Number);
  return new Date(y, m - 1 + delta, 1).toISOString().slice(0, 7);
}

export function MonthlyDebtsSection({ members, currentUserId, canWrite, onSettle }: MonthlyDebtsSectionProps) {
  const [month, setMonth] = React.useState(() => new Date().toISOString().slice(0, 7));
  const { ledger, isLoading } = useMonthlyDebts(month);

  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;
  const memberInitials = (id: number) => memberName(id).slice(0, 2).toUpperCase();

  const isCurrentMonth = month === new Date().toISOString().slice(0, 7);

  return (
    <Card className="bg-card border-border shadow-xl">
      <CardHeader className="space-y-4">
        <div className="flex flex-col gap-1">
          <CardTitle className="text-lg flex items-center gap-2">
            <CalendarDays className="h-5 w-5 text-primary" />
            Dívidas do mês
          </CardTitle>
          <CardDescription>
            Cada parcela aparece só no mês dela — veja o que cada um deve e se já foi pago.
          </CardDescription>
        </div>

        {/* Navegador de mês */}
        <div className="flex items-center justify-between rounded-xl bg-accent/30 border border-border p-2">
          <Button variant="ghost" size="icon" aria-label="Mês anterior" onClick={() => setMonth((m) => shiftMonth(m, -1))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="flex flex-col items-center">
            <span className="text-sm font-black capitalize text-foreground">{monthLabel(month)}</span>
            {!isCurrentMonth && (
              <button
                type="button"
                onClick={() => setMonth(new Date().toISOString().slice(0, 7))}
                className="text-[10px] font-bold text-primary hover:underline"
              >
                voltar para o mês atual
              </button>
            )}
          </div>
          <Button variant="ghost" size="icon" aria-label="Próximo mês" onClick={() => setMonth((m) => shiftMonth(m, 1))}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        {/* Totais do mês */}
        {ledger && (
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-accent/20 p-2">
              <p className="text-[10px] font-black uppercase text-muted-foreground">Total do mês</p>
              <p className="text-sm font-black text-foreground">{formatBRL(ledger.totals.total)}</p>
            </div>
            <div className="rounded-lg bg-emerald-500/10 p-2">
              <p className="text-[10px] font-black uppercase text-muted-foreground">Pago</p>
              <p className="text-sm font-black text-emerald-500">{formatBRL(ledger.totals.paid)}</p>
            </div>
            <div className="rounded-lg bg-amber-500/10 p-2">
              <p className="text-[10px] font-black uppercase text-muted-foreground">Em aberto</p>
              <p className="text-sm font-black text-amber-500">{formatBRL(ledger.totals.open)}</p>
            </div>
          </div>
        )}
      </CardHeader>

      <CardContent className="space-y-6">
        {isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : !ledger || ledger.expenses.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Nenhuma despesa neste mês.
          </p>
        ) : (
          <>
            {/* Quem deve quem NO MÊS */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-black uppercase tracking-wider text-muted-foreground">Acertos do mês</p>
                {ledger.settled_total > 0 && (
                  <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-black uppercase text-emerald-500">
                    {formatBRL(ledger.settled_total)} pago
                  </span>
                )}
              </div>
              {ledger.net_debts.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {ledger.settled_total > 0 ? 'Tudo acertado neste mês. ✅' : 'Ninguém deve nada neste mês. 🎉'}
                </p>
              ) : (
                <div className="space-y-2">
                  {ledger.net_debts.map((d, idx) => (
                    <div key={idx} className="flex items-center justify-between rounded-xl bg-accent/30 border border-border p-3">
                      <p className="text-sm">
                        <span className="font-bold">{memberName(d.debtor_id)}</span>
                        <span className="text-muted-foreground"> deve </span>
                        <span className="font-black text-destructive">{formatBRL(d.amount)}</span>
                        <span className="text-muted-foreground"> a </span>
                        <span className="font-bold">{memberName(d.creditor_id)}</span>
                      </p>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!canWrite}
                        onClick={() => onSettle({ from_user_id: d.debtor_id, to_user_id: d.creditor_id, amount: Number(d.amount), billing_month: month })}
                        className="gap-1.5 font-bold"
                      >
                        <HandCoins className="h-3.5 w-3.5" /> Registrar
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {/* Acertos já registrados para este mês — deixa claro quem pagou */}
              {ledger.settlements.length > 0 && (
                <div className="space-y-1 pt-1">
                  {ledger.settlements.map((s) => (
                    <p key={s.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <HandCoins className="h-3 w-3 shrink-0 text-emerald-500" />
                      <span className="font-bold text-foreground">{memberName(s.from_user_id)}</span> pagou{' '}
                      <span className="font-black text-emerald-500">{formatBRL(s.amount)}</span> a{' '}
                      <span className="font-bold text-foreground">{memberName(s.to_user_id)}</span>
                    </p>
                  ))}
                </div>
              )}
            </div>

            {/* Detalhe das despesas do mês */}
            <div className="space-y-2">
              <p className="text-[11px] font-black uppercase tracking-wider text-muted-foreground">Despesas do mês</p>
              <Table>
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    <TableHead className="text-[10px] font-black uppercase tracking-wider text-muted-foreground">Despesa</TableHead>
                    <TableHead className="text-[10px] font-black uppercase tracking-wider text-muted-foreground">Quem pagou</TableHead>
                    <TableHead className="text-[10px] font-black uppercase tracking-wider text-muted-foreground">Divisão</TableHead>
                    <TableHead className="text-center text-[10px] font-black uppercase tracking-wider text-muted-foreground">Status</TableHead>
                    <TableHead className="text-right text-[10px] font-black uppercase tracking-wider text-muted-foreground">Valor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ledger.expenses.map((exp) => (
                    <TableRow key={exp.id} className="border-border hover:bg-accent/30">
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <span className="text-sm font-bold text-foreground">{exp.title}</span>
                          {exp.installments_of && exp.installments_of > 1 && (
                            <span className="w-fit rounded-full bg-primary/10 px-1.5 py-0.5 text-[9px] font-black uppercase text-primary">
                              Parcela {exp.installment_no}/{exp.installments_of}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                          {exp.payers.map((p, i) => (
                            <span key={i}>
                              {memberName(p.user_id)} · {formatBRL(p.amount)}
                            </span>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {exp.splits.map((s, i) => {
                            const mine = s.user_id === currentUserId;
                            return (
                              <span
                                key={i}
                                title={`${memberName(s.user_id)} — ${formatBRL(s.computed_amount)}`}
                                className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-bold ${
                                  mine
                                    ? 'border-primary/40 bg-primary/15 text-primary'
                                    : 'border-border bg-accent/40 text-muted-foreground'
                                }`}
                              >
                                {mine ? 'Você' : memberInitials(s.user_id)} · {formatBRL(s.computed_amount)}
                              </span>
                            );
                          })}
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        {exp.is_paid ? (
                          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-black uppercase text-emerald-500">Paga</span>
                        ) : (
                          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-black uppercase text-amber-500">Em aberto</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-black text-foreground">{formatBRL(exp.total_amount)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
