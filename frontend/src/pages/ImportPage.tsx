import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useImports } from '@/hooks/use-imports';
import { FileUp, Check, Loader2, Settings2, CopyX } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getApiErrorMessage } from '@/lib/api-error';
import { toast } from '@/stores/toast';
import { parseApiDate } from '@/lib/date';
import { formatMoney } from '@/lib/money';
import { useBaseCurrency } from '@/hooks/use-base-currency';

interface ParsedRow {
  line?: number;
  title: string;
  total_amount: string;
  transaction_date: string;
  duplicate?: boolean;
}

interface SkippedRow {
  line: number;
  reason: string;
}

// Espelha settings.IMPORT_MAX_ROWS do backend (que devolve 422 acima disso).
const IMPORT_MAX_ROWS = 5000;

export function ImportPage() {
  const navigate = useNavigate();
  const { parse, isParsing, commit, isCommitting } = useImports();
  const baseCurrency = useBaseCurrency();
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<ParsedRow[] | null>(null);
  const [skippedRows, setSkippedRows] = React.useState<SkippedRow[]>([]);
  const [skipDuplicates, setSkipDuplicates] = React.useState(true);
  
  // Mapping state
  const [mapping, setMapping] = React.useState({
    date_column: 'Data',
    description_column: 'Descricao',
    amount_column: 'Valor',
    date_format: '%d/%m/%Y',
    delimiter: ';',
    decimal_separator: ',',
    invert_amount: true
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const handleParse = async () => {
    if (!file) return;
    try {
      const data = await parse({ file, mapping });
      // O backend recusa o commit acima de IMPORT_MAX_ROWS. Avisar AQUI evita
      // dois problemas: a tela renderizava uma linha por registro sem
      // virtualização (dezenas de milhares travavam o navegador) e o usuário só
      // descobria o limite depois de revisar o arquivo inteiro, num 422 seco.
      if (data.rows.length > IMPORT_MAX_ROWS) {
        toast.error(
          `O arquivo tem ${data.rows.length.toLocaleString('pt-BR')} linhas e o limite por ` +
          `importação é ${IMPORT_MAX_ROWS.toLocaleString('pt-BR')}. Divida o arquivo e importe em partes.`
        );
        setPreview(null);
        setSkippedRows([]);
        return;
      }
      setPreview(data.rows);
      setSkippedRows(data.skipped);
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao processar arquivo. Verifique o delimitador e os nomes das colunas.'));
    }
  };

  const duplicateCount = preview?.filter((r) => r.duplicate).length ?? 0;
  const rowsToImport = preview
    ? (skipDuplicates ? preview.filter((r) => !r.duplicate) : preview)
    : [];

  const handleImport = async () => {
    if (!preview) return;
    if (rowsToImport.length === 0) {
      toast.warning('Nada a importar', 'Todas as linhas são duplicatas.');
      return;
    }
    try {
      // Decisão por linha: duplicatas viram 'ignore' quando o usuário optou por
      // pular; o backend ainda garante idempotência por fingerprint (ADR 0008)
      const rows = preview.map((r) => ({
        line: r.line,
        title: r.title,
        total_amount: r.total_amount,
        transaction_date: r.transaction_date,
        decision: (skipDuplicates && r.duplicate ? 'ignore' : 'import') as 'import' | 'ignore',
      }));
      const result = await commit({ filename: file?.name, rows });
      toast.success(
        'Importação concluída',
        `${result.imported} criada(s), ${result.duplicate} duplicata(s), ` +
        `${result.ignored} ignorada(s), ${result.skipped} inválida(s).`
      );
      navigate('/');
    } catch (err) {
      toast.error(getApiErrorMessage(err, 'Erro ao importar transações.'));
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1 bg-card border-border shadow-xl">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Settings2 className="h-5 w-5 text-primary" /> Configuração
            </CardTitle>
            <CardDescription>Ajuste os parâmetros do seu arquivo.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Arquivo CSV</Label>
              <div className="flex items-center gap-2">
                <Input type="file" accept=".csv" onChange={handleFileChange} className="bg-background/50" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label className="text-xs">Delimitador</Label>
                <Input value={mapping.delimiter} onChange={e => setMapping({...mapping, delimiter: e.target.value})} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Sep. Decimal</Label>
                <Input value={mapping.decimal_separator} onChange={e => setMapping({...mapping, decimal_separator: e.target.value})} />
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Formato Data</Label>
              <Input value={mapping.date_format} onChange={e => setMapping({...mapping, date_format: e.target.value})} />
              <p className="text-[10px] text-muted-foreground">%d=dia, %m=mês, %Y=ano (ex: %d/%m/%Y)</p>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Coluna Data</Label>
              <Input value={mapping.date_column} onChange={e => setMapping({...mapping, date_column: e.target.value})} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Coluna Descrição</Label>
              <Input value={mapping.description_column} onChange={e => setMapping({...mapping, description_column: e.target.value})} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Coluna Valor</Label>
              <Input value={mapping.amount_column} onChange={e => setMapping({...mapping, amount_column: e.target.value})} />
            </div>

            <Button 
              className="w-full gap-2 font-bold mt-4" 
              onClick={handleParse}
              disabled={!file || isParsing}
            >
              {isParsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
              Processar Arquivo
            </Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2 bg-card border-border shadow-xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-lg">Pré-visualização</CardTitle>
              <CardDescription>
                Verifique se os dados foram extraídos corretamente.
                {duplicateCount > 0 && (
                  <span className="block text-amber-500 font-semibold mt-1">
                    {duplicateCount} possível(is) duplicata(s) detectada(s) — mesma data, valor e descrição.
                  </span>
                )}
                {skippedRows.length > 0 && (
                  <span className="block text-destructive font-semibold mt-1">
                    {skippedRows.length} linha(s) ignorada(s):{' '}
                    {skippedRows.map((s) => `linha ${s.line} (${s.reason})`).join('; ')}
                  </span>
                )}
              </CardDescription>
            </div>
            {preview && (
              <div className="flex items-center gap-4">
                {duplicateCount > 0 && (
                  <label className="flex items-center gap-2 text-xs font-semibold text-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={skipDuplicates}
                      onChange={(e) => setSkipDuplicates(e.target.checked)}
                      className="accent-primary h-4 w-4"
                    />
                    Pular duplicatas
                  </label>
                )}
                <Button onClick={handleImport} disabled={isCommitting} className="bg-emerald-600 hover:bg-emerald-700 gap-2 font-bold">
                  {isCommitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Confirmar {rowsToImport.length} Transações
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent className="p-0">
            {!preview ? (
              <div className="h-[400px] flex flex-col items-center justify-center text-muted-foreground gap-4">
                <FileUp className="h-12 w-12 opacity-20" />
                <p>Nenhum arquivo processado.</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="border-border">
                    <TableHead className="text-[10px] font-semibold uppercase">Data</TableHead>
                    <TableHead className="text-[10px] font-semibold uppercase">Descrição</TableHead>
                    <TableHead className="text-right text-[10px] font-semibold uppercase">Valor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.map((tx, idx) => (
                    <TableRow key={tx.line ?? idx} className={`border-border ${tx.duplicate && skipDuplicates ? 'opacity-40' : ''}`}>
                      <TableCell className="text-xs font-medium">
                        {parseApiDate(tx.transaction_date).toLocaleDateString('pt-BR')}
                      </TableCell>
                      <TableCell className="text-sm font-bold">
                        <span className="flex items-center gap-2">
                          {tx.title}
                          {tx.duplicate && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-[10px] font-bold text-amber-500">
                              <CopyX className="h-3 w-3" /> duplicata
                            </span>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-black">
                        {formatMoney(tx.total_amount, { currency: baseCurrency })}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
