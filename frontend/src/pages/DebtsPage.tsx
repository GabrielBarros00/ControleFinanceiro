import * as React from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useDebts } from '@/hooks/use-debts';
import { useBaseCurrency } from '@/hooks/use-base-currency';
import { useWorkspaceRole } from '@/hooks/use-workspace-role';
import { formatMoney } from '@/lib/money';
import { ArrowRight, Users, Loader2, RefreshCcw, Landmark, HandCoins, History, Trash2, Globe } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { useMembers } from '@/hooks/use-members';
import { useSettlements } from '@/hooks/use-settlements';
import { SettlementDialog, type SettlementDraft } from '@/components/debts/SettlementDialog';
import { BalanceCards } from '@/components/debts/BalanceCards';
import { MonthlyDebtsSection } from '@/components/debts/MonthlyDebtsSection';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { PageHeader } from '@/components/layout/PageHeader';
import { StatTile } from '@/components/ui/stat-tile';
import { parseApiDate } from '@/lib/date';

interface Debt {
  debtor_id: number;
  creditor_id: number;
  amount: string;
}


export function DebtsPage() {
  // Moeda-base do workspace: o backend soma nela, a tela precisa dizer qual é.
  const baseCurrency = useBaseCurrency();
  const formatBRL = (value: string | number) => formatMoney(value, { currency: baseCurrency });
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

  const openSettlement = (debt: { debtor_id: number; creditor_id: number; amount: string | number }) => {
    setDraft({
      from_user_id: debt.debtor_id,
      to_user_id: debt.creditor_id,
      amount: Number(debt.amount),
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
      <div className="flex h-[240px] items-center justify-center sm:h-[400px]">
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
      {/* O ESCOPO tem de estar no cabeçalho: sem ele, quem participa de dois
          espaços lê estes números como se fossem o total dela — e eles nunca
          foram. O total mora em Seus acertos.
          Antes isso era feito concatenando o nome no título (`Acertos · Casa`),
          o que dava um cabeçalho que não batia com o item de navegação
          ("Acertos") e repetia, em 28px, o nome que a barra do topo já mostra.
          A pílula diz a mesma coisa e ainda nomeia o que aquilo é. */}
      <PageHeader
        title="Acertos"
        scope="workspace"
        subtitle="Somente este espaço. Seus acertos de todos os espaços ficam em Pessoal › Seus acertos."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/me/settlements">
              <Button variant="outline" className="gap-2">
                <Globe className="h-4 w-4" /> Ver todos os espaços
              </Button>
            </Link>
            <Button variant="outline" onClick={() => refetch()} className="gap-2">
              <RefreshCcw className="h-4 w-4" /> Atualizar
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
        <StatTile
          label="Você deve"
          value={totalOwed}
          kind={totalOwed > 0 ? 'expense' : 'neutral'}
          currency={baseCurrency}
          hint="Neste espaço"
        />
        <StatTile
          label="Você recebe"
          value={totalCredit}
          kind={totalCredit > 0 ? 'income' : 'neutral'}
          currency={baseCurrency}
          hint="Neste espaço"
        />
        <StatTile
          label="Saldo líquido"
          value={netBalance}
          kind={netBalance > 0 ? 'income' : netBalance < 0 ? 'expense' : 'neutral'}
          currency={baseCurrency}
          // Líquido DENTRO da casa é legítimo: são as mesmas pessoas e o mesmo
          // acordo. Entre casas não é, e por isso a tela global não tem este
          // número (ADR 0020).
          hint={netBalance === 0 ? 'Tudo certo neste espaço' : netBalance > 0 ? 'a receber neste espaço' : 'a pagar neste espaço'}
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
        <p className="text-sm text-muted-foreground">Todos os meses deste espaço, já descontando os acertos.</p>
      </div>

      <BalanceCards
        debts={typedDebts}
        currentUserId={user?.id}
        members={members}
        canWrite={canWrite}
        currency={baseCurrency}
        onSettle={openSettlement}
      />

      {otherDebts.length > 0 && (
        <Card className="bg-card border-border shadow-xl">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Users className="h-5 w-5 text-muted-foreground" />
              Outros Acertos
            </CardTitle>
            <CardDescription>Dívidas entre outros membros deste espaço.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground font-semibold text-xs">Devedor</TableHead>
                  <TableHead className="text-center w-12"></TableHead>
                  <TableHead className="text-muted-foreground font-semibold text-xs">Credor</TableHead>
                  <TableHead className="text-right text-muted-foreground font-semibold text-xs">Valor</TableHead>
                  <TableHead className="w-32"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {otherDebts.map((debt) => (
                  <TableRow key={`${debt.debtor_id}-${debt.creditor_id}`} className="border-border hover:bg-accent/30">
                    <TableCell className="font-bold">{memberName(debt.debtor_id)}</TableCell>
                    <TableCell className="text-center">
                      <ArrowRight className="h-4 w-4 text-muted-foreground inline" />
                    </TableCell>
                    <TableCell className="font-bold">{memberName(debt.creditor_id)}</TableCell>
                    <TableCell className="text-right font-semibold whitespace-nowrap">{formatBRL(debt.amount)}</TableCell>
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
                  <TableHead className="text-muted-foreground font-semibold text-xs">Data</TableHead>
                  <TableHead className="text-muted-foreground font-semibold text-xs">Pagou</TableHead>
                  <TableHead className="text-muted-foreground font-semibold text-xs">Recebeu</TableHead>
                  <TableHead className="text-muted-foreground font-semibold text-xs">Obs.</TableHead>
                  <TableHead className="text-right text-muted-foreground font-semibold text-xs">Valor</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {settlements.map((s) => (
                  <TableRow key={s.id} className="border-border hover:bg-accent/30">
                    <TableCell className="text-xs whitespace-nowrap">{parseApiDate(s.settled_at).toLocaleDateString('pt-BR')}</TableCell>
                    <TableCell className="font-bold">{memberName(s.from_user_id)}</TableCell>
                    <TableCell className="font-bold">{memberName(s.to_user_id)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{s.note || '—'}</TableCell>
                    <TableCell className="text-right font-semibold whitespace-nowrap text-emerald-500">{formatBRL(s.amount)}</TableCell>
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
