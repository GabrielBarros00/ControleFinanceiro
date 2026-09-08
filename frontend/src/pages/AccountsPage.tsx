import React from 'react';
import { AlertTriangle, ArrowLeftRight, Plus, Trash2, Wallet } from 'lucide-react';

import { PageHeader } from '@/components/layout/PageHeader';
import { MoneyText } from '@/components/money/MoneyText';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MoneyInput } from '@/components/ui/MoneyInput';
import { NativeSelect } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusPill } from '@/components/ui/status-pill';
import { useConfirm } from '@/components/ui/confirm';
import { toast } from '@/stores/toast';
import { getApiErrorMessage } from '@/lib/api-error';
import { parseApiDay, todayLocalISO } from '@/lib/date';
import { currencySymbol, formatMoney } from '@/lib/money';
import {
  useAccountBalanceActions,
  useBalance,
  type AccountBalanceRead,
} from '@/hooks/use-balance';
import {
  ACCOUNT_TYPE_OPTIONS,
  accountTypeLabel,
  usePaymentAccounts,
  type PaymentAccountType,
} from '@/hooks/use-payment-accounts';
import { useTransfers } from '@/hooks/use-transfers';
import { AccountStatementDialog } from '@/components/accounts/AccountStatementDialog';

/*
 * Contas — "onde está o meu dinheiro" (ADR 0034).
 *
 * Era uma aba dentro de Configurações, e cabia lá enquanto a conta era só um
 * rótulo de origem de pagamento. Com saldo, extrato, ajuste e transferência ela
 * passou a ser uma das quatro perguntas que o app responde, e uma pergunta dessas
 * não mora atrás de uma engrenagem.
 *
 * O saldo `null` é o estado mais importante desta tela: conta sem saldo inicial
 * PEDE o número em vez de mostrar zero. A migração não inventa saldo (§6 do
 * pedido), e um zero ali seria um valor errado com a mesma cara de um certo.
 */
