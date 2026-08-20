import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { invalidateForEvent } from '@/lib/ws-events';
import type { components } from '@/types/api.gen';
import { useWorkspaceId } from './use-workspace-id';

/*
 * Derivados do OpenAPI, não escritos à mão.
 *
 * Este arquivo mantinha SETE interfaces manuais, e duas delas já divergiam entre
 * si sobre o mesmo campo do mesmo fluxo: `ParsedCsvRow.total_amount` era
 * `string`, `CommitRow.total_amount` era `string | number`. Nada acusava, porque
 * as rotas devolviam `Dict[str, Any]` e não havia contrato com que divergir.
 */
export type ParsedCsvRow = components['schemas']['ParsedCsvRow'];
export type SkippedCsvRow = components['schemas']['SkippedCsvRow'];
export type ParseCsvResult = components['schemas']['ParseCsvResult'];
export type BulkImportResult = components['schemas']['BulkCreateResult'];
export type CommitImportResult = components['schemas']['CommitImportResult'];

/** O corpo do commit — entrada, não saída (a decisão por linha é do usuário). */
export type CommitRow = components['schemas']['CommitRow'];

/** Mapeamento de colunas do CSV: é `multipart/form-data`, não JSON, então o
 *  OpenAPI o descreve como campos de formulário e não como um schema só. */
export interface CsvMapping {
  date_column: string;
  description_column: string;
  amount_column: string;
  date_format: string;
  delimiter: string;
  decimal_separator: string;
  invert_amount: boolean;
}

export function useImports() {
  const currentWorkspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  /**
   * O import era o ÚNICO hook de mutação do app sem invalidação local: ele
   * dependia só do `transaction.bulk_created` voltar pelo WebSocket. Com o socket
   * bloqueado por infra (ou ainda em backoff), a pessoa importava 200 linhas,
   * caía no Início e via os dados de antes — sem nenhum sinal de que faltava algo.
   *
   * Mesmo tipo de evento que o backend publica em `imports.py`, então os dois
   * caminhos convergem exatamente como `lib/ws-events.ts` descreve.
   */
  const invalidarLote = () =>
    invalidateForEvent(queryClient, 'transaction.bulk_created', currentWorkspaceId);

  const parseMutation = useMutation({
    mutationFn: async ({ file, mapping }: { file: File; mapping: CsvMapping }): Promise<ParseCsvResult> => {
      const formData = new FormData();
      formData.append('file', file);

      // Append mapping fields
      (Object.keys(mapping) as (keyof CsvMapping)[]).forEach(key => {
        formData.append(key, String(mapping[key]));
      });

      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/imports/parse`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      return response.data;
    },
  });

  const importMutation = useMutation({
    mutationFn: async (transactions: ParsedCsvRow[]) => {
      // O endpoint bulk recebe a lista pura no body (não um objeto embrulhado)
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/transactions/bulk`,
        transactions
      );
      return response.data as BulkImportResult;
    },
    onSuccess: invalidarLote,
  });

  // Commit persistido: lote auditável + fingerprint idempotente (ADR 0008).
  // Reimportar o mesmo arquivo não duplica (linhas repetidas viram 'duplicate').
  const commitMutation = useMutation({
    mutationFn: async ({ filename, rows }: { filename?: string; rows: CommitRow[] }) => {
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/imports/commit`,
        { filename, rows }
      );
      return response.data as CommitImportResult;
    },
    onSuccess: invalidarLote,
  });

  return {
    parse: parseMutation.mutateAsync,
    isParsing: parseMutation.isPending,
    importTransactions: importMutation.mutateAsync,
    isImporting: importMutation.isPending,
    commit: commitMutation.mutateAsync,
    isCommitting: commitMutation.isPending,
  };
}
