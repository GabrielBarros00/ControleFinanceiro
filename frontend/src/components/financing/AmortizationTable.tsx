import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { StatusPill } from "@/components/ui/status-pill";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MoneyInput } from "@/components/ui/MoneyInput";
import { ChevronLeft, ChevronRight, Loader2, Trash2 } from 'lucide-react';
import { useFinancing, useFinancingSchedule, type Financing } from '@/hooks/use-financing';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useReportCurrency } from '@/hooks/use-report-currency';
import { CurrencyCombobox } from '@/components/dashboard/transaction-form/CurrencyCombobox';
import { currencySymbol, formatMoney } from '@/lib/money';
import { toast } from '@/stores/toast';
import { useConfirm } from '@/components/ui/confirm';
import { parseApiDate, todayLocalISO } from '@/lib/date';
import { nativeSelectClass } from '@/components/ui/native-select';
import { CardsOrTable, DataCard } from '@/components/ui/data-card';
import { NumberInput } from '@/components/ui/NumberInput';

// Base UI Select abre num portal fora do focus-trap do Dialog (Radix) e fecha
// na hora — dentro de diálogos usamos <select> nativo (mesmo padrão de
// SettlementDialog/RecurringTransactionsPage/PaymentMethodField).
const selectClass = `${nativeSelectClass} font-semibold`;

// Um ano por página: o recorte natural de um cronograma de amortização
const PARCELAS_POR_PAGINA = 12;

/**
 * Pagar parcela — com a opção de LANÇAR A DESPESA num workspace.
 *
 * O backend aceita `workspace_id` neste endpoint desde que a rota existe, e a
 * interface nunca o enviava: pagar uma parcela só reduzia Compromissos e o gasto
 * não aparecia em relatório nenhum. Quem divide o financiamento com alguém não
 * tinha como registrar isso pela tela.
 *
 * O padrão é "não lançar": o financiamento é compromisso pessoal (ADR 0021) e a
 * maioria dos pagamentos não é despesa de casa nenhuma. Quem quer, escolhe.
 */
