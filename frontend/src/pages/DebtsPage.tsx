import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useDebts } from '@/hooks/use-debts';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { ArrowRight, Users, Loader2, RefreshCcw, Landmark, HandCoins, History, Trash2 } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { useMembers } from '@/hooks/use-members';
import { useSettlements } from '@/hooks/use-settlements';
import { SettlementDialog, type SettlementDraft } from '@/components/debts/SettlementDialog';
import { MonthlyDebtsSection } from '@/components/debts/MonthlyDebtsSection';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { PageHeader } from '@/components/layout/PageHeader';
import { StatTile } from '@/components/ui/stat-tile';

interface Debt {
  debtor_id: number;
  creditor_id: number;
  amount: string;
}

const formatBRL = (value: string | number) =>
  `R$ ${parseFloat(String(value)).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;

export function DebtsPage() {
  const { debts, isLoading, isError, refetch } = useDebts();
  const { user } = useAuth();
  const { canWrite } = useWorkspaceRole();  // viewer não registra/desfaz acertos (RBAC-FE-001)
  const { members } = useMembers();
  const { settlements, remove } = useSettlements();
  const confirm = useConfirm();
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<SettlementDraft | null>(null);

  const memberName = (id: number) =>
    members.find((m) => m.user_id === id)?.user_name ?? `Membro #${id}`;
  const memberInitial = (id: number) => memberName(id)[0] ?? '?';

  const openSettlement = (debt: Debt) => {
    setDraft({
      from_user_id: debt.debtor_id,
      to_user_id: debt.creditor_id,
      amount: parseFloat(debt.amount),
    });
    setDialogOpen(true);
  };

  const undoSettlement = async (id: number) => {
    const ok = await confirm({
      title: 'Desfazer acerto',
      description: 'Desfazer este acerto? A dívida correspondente volta ao balanço.',
      confirmLabel: 'Desfazer',
      destructive: true,
    });
    if (!ok) return;
    try {
      await remove(id);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao desfazer o acerto.'));
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Estado de erro explícito (ERR-001): falha não pode parecer "sem dívidas"
  if (isError) {
    return (
      <div className="p-12 text-center rounded-xl bg-destructive/10 border border-destructive/20">
        <p className="text-sm font-bold text-destructive">Não foi possível carregar as dívidas.</p>
        <Button variant="link" onClick={() => refetch()} className="mt-3 text-primary font-bold">
          Tentar novamente
        </Button>
      </div>
    );
  }

  const typedDebts = debts as Debt[];
  const myDebts = typedDebts.filter((d) => d.debtor_id === user?.id);
  const myCredits = typedDebts.filter((d) => d.creditor_id === user?.id);
  const otherDebts = typedDebts.filter((d) => d.debtor_id !== user?.id && d.creditor_id !== user?.id);

  const totalOwed = myDebts.reduce((a, d) => a + parseFloat(d.amount), 0);
  const totalCredit = myCredits.reduce((a, d) => a + parseFloat(d.amount), 0);
  const netBalance = totalCredit - totalOwed;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dívidas & acertos"
        subtitle="Quem deve para quem — e os acertos já feitos."
        action={
          <Button variant="outline" onClick={() => refetch()} className="gap-2">
            <RefreshCcw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Você deve" value={totalOwed} kind={totalOwed > 0 ? 'expense' : 'neutral'} />
        <StatTile label="Você recebe" value={totalCredit} kind={totalCredit > 0 ? 'income' : 'neutral'} />
        <StatTile
          label="Saldo líquido"
          value={netBalance}
          kind={netBalance > 0 ? 'income' : netBalance < 0 ? 'expense' : 'neutral'}
          hint={netBalance === 0 ? 'Tudo certo por aqui' : netBalance > 0 ? 'a receber, no total' : 'a pagar, no total'}
        />
      </div>

      {/* Dívidas mês a mês: parcelas aparecem no mês delas, com status */}
      <MonthlyDebtsSection
        members={members}
        currentUserId={user?.id}
        canWrite={canWrite}
        onSettle={(draft) => {
          setDraft(draft);
          setDialogOpen(true);
        }}
      />

      <div className="space-y-1">
        <h3 className="text-lg font-bold tracking-tight text-foreground">Saldo geral a acertar</h3>
        <p className="text-sm text-muted-foreground">Balanço consolidado de todos os meses, já descontando os acertos.</p>
      </div>

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
            {myDebts.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">Você não deve nada a ninguém! 🎉</p>
            ) : (
              <div className="space-y-4">
                {myDebts.map((debt, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary">
                        {memberInitial(debt.creditor_id)}
                      </div>
                      <div>
                        <p className="text-sm font-bold">{memberName(debt.creditor_id)}</p>
                        <p className="text-[10px] text-muted-foreground uppercase font-black">Credor</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <p className="text-lg font-black text-destructive">{formatBRL(debt.amount)}</p>
                      <Button size="sm" disabled={!canWrite} onClick={() => openSettlement(debt)} className="gap-1.5 bg-primary text-primary-foreground font-bold">
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
            {myCredits.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">Ninguém te deve nada no momento.</p>
            ) : (
              <div className="space-y-4">
                {myCredits.map((debt, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 rounded-xl bg-accent/30 border border-border">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary">
                        {memberInitial(debt.debtor_id)}
                      </div>
                      <div>
                        <p className="text-sm font-bold">{memberName(debt.debtor_id)}</p>
                        <p className="text-[10px] text-muted-foreground uppercase font-black">Devedor</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <p className="text-lg font-black text-emerald-500">{formatBRL(debt.amount)}</p>
                      <Button size="sm" variant="outline" disabled={!canWrite} onClick={() => openSettlement(debt)} className="gap-1.5 border-emerald-500/40 text-emerald-500 font-bold hover:bg-emerald-500/10">
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

      {otherDebts.length > 0 && (
        <Card className="bg-card border-border shadow-xl">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Users className="h-5 w-5 text-muted-foreground" />
              Outros Acertos
            </CardTitle>
            <CardDescription>Dívidas entre outros membros do workspace.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Devedor</TableHead>
                  <TableHead className="text-center w-12"></TableHead>
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Credor</TableHead>
                  <TableHead className="text-right text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Valor</TableHead>
                  <TableHead className="w-32"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {otherDebts.map((debt, idx) => (
                  <TableRow key={idx} className="border-border hover:bg-accent/30">
                    <TableCell className="font-bold">{memberName(debt.debtor_id)}</TableCell>
                    <TableCell className="text-center">
                      <ArrowRight className="h-4 w-4 text-muted-foreground inline" />
                    </TableCell>
                    <TableCell className="font-bold">{memberName(debt.creditor_id)}</TableCell>
                    <TableCell className="text-right font-black">{formatBRL(debt.amount)}</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" disabled={!canWrite} onClick={() => openSettlement(debt)} className="gap-1.5 text-primary hover:bg-primary/10 font-bold">
                        <HandCoins className="h-3.5 w-3.5" /> Registrar
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <History className="h-5 w-5 text-muted-foreground" />
            Histórico de acertos
          </CardTitle>
          <CardDescription>Pagamentos já registrados — desfaça um acerto para devolvê-lo ao balanço.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {settlements.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">Nenhum acerto registrado ainda.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Data</TableHead>
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Pagou</TableHead>
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Recebeu</TableHead>
                  <TableHead className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Obs.</TableHead>
                  <TableHead className="text-right text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Valor</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {settlements.map((s) => (
                  <TableRow key={s.id} className="border-border hover:bg-accent/30">
                    <TableCell className="text-xs">{new Date(s.settled_at).toLocaleDateString('pt-BR')}</TableCell>
                    <TableCell className="font-bold">{memberName(s.from_user_id)}</TableCell>
                    <TableCell className="font-bold">{memberName(s.to_user_id)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.note || '—'}</TableCell>
                    <TableCell className="text-right font-black text-emerald-500">{formatBRL(s.amount)}</TableCell>
                    <TableCell className="text-center">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label="Desfazer acerto"
                        disabled={!canWrite} onClick={() => undoSettlement(s.id)}
                        className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="p-6 rounded-2xl bg-primary/5 border border-primary/10 flex items-start gap-4">
        <div className="p-2 bg-primary/10 rounded-xl">
          <Landmark className="h-6 w-6 text-primary" />
        </div>
        <div className="space-y-1">
          <h4 className="font-bold text-foreground">Como os acertos funcionam?</h4>
          <p className="text-sm text-muted-foreground leading-relaxed">
            O sistema calcula quem pagou a mais e quem pagou a menos baseando-se nas divisões de cada transação.
            Faça o pagamento (Pix, dinheiro...) e registre aqui: o valor é abatido do balanço na hora,
            e o histórico guarda quem acertou o quê.
          </p>
        </div>
      </div>

      <SettlementDialog open={dialogOpen} onOpenChange={setDialogOpen} draft={draft} members={members} />
    </div>
  );
}
