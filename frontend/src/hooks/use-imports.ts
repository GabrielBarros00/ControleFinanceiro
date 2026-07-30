import { useMutation } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useWorkspaceId } from './use-workspace-id';

export interface CsvMapping {
  date_column: string;
  description_column: string;
  amount_column: string;
  date_format: string;
  delimiter: string;
  decimal_separator: string;
  invert_amount: boolean;
}

export interface ParsedCsvRow {
  line?: number;
  title: string;
  total_amount: string;
  transaction_date: string;
  duplicate?: boolean;
}

export interface SkippedCsvRow {
  line: number;
  reason: string;
}

export interface ParseCsvResult {
  rows: ParsedCsvRow[];
  skipped: SkippedCsvRow[];
}

export interface BulkImportResult {
  status: string;
  created: number;
  skipped: number;
  skipped_details: { index: number; title: string; reason: string }[];
}

export interface CommitRow {
  line?: number;
  title: string;
  total_amount: string | number;
  transaction_date: string;
  decision?: 'import' | 'ignore';
}

export interface CommitImportResult {
  batch_id: number;
  imported: number;
  ignored: number;
  duplicate: number;
  skipped: number;
}

export function useImports() {
  const currentWorkspaceId = useWorkspaceId();

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
