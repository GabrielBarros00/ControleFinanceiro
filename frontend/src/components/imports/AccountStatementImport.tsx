import * as React from 'react';
import { Check, CopyX, FileUp, Loader2, Settings2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { useAccountStatementImport, type AccountCommitResult, type AccountParsedRow, type ImportClassification } from '@/hooks/use-imports';
import { usePaymentAccounts } from '@/hooks/use-payment-accounts';
import { useCreditCards } from '@/hooks/use-credit-cards';
import { useWorkspaces } from '@/hooks/use-workspaces';
import { useWorkspaceId } from '@/hooks/use-workspace-id';
import { getApiErrorMessage } from '@/lib/api-error';
import { parseApiDate } from '@/lib/date';
import { formatMoney } from '@/lib/money';
import { toast } from '@/stores/toast';
import { cn } from '@/lib/utils';

type Escolha = ImportClassification | 'ignore';

/** A decisão da pessoa sobre uma linha, começando pelo palpite do servidor. */
interface Linha extends AccountParsedRow {
  escolha: Escolha;
  espaco: number | '';
  conta: number | '';
  cartao: number | '';
}

const ROTULO: Record<Escolha, string> = {
  expense: 'Despesa',
  income: 'Renda',
  transfer: 'Transferência',
  statement_payment: 'Pagamento de fatura',
  ignore: 'Ignorar',
};

/** O que cada sentido pode ser: dinheiro que saiu não é renda, e que entrou não é despesa. */
const OPCOES: Record<'in' | 'out', Escolha[]> = {
  out: ['expense', 'transfer', 'statement_payment', 'ignore'],
  in: ['income', 'transfer', 'ignore'],
};

/**
 * Importar o EXTRATO de uma conta (ADR 0037).
 *
 * Diferente da importação de despesas: o sinal do valor diz se o dinheiro
 * entrou ou saiu, e cada linha vira o que ela é — despesa num espaço, renda na
 * conta, transferência com outra conta sua ou pagamento de fatura. O servidor
 * sugere; a pessoa confirma linha a linha.
 */
export function AccountStatementImport() {
  const { parse, isParsing, commit, isCommitting } = useAccountStatementImport();
  const { activeAccounts } = usePaymentAccounts();
  const { cards } = useCreditCards();
  const { workspaces } = useWorkspaces();
  const espacoAtual = useWorkspaceId();
  const [conta, setConta] = React.useState<number | ''>('');
  const [arquivo, setArquivo] = React.useState<File | null>(null);
  const [linhas, setLinhas] = React.useState<Linha[] | null>(null);
  const [recusadas, setRecusadas] = React.useState<Array<{ line: number; reason: string }>>([]);
  const [resultado, setResultado] = React.useState<AccountCommitResult | null>(null);
  const [espacoPadrao, setEspacoPadrao] = React.useState<number | ''>(espacoAtual ?? '');
  const [mapeamento, setMapeamento] = React.useState({
    date_column: 'Data',
    description_column: 'Descricao',
    amount_column: 'Valor',
    date_format: '%d/%m/%Y',
    delimiter: ';',
    decimal_separator: ',',
    id_column: '',
  });

  const contaEscolhida = activeAccounts.find((a) => a.id === conta);
  const moeda = contaEscolhida?.currency ?? 'BRL';
  const outrasContas = activeAccounts.filter((a) => a.id !== conta);

  const campo = (nome: keyof typeof mapeamento, rotulo: string) => (
    <div className="space-y-1">
      <Label htmlFor={`extrato-${nome}`} className="text-xs">{rotulo}</Label>
      <Input id={`extrato-${nome}`} value={mapeamento[nome]} onChange={(e) => setMapeamento({ ...mapeamento, [nome]: e.target.value })} />
    </div>
  );

  async function processar() {
    if (!arquivo || conta === '') return;
    try {
      const r = await parse({ accountId: conta, file: arquivo, mapping: mapeamento });
      setResultado(null);
      setRecusadas(r.skipped);
      setLinhas(r.rows.map((x) => ({
        ...x,
        // Já importada (e o que ela criou ainda existe): começa ignorada.
        escolha: x.duplicate ? 'ignore' : x.suggested_classification,
        espaco: '',
        conta: x.suggested_account_id ?? '',
        cartao: x.suggested_card_id ?? (cards.length === 1 ? cards[0].id : ''),
      })));
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao processar o extrato. Confira o delimitador e os nomes das colunas.'));
    }
  }

  const muda = (i: number, parte: Partial<Linha>) =>
    setLinhas((atual) => atual && atual.map((l, j) => (j === i ? { ...l, ...parte } : l)));

  const aImportar = linhas?.filter((l) => l.escolha !== 'ignore').length ?? 0;

  async function importar() {
    if (!linhas || conta === '') return;
    try {
      const r = await commit({
        account_id: conta,
        filename: arquivo?.name,
        rows: linhas.map((l) => ({
          line: l.line,
          title: l.title,
          total_amount: l.total_amount,
          transaction_date: l.transaction_date,
          direction: l.direction,
          external_id: l.external_id ?? null,
          decision: l.escolha === 'ignore' ? 'ignore' : 'import',
          classification: l.escolha === 'ignore' ? null : l.escolha,
          space_id: l.escolha === 'expense' ? (l.espaco || espacoPadrao || null) : null,
          counterpart_account_id: l.escolha === 'transfer' ? l.conta || null : null,
          card_id: l.escolha === 'statement_payment' ? l.cartao || null : null,
        })),
      });
      setResultado(r);
      setLinhas(null);
      toast.success(
        'Extrato importado',
        `${r.imported} registrado(s), ${r.duplicate} já existia(m), ${r.ignored} ignorado(s)` +
          (r.skipped ? `, ${r.skipped} não entrou(aram) — veja o motivo na tela.` : '.'),
      );
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao importar o extrato.'));
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-1 bg-card border-border shadow-xl">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Settings2 className="h-5 w-5 text-primary" /> Configuração
          </CardTitle>
          <CardDescription>Positivo entrou, negativo saiu — como o banco exporta.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="extrato-conta">Conta do extrato</Label>
            <NativeSelect id="extrato-conta" value={conta} onChange={(e) => setConta(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Escolha a conta</option>
              {activeAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </NativeSelect>
          </div>
          <div className="space-y-2">
            <Label htmlFor="extrato-arquivo">Arquivo CSV</Label>
            <Input id="extrato-arquivo" type="file" accept=".csv" onChange={(e) => setArquivo(e.target.files?.[0] ?? null)} className="bg-background/50" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            {campo('delimiter', 'Delimitador')}
            {campo('decimal_separator', 'Separador decimal')}
          </div>
          {campo('date_format', 'Formato da data')}
          {campo('date_column', 'Coluna da data')}
          {campo('description_column', 'Coluna da descrição')}
          {campo('amount_column', 'Coluna do valor')}
          {campo('id_column', 'Coluna do id da linha (opcional)')}
          <Button className="w-full gap-2 font-bold" onClick={() => void processar()} disabled={!arquivo || conta === '' || isParsing}>
            {isParsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
            Processar extrato
          </Button>
        </CardContent>
      </Card>

      <Card className="lg:col-span-2 bg-card border-border shadow-xl">
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="text-lg">Pré-visualização</CardTitle>
            <CardDescription>
              Confira o que cada linha vai virar.
              {recusadas.length > 0 && (
                <span className="block text-destructive font-semibold mt-1">
                  {recusadas.length} linha(s) ilegível(is): {recusadas.map((s) => `linha ${s.line} (${s.reason})`).join('; ')}
                </span>
              )}
            </CardDescription>
          </div>
          {linhas && (
            <Button onClick={() => void importar()} disabled={isCommitting || aImportar === 0} className="gap-2 font-bold">
              {isCommitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Importar {aImportar}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {resultado && resultado.problems.length > 0 && (
            <div role="status" className="rounded-lg border border-warning/30 bg-warning-subtle px-3 py-2 text-sm text-warning">
              <p className="font-semibold">Não entraram:</p>
              <ul className="mt-1 list-disc pl-5">
                {resultado.problems.map((p) => <li key={p.line}>Linha {p.line}: {p.reason}</li>)}
              </ul>
            </div>
          )}
          {linhas && linhas.some((l) => l.escolha === 'expense') && (
            <div className="space-y-1">
              <Label htmlFor="extrato-espaco-padrao" className="text-xs">Espaço das despesas</Label>
              <NativeSelect id="extrato-espaco-padrao" value={espacoPadrao} onChange={(e) => setEspacoPadrao(e.target.value ? Number(e.target.value) : '')}>
                <option value="">Escolha o espaço</option>
                {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </NativeSelect>
            </div>
          )}
          {!linhas ? (
            <div className="flex h-[200px] flex-col items-center justify-center gap-4 text-muted-foreground">
              <FileUp className="h-12 w-12 opacity-20" />
              <p>Nenhum extrato processado.</p>
            </div>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {linhas.map((l, i) => (
                <li key={`${l.line}-${i}`} className={cn('space-y-2 p-3', l.escolha === 'ignore' && 'opacity-60')}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                        <span className="truncate">{l.title}</span>
                        {l.duplicate && (
                          <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning-subtle px-2 py-0.5 text-[10px] font-bold text-warning">
                            <CopyX className="h-3 w-3" /> já importada
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">{parseApiDate(l.transaction_date).toLocaleDateString('pt-BR')}</p>
                    </div>
                    <span className={cn('shrink-0 font-semibold tabular-nums', l.direction === 'in' ? 'text-income' : 'text-expense')}>
                      {l.direction === 'in' ? '+' : '−'}{formatMoney(l.total_amount, { currency: moeda })}
                    </span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <NativeSelect aria-label={`O que é "${l.title}"`} value={l.escolha} onChange={(e) => muda(i, { escolha: e.target.value as Escolha })}>
                      {OPCOES[l.direction].map((o) => <option key={o} value={o}>{ROTULO[o]}</option>)}
                    </NativeSelect>
                    {l.escolha === 'expense' && (
                      <NativeSelect aria-label={`Espaço de "${l.title}"`} value={l.espaco} onChange={(e) => muda(i, { espaco: e.target.value ? Number(e.target.value) : '' })}>
                        <option value="">Espaço das despesas</option>
                        {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                      </NativeSelect>
                    )}
                    {l.escolha === 'transfer' && (
                      <NativeSelect aria-label={`Outra conta de "${l.title}"`} value={l.conta} onChange={(e) => muda(i, { conta: e.target.value ? Number(e.target.value) : '' })}>
                        <option value="">{l.direction === 'out' ? 'Para qual conta?' : 'De qual conta?'}</option>
                        {outrasContas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                      </NativeSelect>
                    )}
                    {l.escolha === 'statement_payment' && (
                      <NativeSelect aria-label={`Cartão de "${l.title}"`} value={l.cartao} onChange={(e) => muda(i, { cartao: e.target.value ? Number(e.target.value) : '' })}>
                        <option value="">Qual cartão?</option>
                        {cards.map((c: { id: number; name: string }) => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </NativeSelect>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