export default function AccountsPage() {
  const { balance, isLoading, isError, refetch } = useBalance();
  const { create, update, remove } = usePaymentAccounts();
  const confirm = useConfirm();

  const [criando, setCriando] = React.useState(false);
  const [saldoDe, setSaldoDe] = React.useState<AccountBalanceRead | null>(null);
  const [ajustando, setAjustando] = React.useState<AccountBalanceRead | null>(null);
  const [transferindo, setTransferindo] = React.useState(false);
  const [extratoDe, setExtratoDe] = React.useState<AccountBalanceRead | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <PageHeader title="Contas" subtitle="Onde está o seu dinheiro" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  // Falha de API não pode virar "você não tem dinheiro" (regra ERR-001).
  if (isError || !balance) {
    return (
      <div className="space-y-4">
        <PageHeader title="Contas" subtitle="Onde está o seu dinheiro" />
        <ErrorState
          title="Não foi possível carregar os saldos"
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  const semSaldo = balance.accounts_without_opening ?? 0;
  const semConta = balance.unassigned_movements ?? 0;
  const antesDaAbertura = balance.movements_before_opening ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contas"
        subtitle="Onde está o seu dinheiro"
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setTransferindo(true)}>
              <ArrowLeftRight className="mr-2 h-4 w-4" /> Transferir
            </Button>
            <Button size="sm" onClick={() => setCriando(true)}>
              <Plus className="mr-2 h-4 w-4" /> Nova conta
            </Button>
          </div>
        }
      />

      {/* --- O total ------------------------------------------------------- */}
      <Card>
        <CardContent className="p-4 sm:p-6">
          <p className="text-xs text-muted-foreground sm:text-sm">Seu dinheiro</p>
          {balance.total === null || balance.total === undefined ? (
            <p className="mt-1 text-xl font-semibold text-muted-foreground">
              Saldo não configurado
            </p>
          ) : (
            <MoneyText
              value={balance.total}
              currency={balance.currency}
              className="mt-1 block text-2xl font-semibold sm:text-3xl"
            />
          )}
          {(balance.excluded_foreign_count ?? 0) > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              {balance.excluded_foreign_count} conta(s) ficaram de fora do total por
              falta de cotação. O saldo de cada uma continua correto na moeda dela.
            </p>
          )}
        </CardContent>
      </Card>

      {/* --- Os avisos que explicam um saldo que não fecha ------------------ */}
      {(semSaldo > 0 || semConta > 0 || antesDaAbertura > 0) && (
        <Card className="border-warning/40 bg-warning-subtle/40">
          <CardContent className="space-y-1 p-4 text-sm">
            {semSaldo > 0 && (
              <p className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <span>
                  {semSaldo === 1 ? 'Uma conta ainda não tem' : `${semSaldo} contas ainda não têm`}{' '}
                  saldo inicial. Informe quanto havia e em que dia para o saldo
                  começar a ser calculado.
                </span>
              </p>
            )}
            {semConta > 0 && (
              <p className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <span>
                  {semConta} movimento(s) sem conta declarada não entram em saldo
                  nenhum. Informe a conta ao pagar para eles passarem a contar.
                </span>
              </p>
            )}
            {antesDaAbertura > 0 && (
              <p className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <span>
                  {antesDaAbertura} movimento(s) são anteriores ao saldo inicial da
                  conta e por isso não somam de novo — eles já estão dentro do
                  número que você informou.
                </span>
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* --- Uma conta por cartão ------------------------------------------ */}
      {balance.accounts.length === 0 ? (
        <EmptyState
          icon={Wallet}
          title="Nenhuma conta cadastrada"
          description="Cadastre suas contas, carteiras e o dinheiro vivo para o app saber onde o seu dinheiro está."
          action={
            <Button onClick={() => setCriando(true)}>
              <Plus className="mr-2 h-4 w-4" /> Nova conta
            </Button>
          }
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {balance.accounts.map((conta) => (
            <Card key={conta.account_id} className={conta.active ? '' : 'opacity-70'}>
              <CardHeader className="pb-2">
                <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                  <Wallet className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">{conta.name}</span>
                  {!conta.active && <StatusPill tone="neutral">Inativa</StatusPill>}
                  {conta.is_default && <StatusPill tone="brand">Padrão</StatusPill>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  {conta.balance === null || conta.balance === undefined ? (
                    <button
                      type="button"
                      onClick={() => setSaldoDe(conta)}
                      className="text-left text-sm font-medium text-warning underline-offset-4 hover:underline"
                    >
                      Informar saldo atual
                    </button>
                  ) : (
                    <MoneyText
                      value={conta.balance}
                      currency={conta.currency}
                      className="block text-xl font-semibold"
                    />
                  )}
                  <p className="text-[11px] text-muted-foreground">
                    {accountTypeLabel(conta.type)} · {conta.currency}
                    {conta.opening_on
                      && ` · desde ${parseApiDay(conta.opening_on).toLocaleDateString('pt-BR')}`}
                  </p>
                </div>

                <div className="flex flex-wrap gap-1">
                  <Button variant="ghost" size="sm" className="h-7 text-xs"
                          onClick={() => setExtratoDe(conta)}>
                    Extrato
                  </Button>
                  <Button variant="ghost" size="sm" className="h-7 text-xs"
                          onClick={() => setSaldoDe(conta)}>
                    Saldo inicial
                  </Button>
                  <Button
                    variant="ghost" size="sm" className="h-7 text-xs"
                    disabled={conta.balance === null || conta.balance === undefined}
                    onClick={() => setAjustando(conta)}
                  >
                    Ajustar
                  </Button>
                  <Button
                    variant="ghost" size="sm" className="h-7 text-xs"
                    onClick={async () => {
                      try {
                        await update({
                          id: conta.account_id,
                          data: { is_default: !conta.is_default },
                        });
                      } catch (err) {
                        toast.error(getApiErrorMessage(err, 'Erro ao atualizar a conta.'));
                      }
                    }}
                  >
                    {conta.is_default ? 'Remover padrão' : 'Tornar padrão'}
                  </Button>
                  <Button
                    variant="ghost" size="sm" className="h-7 text-xs"
                    onClick={async () => {
                      try {
                        await update({
                          id: conta.account_id,
                          data: { active: !conta.active },
                        });
                      } catch (err) {
                        toast.error(getApiErrorMessage(err, 'Erro ao atualizar a conta.'));
                      }
                    }}
                  >
                    {conta.active ? 'Desativar' : 'Reativar'}
                  </Button>
                  <Button
                    variant="ghost" size="sm"
                    aria-label={`Excluir a conta ${conta.name}`}
                    className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                    onClick={async () => {
                      const ok = await confirm({
                        title: 'Excluir conta',
                        description: `Excluir a conta "${conta.name}"? O histórico de pagamentos continua explicável.`,
                        confirmLabel: 'Excluir',
                        destructive: true,
                      });
                      if (!ok) return;
                      try {
                        await remove(conta.account_id);
                      } catch (err) {
                        // 409 quando a conta tem saldo: a mensagem do servidor
                        // explica o que fazer (transferir ou ajustar antes).
                        toast.error(getApiErrorMessage(err, 'Erro ao excluir a conta.'));
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {criando && (
        <NovaContaDialog onClose={() => setCriando(false)} onCreate={create} />
      )}
      {saldoDe && (
        <SaldoInicialDialog conta={saldoDe} onClose={() => setSaldoDe(null)} />
      )}
      {ajustando && (
        <AjusteDialog conta={ajustando} onClose={() => setAjustando(null)} />
      )}
      {transferindo && (
        <TransferenciaDialog
          contas={balance.accounts}
          onClose={() => setTransferindo(false)}
        />
      )}
      {extratoDe && (
        <AccountStatementDialog
          accountId={extratoDe.account_id}
          accountName={extratoDe.name}
          onClose={() => setExtratoDe(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function NovaContaDialog({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (data: { name: string; type: PaymentAccountType }) => Promise<unknown>;
}) {
  const [nome, setNome] = React.useState('');
  const [tipo, setTipo] = React.useState<PaymentAccountType>('checking');
  const [salvando, setSalvando] = React.useState(false);

  const salvar = async () => {
    setSalvando(true);
    try {
      await onCreate({ name: nome.trim(), type: tipo });
      toast.success('Conta criada. Informe o saldo atual para ela começar a contar.');
      onClose();
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao criar a conta.'));
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nova conta</DialogTitle>
          <DialogDescription>
            Conta bancária, carteira digital ou o dinheiro vivo.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="conta-nome">Nome</Label>
            <Input
              id="conta-nome" value={nome} autoFocus
              placeholder="Nubank"
              onChange={(e) => setNome(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="conta-tipo">Tipo</Label>
            {/* `<select>` nativo dentro de Dialog: o popup do Base UI escapa do
                focus-trap do Radix e fica inalcançável pelo teclado. */}
            <NativeSelect
              id="conta-tipo" value={tipo}
              onChange={(e) => setTipo(e.target.value as PaymentAccountType)}
            >
              {ACCOUNT_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </NativeSelect>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={salvar} disabled={nome.trim().length < 2 || salvando}>
            Criar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SaldoInicialDialog({
  conta,
  onClose,
}: {
  conta: AccountBalanceRead;
  onClose: () => void;
}) {
  const { setOpeningBalance, isSaving } = useAccountBalanceActions();
  const [valor, setValor] = React.useState<number>(Number(conta.opening_amount ?? 0));
  const [data, setData] = React.useState(conta.opening_on ?? todayLocalISO());

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Saldo inicial — {conta.name}</DialogTitle>
          <DialogDescription>
            Quanto havia nesta conta e em que dia. É o ponto de partida: tudo que
            aconteceu antes dessa data já está dentro desse número, e só o que vier
            depois muda o saldo.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="saldo-valor">Saldo</Label>
            <MoneyInput
              id="saldo-valor" value={valor} onChange={setValor}
              prefix={currencySymbol(conta.currency)}
            />
          </div>
          <div>
            <Label htmlFor="saldo-data">Data desse saldo</Label>
            <Input
              id="saldo-data" type="date" value={data}
              onChange={(e) => setData(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button
            disabled={isSaving}
            onClick={async () => {
              try {
                await setOpeningBalance({
                  accountId: conta.account_id,
                  amount: valor.toFixed(2),
                  asOf: data,
                });
                toast.success('Saldo inicial registrado.');
                onClose();
              } catch (err) {
                toast.error(getApiErrorMessage(err, 'Erro ao salvar o saldo.'));
              }
            }}
          >
            Salvar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AjusteDialog({
  conta,
  onClose,
}: {
  conta: AccountBalanceRead;
  onClose: () => void;
}) {
  const { adjust, isSaving } = useAccountBalanceActions();
  const calculado = Number(conta.balance ?? 0);
  const [real, setReal] = React.useState<number>(calculado);
  const [nota, setNota] = React.useState('');
  const diferenca = real - calculado;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ajustar saldo — {conta.name}</DialogTitle>
          <DialogDescription>
            Informe o saldo que o banco mostra. A diferença vira um movimento
            datado no extrato — nada do passado é reescrito.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-lg bg-muted p-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Calculado pelo app</span>
              <span className="tabular">
                {formatMoney(calculado, { currency: conta.currency })}
              </span>
            </div>
            {diferenca !== 0 && (
              <div className="mt-1 flex justify-between font-medium">
                <span>Ajuste</span>
                <span className="tabular">
                  {formatMoney(diferenca, { sign: true, currency: conta.currency })}
                </span>
              </div>
            )}
          </div>
          <div>
            <Label htmlFor="ajuste-real">Saldo real</Label>
            <MoneyInput
              id="ajuste-real" value={real} onChange={setReal}
              prefix={currencySymbol(conta.currency)}
            />
          </div>
          <div>
            <Label htmlFor="ajuste-nota">Motivo (opcional)</Label>
            <Input
              id="ajuste-nota" value={nota}
              placeholder="Conferido no app do banco"
              onChange={(e) => setNota(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button
            disabled={isSaving || diferenca === 0}
            onClick={async () => {
              try {
                await adjust({
                  accountId: conta.account_id,
                  realBalance: real.toFixed(2),
                  note: nota || undefined,
                });
                toast.success('Ajuste registrado no extrato.');
                onClose();
              } catch (err) {
                toast.error(getApiErrorMessage(err, 'Erro ao ajustar o saldo.'));
              }
            }}
          >
            Ajustar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TransferenciaDialog({
  contas,
  onClose,
}: {
  contas: AccountBalanceRead[];
  onClose: () => void;
}) {
  const { create, isSaving } = useTransfers();
  const ativas = contas.filter((c) => c.active);
  const [origem, setOrigem] = React.useState<number>(ativas[0]?.account_id ?? 0);
  const [destino, setDestino] = React.useState<number>(
    ativas[1]?.account_id ?? ativas[0]?.account_id ?? 0,
  );
  const [valor, setValor] = React.useState(0);
  const [valorDestino, setValorDestino] = React.useState(0);
  const [quando, setQuando] = React.useState(todayLocalISO());
  const [nota, setNota] = React.useState('');

  const contaOrigem = ativas.find((c) => c.account_id === origem);
  const contaDestino = ativas.find((c) => c.account_id === destino);
  // Moedas diferentes exigem os DOIS valores: o app não converte por conta
  // própria (ADR 0006/0015), então quem transfere informa quanto entrou.
  const multimoeda =
    !!contaOrigem && !!contaDestino && contaOrigem.currency !== contaDestino.currency;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Transferir entre contas</DialogTitle>
          <DialogDescription>
            O dinheiro muda de lugar. Não é renda nem despesa, e o seu total não se
            altera.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="transf-origem">De</Label>
            <NativeSelect
              id="transf-origem" value={String(origem)}
              onChange={(e) => setOrigem(Number(e.target.value))}
            >
              {ativas.map((c) => (
                <option key={c.account_id} value={c.account_id}>
                  {c.name} ({c.currency})
                </option>
              ))}
            </NativeSelect>
          </div>
          <div>
            <Label htmlFor="transf-destino">Para</Label>
            <NativeSelect
              id="transf-destino" value={String(destino)}
              onChange={(e) => setDestino(Number(e.target.value))}
            >
              {ativas.map((c) => (
                <option key={c.account_id} value={c.account_id}>
                  {c.name} ({c.currency})
                </option>
              ))}
            </NativeSelect>
          </div>
          <div>
            <Label htmlFor="transf-valor">
              {multimoeda ? `Valor que sai (${contaOrigem?.currency})` : 'Valor'}
            </Label>
            <MoneyInput
              id="transf-valor" value={valor} onChange={setValor}
              prefix={currencySymbol(contaOrigem?.currency ?? 'BRL')}
            />
          </div>
          {multimoeda && (
            <div>
              <Label htmlFor="transf-valor-destino">
                Valor que entra ({contaDestino?.currency})
              </Label>
              <MoneyInput
                id="transf-valor-destino" value={valorDestino}
                onChange={setValorDestino}
                prefix={currencySymbol(contaDestino?.currency ?? 'BRL')}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                As contas estão em moedas diferentes: informe os dois valores. O app
                não converte por conta própria.
              </p>
            </div>
          )}
          <div>
            <Label htmlFor="transf-data">Data</Label>
            <Input
              id="transf-data" type="date" value={quando}
              onChange={(e) => setQuando(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="transf-nota">Descrição (opcional)</Label>
            <Input
              id="transf-nota" value={nota}
              onChange={(e) => setNota(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button
            disabled={
              isSaving || valor <= 0 || origem === destino ||
              (multimoeda && valorDestino <= 0)
            }
            onClick={async () => {
              try {
                await create({
                  from_account_id: origem,
                  to_account_id: destino,
                  from_amount: valor.toFixed(2),
                  to_amount: multimoeda ? valorDestino.toFixed(2) : undefined,
                  occurred_on: quando,
                  note: nota || undefined,
                });
                toast.success('Transferência registrada.');
                onClose();
              } catch (err) {
                toast.error(getApiErrorMessage(err, 'Erro ao transferir.'));
              }
            }}
          >
            Transferir
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
