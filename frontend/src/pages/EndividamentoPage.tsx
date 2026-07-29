import * as React from 'react';
import { Link } from 'react-router-dom';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { StatTile } from '@/components/ui/stat-tile';
import { PageHeader } from '@/components/layout/PageHeader';
import { useLiabilities } from '@/hooks/use-liabilities';
import { useMembers } from '@/hooks/use-members';
import { useAuth } from '@/hooks/use-auth';
import { formatMoney } from '@/lib/money';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { currentMonthLocal, shiftMonth } from '@/lib/date';
import {
  ChevronLeft, ChevronRight, RefreshCcw, Loader2, CalendarDays,
  Landmark, CreditCard, Users, ArrowRight,
} from 'lucide-react';

function monthLabel(month: string) {
  const [y, m] = month.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
}

// Data só-dia (YYYY-MM-DD): monta local para não escorregar um dia no fuso -3.
function formatDay(iso: string | null) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('pt-BR');
}

export function EndividamentoPage() {
  const [month, setMonth] = React.useState(currentMonthLocal);
  const { overview, isLoading, isError, refetch } = useLiabilities(month);
  const { members } = useMembers();
  const { user } = useAuth();
  const baseCurrency = useBaseCurrency();
  const fmt = (value: number | string) => formatMoney(value, { currency: baseCurrency });

  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;
  const memberInitials = (id: number) => memberName(id).slice(0, 2).toUpperCase();

  const isCurrentMonth = month === currentMonthLocal();

  if (isLoading) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (isError || !overview) {
    return (
      <div className="rounded-xl border border-destructive/20 bg-destructive/10 p-12 text-center">
        <p className="text-sm font-bold text-destructive">Não foi possível carregar o panorama.</p>
        <Button variant="link" onClick={() => refetch()} className="mt-3 font-bold text-primary">
          Tentar novamente
        </Button>
      </div>
    );
  }

  const { totals, month_due, by_person, financings, cards } = overview;
  const nothingOwed = totals.grand_total <= 0 && financings.length === 0 && cards.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Endividamento"
        subtitle="Quanto você deve a bancos e cartões — no total, neste mês e por pessoa."
        action={
          <Button variant="outline" onClick={() => refetch()} className="gap-2">
            <RefreshCcw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      {nothingOwed ? (
        <div className="rounded-2xl border border-primary/10 bg-primary/5 p-12 text-center">
          <p className="text-sm font-bold text-foreground">Sem dívidas com bancos ou cartões. 🎉</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Financiamentos ativos e faturas em aberto aparecem aqui.
          </p>
          <div className="mt-4 flex items-center justify-center gap-3">
            <Link to="/financing" className="text-sm font-bold text-primary hover:underline">Financiamentos</Link>
            <span className="text-muted-foreground">·</span>
            <Link to="/cards" className="text-sm font-bold text-primary hover:underline">Cartões</Link>
          </div>
        </div>
      ) : (
        <>
          {/* Total devedor (independente do mês) */}
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile
              label="Devendo no total"
              value={totals.grand_total}
              kind={totals.grand_total > 0 ? 'expense' : 'neutral'}
              hint="Saldo devedor + faturas em aberto"
            />
            <StatTile
              label="Financiamentos"
              value={totals.financing_outstanding}
              kind={totals.financing_outstanding > 0 ? 'expense' : 'neutral'}
              icon={Landmark}
            />
            <StatTile
              label="Cartões"
              value={totals.cards_committed}
              kind={totals.cards_committed > 0 ? 'expense' : 'neutral'}
              icon={CreditCard}
            />
          </div>

          {/* O que vence no mês selecionado */}
          <Card className="border-border bg-card shadow-xl">
            <CardHeader className="space-y-4">
              <div className="flex flex-col gap-1">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <CalendarDays className="h-5 w-5 text-primary" />
                  O que vence no mês
                </CardTitle>
                <CardDescription>Parcelas de financiamento e faturas com vencimento no mês.</CardDescription>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-border bg-accent/30 p-2">
                <Button variant="ghost" size="icon" aria-label="Mês anterior" onClick={() => setMonth((m) => shiftMonth(m, -1))}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <div className="flex flex-col items-center">
                  <span className="text-sm font-black capitalize text-foreground">{monthLabel(month)}</span>
                  {!isCurrentMonth && (
                    <button
                      type="button"
                      onClick={() => setMonth(currentMonthLocal())}
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
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-accent/20 p-3">
                  <p className="text-[10px] font-semibold uppercase text-muted-foreground">Financiamento</p>
                  <p className="mt-0.5 text-sm font-black text-foreground">{fmt(month_due.financing_due)}</p>
                </div>
                <div className="rounded-lg bg-accent/20 p-3">
                  <p className="text-[10px] font-semibold uppercase text-muted-foreground">Cartão</p>
                  <p className="mt-0.5 text-sm font-black text-foreground">{fmt(month_due.cards_due)}</p>
                </div>
                <div className="rounded-lg bg-amber-500/10 p-3">
                  <p className="text-[10px] font-semibold uppercase text-muted-foreground">Total do mês</p>
                  <p className="mt-0.5 text-sm font-black text-amber-500">{fmt(month_due.total)}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Por pessoa (saldo devedor total atribuído) */}
          {by_person.length > 0 && (
            <Card className="border-border bg-card shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Users className="h-5 w-5 text-muted-foreground" />
                  Por pessoa
                </CardTitle>
                <CardDescription>
                  Financiamento vai para o dono; fatura de cartão é rateada pela divisão de cada compra.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {by_person.map((p) => {
                  const mine = p.user_id === user?.id;
                  return (
                    <div key={p.user_id} className="flex items-center justify-between rounded-xl border border-border bg-accent/30 p-3">
                      <div className="flex items-center gap-3">
                        <div className={`flex h-10 w-10 items-center justify-center rounded-full font-bold ${mine ? 'bg-primary/15 text-primary' : 'bg-primary/10 text-primary'}`}>
                          {memberInitials(p.user_id)}
                        </div>
                        <div>
                          <p className="text-sm font-bold text-foreground">{mine ? 'Você' : memberName(p.user_id)}</p>
                          <p className="flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
                            <span>Financ. {fmt(p.financing)}</span>
                            <span>·</span>
                            <span>Cartão {fmt(p.cards)}</span>
                          </p>
                        </div>
                      </div>
                      <p className="text-lg font-black text-foreground">{fmt(p.total)}</p>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          {/* Detalhe: financiamentos */}
          {financings.length > 0 && (
            <Card className="border-border bg-card shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Landmark className="h-5 w-5 text-muted-foreground" />
                  Financiamentos ativos
                </CardTitle>
                <CardDescription>Saldo devedor (principal) e próximo vencimento de cada um.</CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      <TableHead className="text-xs font-semibold text-muted-foreground">Financiamento</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Responsável</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Parcelas</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Próx. venc.</TableHead>
                      <TableHead className="text-right text-xs font-semibold text-muted-foreground">Saldo devedor</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {financings.map((f) => (
                      <TableRow key={f.id} className="border-border hover:bg-accent/30">
                        <TableCell className="font-bold">{f.title}</TableCell>
                        <TableCell className="text-muted-foreground">{memberName(f.owner_id)}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {f.remaining_installments} de {f.installments_count} restantes
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatDay(f.next_due_date)}</TableCell>
                        <TableCell className="text-right font-black text-foreground">{fmt(f.outstanding)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Detalhe: cartões */}
          {cards.length > 0 && (
            <Card className="border-border bg-card shadow-xl">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <CreditCard className="h-5 w-5 text-muted-foreground" />
                  Cartões
                </CardTitle>
                <CardDescription>Faturas em aberto (limite comprometido) por cartão.</CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border hover:bg-transparent">
                      <TableHead className="text-xs font-semibold text-muted-foreground">Cartão</TableHead>
                      <TableHead className="text-xs font-semibold text-muted-foreground">Vence no mês</TableHead>
                      <TableHead className="text-right text-xs font-semibold text-muted-foreground">Em aberto</TableHead>
                      <TableHead className="w-24"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {cards.map((c) => (
                      <TableRow key={c.id} className="border-border hover:bg-accent/30">
                        <TableCell className="font-bold">{c.name}</TableCell>
                        <TableCell className="text-muted-foreground">{fmt(c.month_due)}</TableCell>
                        <TableCell className="text-right font-black text-foreground">{fmt(c.committed)}</TableCell>
                        <TableCell className="text-right">
                          <Link to="/cards" className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline">
                            Ver <ArrowRight className="h-3 w-3" />
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
