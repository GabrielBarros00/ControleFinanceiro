import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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

/** Uma importação feita pela pessoa, com quanto dela ainda existe (ADR 0036). */
export type ImportBatch = components['schemas']['ImportBatchRead'];
export type UndoImportResult = components['schemas']['UndoImportResult'];

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
    onSuccess: () => {
      invalidarLote();
      queryClient.invalidateQueries({ queryKey: ['imports', currentWorkspaceId] });
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

/** As importações da pessoa neste espaço (ADR 0036). */
export function useImportHistory() {
  const workspaceId = useWorkspaceId();
  return useQuery({
    queryKey: ['imports', workspaceId],
    queryFn: async () => (await apiClient.get(`/workspaces/${workspaceId}/imports`)).data as ImportBatch[],
    enabled: Boolean(workspaceId),
  });
}

/**
 * Desfazer importação: exclui o que o lote criou e ainda existe, com as regras da
 * exclusão (tudo ou nada). Com anexo, o servidor só aceita com
 * `confirm_attachments` — a tela pergunta antes, mostrando quantos recibos saem.
 */
export function useUndoImport() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ batchId, confirmAttachments }: { batchId: number; confirmAttachments: boolean }) =>
      (await apiClient.post(`/workspaces/${workspaceId}/imports/${batchId}/undo`, {
        confirm_attachments: confirmAttachments,
      })).data as UndoImportResult,
    onSuccess: () => {
      // Os lançamentos saíram: as mesmas telas que o lote de criação atualiza.
      invalidateForEvent(queryClient, 'transaction.bulk_created', workspaceId);
      queryClient.invalidateQueries({ queryKey: ['imports', workspaceId] });
    },
  });
}

// --- Extrato de CONTA (ADR 0037): pessoal, como a conta -------------------------------

export type AccountParsedRow = components['schemas']['AccountParsedRow'];
export type AccountCommitRow = components['schemas']['AccountCommitRow'];
export type AccountCommitResult = components['schemas']['AccountCommitResult'];
export type AccountImportBatch = components['schemas']['AccountImportBatchRead'];
export type AccountUndoResult = components['schemas']['AccountUndoResult'];
export type ImportClassification = NonNullable<AccountCommitRow['classification']>;

/** Mapeamento do extrato de conta: o de sempre, mais a coluna do id da linha (opcional). */
export type AccountCsvMapping = Omit<CsvMapping, 'invert_amount'> & { id_column?: string };

/**
 * Um extrato de conta mexe em várias telas de uma vez — lançamentos de mais de um
 * espaço, rendas, saldo das contas, transferências, faturas —, então a importação
 * e o desfazer recarregam tudo o que estiver aberto.
 */
export function useAccountStatementImport() {
  const queryClient = useQueryClient();
  const parse = useMutation({
    mutationFn: async ({ accountId, file, mapping }: { accountId: number; file: File; mapping: AccountCsvMapping }) => {
      const form = new FormData();
      form.append('account_id', String(accountId));
      form.append('file', file);
      (Object.keys(mapping) as (keyof AccountCsvMapping)[]).forEach((k) => {
        const v = mapping[k];
        if (v !== undefined && v !== '') form.append(k, String(v));
      });
      const r = await apiClient.post('/me/imports/parse', form, { headers: { 'Content-Type': 'multipart/form-data' } });
      return r.data as components['schemas']['AccountParseResult'];
    },
  });
  const commit = useMutation({
    mutationFn: async (body: { account_id: number; filename?: string; rows: AccountCommitRow[] }) =>
      (await apiClient.post('/me/imports/commit', body)).data as AccountCommitResult,
    onSuccess: () => queryClient.invalidateQueries(),
  });
  return {
    parse: parse.mutateAsync, isParsing: parse.isPending,
    commit: commit.mutateAsync, isCommitting: commit.isPending,
  };
}

export function useAccountImportHistory() {
  return useQuery({
    queryKey: ['me-imports'],
    queryFn: async () => (await apiClient.get('/me/imports')).data as AccountImportBatch[],
  });
}

export function useUndoAccountImport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ batchId, confirmAttachments }: { batchId: number; confirmAttachments: boolean }) =>
      (await apiClient.post(`/me/imports/${batchId}/undo`, { confirm_attachments: confirmAttachments })).data as AccountUndoResult,
    onSuccess: () => queryClient.invalidateQueries(),
  });
}