function PagarParcelaDialog({
  open,
  onOpenChange,
  financing,
  installmentNumber,
  valor,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  financing: Financing;
  installmentNumber: number | null;
  valor: string;
}) {
  const { payInstallment } = useFinancing();
  const { workspaces } = useWorkspaces();
  const [workspaceId, setWorkspaceId] = React.useState('');
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (open) setWorkspaceId('');
  }, [open]);

  if (installmentNumber === null) return null;

  const confirmar = async () => {
    setSaving(true);
    try {
      await payInstallment({
        financingId: financing.id,
        installmentNumber,
        workspaceId: workspaceId ? Number(workspaceId) : null,
      });
      toast.success(
        workspaceId
          ? 'Parcela paga e lançada como despesa.'
          : 'Parcela paga.',
      );
      onOpenChange(false);
    } catch {
      toast.error('Erro ao pagar parcela.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pagar parcela {installmentNumber}</DialogTitle>
          <DialogDescription>
            {valor} — sai dos seus Compromissos e entra no caixa do mês.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="pagar-parcela-ws">Lançar como despesa em</Label>
          <select
            id="pagar-parcela-ws"
            className={selectClass}
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
          >
            <option value="">Não lançar (só compromisso pessoal)</option>
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>{ws.name}</option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Escolhendo um espaço, a parcela vira um lançamento lá — e entra nos
            relatórios dele. Sem escolher, o pagamento fica só seu.
          </p>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="button" onClick={confirmar} disabled={saving} className="px-8 font-bold">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Pagar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CreateFinancingDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { create } = useFinancing();
  // Criando, vale a moeda de RELATÓRIO do dono — é com ela que o backend
  // (`resolve_personal_currency`) vai gravar o contrato. A moeda-base do
  // workspace prometia uma coisa e o backend gravava outra.
  const reportCurrency = useReportCurrency();
  const [title, setTitle] = React.useState('');
  const [totalAmount, setTotalAmount] = React.useState(0);
  // A moeda do CONTRATO, não a de visualização: um financiamento assinado em
  // dólar continua em dólar quando os relatórios passam a ser em real. Sem o
  // campo, ele nascia com a moeda de relatório ativa no momento da criação.
  const [currency, setCurrency] = React.useState(reportCurrency);
  const [interestRate, setInterestRate] = React.useState('1.00'); // % ao mês
  const [installments, setInstallments] = React.useState(12);
  const [method, setMethod] = React.useState<'SAC' | 'PRICE'>('SAC');
  const [startDate, setStartDate] = React.useState(todayLocalISO);
  /**
   * Parcelamento SEM JUROS (ADR 0030) — mensalidade de faculdade, curso, plano
   * anual dividido. O cronograma já sabia lidar com taxa zero (o `else` explícito
   * do PRICE em `FinancingService`); o que faltava era a porta de entrada. Sem
   * ela, quem tem 144 mensalidades iguais a pagar era recebido por "Juros (% ao
   * mês)", "SAC" e "PRICE" — vocabulário de empréstimo para o que não é um.
   */
  const [semJuros, setSemJuros] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handleCreate = async () => {
    if (!title.trim() || totalAmount <= 0 || installments < 1) {
      setError('Preencha título, valor e parcelas.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await create({
        title: title.trim(),
        total_amount: String(totalAmount),
        // Sem juros: taxa zero e PRICE, que com taxa zero é exatamente
        // "total ÷ N" — parcelas iguais que somam o total, ao centavo.
        interest_rate: semJuros ? '0' : String(Number(interestRate.replace(',', '.')) / 100),
        start_date: startDate,
        installments_count: installments,
        method: semJuros ? 'PRICE' : method,
        currency,
      });
      onOpenChange(false);
      setTitle(''); setTotalAmount(0); setInterestRate('1.00'); setInstallments(12);
      setSemJuros(false);
      setCurrency(reportCurrency);
    } catch {
      setError('Erro ao criar financiamento.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{semJuros ? 'Novo parcelamento' : 'Novo Financiamento'}</DialogTitle>
          <DialogDescription>
            {semJuros
              ? 'Parcelas iguais, sem juros — mensalidade, curso, plano dividido.'
              : 'O cronograma de amortização é gerado automaticamente.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="financing-kind">Tipo</Label>
            <select
              id="financing-kind"
              value={semJuros ? 'sem-juros' : 'com-juros'}
              onChange={(e) => setSemJuros(e.target.value === 'sem-juros')}
              className={selectClass}
            >
              <option value="com-juros" className="bg-card">Financiamento (com juros)</option>
              <option value="sem-juros" className="bg-card">Parcelamento sem juros</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label>Título</Label>
            <Input
              placeholder={semJuros ? 'Ex: Faculdade, Curso...' : 'Ex: Apartamento, Carro...'}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="bg-background/50"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>{semJuros ? 'Valor total' : 'Valor Financiado'}</Label>
              <MoneyInput value={totalAmount} onChange={setTotalAmount} prefix={currencySymbol(currency)} className="bg-background/50" />
            </div>
            {/* Juros e sistema de amortização somem no modo sem juros: são o
                vocabulário de empréstimo, e uma mensalidade não é um. */}
            {!semJuros && (
              <div className="space-y-2">
                <Label>Juros (% ao mês)</Label>
                <Input type="text" inputMode="decimal" value={interestRate} onChange={(e) => setInterestRate(e.target.value)} className="bg-background/50" />
              </div>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="financing-currency">Moeda do contrato</Label>
            <CurrencyCombobox
              id="financing-currency"
              ariaLabel="Moeda do contrato"
              value={currency}
              onChange={setCurrency}
            />
          </div>
          <div className={`grid grid-cols-1 gap-4 ${semJuros ? 'sm:grid-cols-2' : 'sm:grid-cols-3'}`}>
            <div className="space-y-2">
              <Label>Parcelas</Label>
              <NumberInput aria-label="Número de parcelas" min={1} max={600} padraoAoSair={12} value={installments} onChange={(v) => setInstallments(v ?? 12)} className="bg-background/50" />
              {semJuros && totalAmount > 0 && installments > 0 && (
                <p className="text-[11px] text-muted-foreground">
                  {installments}× de{' '}
                  {formatMoney(totalAmount / installments, { currency })}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label>Início</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-background/50" />
            </div>
            {!semJuros && (
              <div className="space-y-2">
                <Label>Sistema</Label>
                <select
                  value={method}
                  onChange={(e) => setMethod(e.target.value as 'SAC' | 'PRICE')}
                  className={selectClass}
                >
                  <option value="SAC" className="bg-card">SAC</option>
                  <option value="PRICE" className="bg-card">PRICE</option>
                </select>
              </div>
            )}
          </div>
          {error && <p className="text-xs text-destructive font-medium">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="button" onClick={handleCreate} disabled={saving} className="bg-primary font-bold px-8">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Criar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FinancingDetail({ financing }: { financing: Financing }) {
  const { schedule, settlement } = useFinancingSchedule(financing.id);
  // A moeda é DO CONTRATO, não do workspace aberto: o financiamento é pessoal
  // (ADR 0021) e não muda de denominação porque o usuário trocou de casa.
  const fmt = (value: number | string) =>
    formatMoney(value, { currency: financing.currency });
  // Número da parcela em pagamento (o diálogo pergunta se ela vira despesa).
  const [pagando, setPagando] = React.useState<number | null>(null);

  const unpaid = schedule.filter((i) => !i.is_paid);
  const nextInstallment = unpaid[0] ?? null;
  const remainingBalance = nextInstallment
    ? parseFloat(unpaid[0].remaining_balance) + parseFloat(unpaid[0].principal_amount)
    : 0;
  const paidCount = schedule.length - unpaid.length;
  const progress = schedule.length > 0 ? (paidCount / schedule.length) * 100 : 0;

  // Paginação de 12 em 12 (um ano por página): um financiamento de 30 anos são
  // 360 linhas: a página passava de 7.000px e o usuário rolava por um cronograma
  // inteiro para achar a parcela do mês.
  const totalPages = Math.max(1, Math.ceil(schedule.length / PARCELAS_POR_PAGINA));
  const [page, setPage] = React.useState(0);

  // Abre na página da PRÓXIMA parcela — é a que interessa (e a única com o botão
  // "Pagar"). Reancora quando o cronograma muda (trocar de financiamento, pagar).
  const nextNumber = nextInstallment?.installment_number;
  React.useEffect(() => {
    const alvo = nextNumber ? Math.floor((nextNumber - 1) / PARCELAS_POR_PAGINA) : 0;
    setPage(Math.min(alvo, totalPages - 1));
  }, [nextNumber, totalPages]);

  const pageSafe = Math.min(page, totalPages - 1);
  const inicio = pageSafe * PARCELAS_POR_PAGINA;
  const visiveis = schedule.slice(inicio, inicio + PARCELAS_POR_PAGINA);

  return (
    <div className="space-y-8">
      <div className="grid gap-6 md:grid-cols-3">
        <Card className="bg-card border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-normal text-muted-foreground">Saldo devedor</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">{fmt(remainingBalance)}</div>
            <Progress value={progress} className="h-1 mt-3" />
            <p className="text-xs text-muted-foreground mt-2">{paidCount} de {schedule.length} parcelas pagas</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-normal text-muted-foreground">Próxima parcela</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold">
              {nextInstallment ? fmt(nextInstallment.total_amount) : '—'}
            </div>
            {nextInstallment && (
              <p className="text-xs text-muted-foreground mt-1">
                Vence em {parseApiDate(nextInstallment.due_date).toLocaleDateString('pt-BR')}
              </p>
            )}
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-normal text-muted-foreground">Economia se quitar hoje</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold text-income">
              {settlement ? fmt(settlement.savings) : '—'}
            </div>
            {settlement && (
              <p className="text-xs text-muted-foreground mt-1">
                Pagaria {fmt(settlement.total_to_pay)} (valor presente)
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="bg-card border-border">
        <CardHeader>
          {/* Sem juros não há sistema de amortização a nomear: "Tabela PRICE"
              num parcelamento de mensalidade é vocabulário de empréstimo para o
              que não é um (ADR 0030). */}
          <CardTitle>
            {Number(financing.interest_rate) === 0
              ? `Parcelas — ${financing.title}`
              : `Tabela ${financing.method} — ${financing.title}`}
          </CardTitle>
          <CardDescription>
            {Number(financing.interest_rate) === 0
              ? 'Parcelas iguais, sem juros.'
              : 'Visualização detalhada das parcelas e amortização.'}
            {schedule.length > PARCELAS_POR_PAGINA && (
              <> Mostrando {inicio + 1}–{Math.min(inicio + PARCELAS_POR_PAGINA, schedule.length)} de {schedule.length}.</>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Sete colunas somam ~900px: no celular a tabela virava uma tira
              rolável em que "Saldo Devedor" e "Status" — as duas que respondem
              "quanto falta" e "posso pagar?" — ficavam fora da tela. */}
          <CardsOrTable
            cards={
          <div className="space-y-2">
            {visiveis.map((row) => (
              <DataCard
                key={row.id}
                title={`Parcela ${row.installment_number}`}
                meta={`Vence em ${parseApiDate(row.due_date).toLocaleDateString('pt-BR')}`}
                value={<span className="text-sm font-semibold text-foreground">{fmt(row.total_amount)}</span>}
                badge={row.is_paid ? <StatusPill tone="success">Paga</StatusPill> : <StatusPill tone="neutral">Pendente</StatusPill>}
                fields={[
                  { label: 'Amortização', value: fmt(row.principal_amount) },
                  { label: 'Juros', value: fmt(row.interest_amount) },
                  { label: 'Saldo devedor', value: fmt(row.remaining_balance), full: true },
                ]}
                actions={
                  !row.is_paid && row.installment_number === nextInstallment?.installment_number ? (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-10 w-full border-primary/40 text-primary hover:bg-primary/10"
                      onClick={() => setPagando(row.installment_number)}
                    >
                      Pagar parcela
                    </Button>
                  ) : undefined
                }
              />
            ))}
          </div>
            }
            table={
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead className="w-[50px]">Nº</TableHead>
                <TableHead>Vencimento</TableHead>
                <TableHead>Amortização</TableHead>
                <TableHead>Juros</TableHead>
                <TableHead>Total</TableHead>
                <TableHead className="text-right">Saldo Devedor</TableHead>
                <TableHead className="text-center">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visiveis.map((row) => (
                <TableRow key={row.id} className="border-border">
                  <TableCell className="text-muted-foreground">{row.installment_number}</TableCell>
                  <TableCell>{parseApiDate(row.due_date).toLocaleDateString('pt-BR')}</TableCell>
                  <TableCell>{fmt(row.principal_amount)}</TableCell>
                  <TableCell>{fmt(row.interest_amount)}</TableCell>
                  <TableCell className="font-medium">{fmt(row.total_amount)}</TableCell>
                  <TableCell className="text-right text-muted-foreground">{fmt(row.remaining_balance)}</TableCell>
                  <TableCell className="text-center">
                    {row.is_paid ? (
                      <StatusPill tone="success">Paga</StatusPill>
                    ) : row.installment_number === nextInstallment?.installment_number ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs border-primary/40 text-primary hover:bg-primary/10"
                        onClick={() => setPagando(row.installment_number)}
                      >
                        Pagar
                      </Button>
                    ) : (
                      <StatusPill tone="neutral">Pendente</StatusPill>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
            }
          />

          {totalPages > 1 && (
            // `flex-wrap`: os três grupos (Anteriores / contador + atalho /
            // Próximas) somam bem mais que 328px e não cabiam numa linha só.
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={pageSafe === 0}
                onClick={() => setPage(pageSafe - 1)}
              >
                <ChevronLeft className="h-4 w-4" /> Anteriores
              </Button>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">
                  Página {pageSafe + 1} de {totalPages}
                </span>
                {nextNumber != null && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-xs text-primary hover:bg-primary/10"
                    onClick={() => setPage(Math.floor((nextNumber - 1) / PARCELAS_POR_PAGINA))}
                  >
                    Ir para a próxima parcela
                  </Button>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={pageSafe >= totalPages - 1}
                onClick={() => setPage(pageSafe + 1)}
              >
                Próximas <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <PagarParcelaDialog
        open={pagando !== null}
        onOpenChange={(o) => !o && setPagando(null)}
        financing={financing}
        installmentNumber={pagando}
        valor={fmt(
          schedule.find((i) => i.installment_number === pagando)?.total_amount ?? 0,
        )}
      />
    </div>
  );
}

export function AmortizationTable() {
  const { financings, isLoading, remove } = useFinancing();
  const confirm = useConfirm();
  const [selectedId, setSelectedId] = React.useState<number | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);

  React.useEffect(() => {
    if (financings.length > 0 && !financings.some((f) => f.id === selectedId)) {
      setSelectedId(financings[0].id);
    }
    if (financings.length === 0) setSelectedId(null);
  }, [financings, selectedId]);

  const selected = financings.find((f) => f.id === selectedId) ?? null;

  if (isLoading) {
    return (
      <div className="h-[200px] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {financings.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setSelectedId(f.id)}
              className={`px-4 py-2 rounded-xl border text-sm font-semibold transition-colors ${
                f.id === selectedId
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-card text-muted-foreground hover:text-foreground'
              }`}
            >
              {f.title}
              {f.status === 'settled' && <span className="ml-2 text-[10px] text-income font-semibold">QUITADO</span>}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {selected && (
            <Button
              variant="ghost"
              className="text-destructive hover:bg-destructive/10 gap-2"
              onClick={async () => {
                const ok = await confirm({
                  title: 'Excluir financiamento',
                  description: `Excluir o financiamento "${selected.title}"?`,
                  confirmLabel: 'Excluir',
                  destructive: true,
                });
                if (!ok) return;
                try { await remove(selected.id); } catch { toast.error('Erro ao excluir.'); }
              }}
            >
              <Trash2 className="h-4 w-4" /> Excluir
            </Button>
          )}
          <Button onClick={() => setCreateOpen(true)} className="bg-primary hover:bg-primary/90 text-primary-foreground font-bold">
            + Novo Financiamento
          </Button>
        </div>
      </div>

      {financings.length === 0 ? (
        <Card className="bg-card border-border p-12 text-center">
          <p className="text-muted-foreground">
            Nenhum financiamento cadastrado. Crie um para ver o cronograma SAC/PRICE e simular quitação antecipada.
          </p>
        </Card>
      ) : selected ? (
        <FinancingDetail financing={selected} />
      ) : null}

      <CreateFinancingDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
