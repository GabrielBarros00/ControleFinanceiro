import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';
import { useUIStore } from '@/stores';

export interface AttachmentMeta {
  id: number;
  transaction_id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_by_user_id?: number | null;
  created_at: string;
}

// Espelha ALLOWED_CONTENT_TYPES / UPLOAD_MAX_BYTES do backend
export const ATTACHMENT_ACCEPT = 'image/jpeg,image/png,image/webp,application/pdf';
export const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;

const ALLOWED_TYPES = new Set(ATTACHMENT_ACCEPT.split(','));

/** Valida antes de subir — na criação o arquivo fica em memória e só chegaria
 * ao servidor depois de salvar a despesa; recusar ali seria tarde demais. */
export function validateAttachmentFile(file: File): string | null {
  if (!ALLOWED_TYPES.has(file.type)) return `"${file.name}": use JPG, PNG, WebP ou PDF.`;
  if (file.size === 0) return `"${file.name}": arquivo vazio.`;
  if (file.size > ATTACHMENT_MAX_BYTES) return `"${file.name}": passa de 5 MB.`;
  return null;
}

async function postAttachment(
  workspaceId: number | string,
  transactionId: number,
  file: File,
): Promise<AttachmentMeta> {
  const form = new FormData();
  // 3º argumento explícito: sem ele o nome do arquivo depende da implementação
  // de FormData e o backend acaba gravando "blob" como filename
  form.append('file', file, file.name);
  const response = await apiClient.post(
    `/workspaces/${workspaceId}/transactions/${transactionId}/attachments`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return response.data as AttachmentMeta;
}

export function useAttachments(transactionId: number | null) {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  const listQuery = useQuery({
    queryKey: ['attachments', currentWorkspaceId, transactionId],
    queryFn: async (): Promise<AttachmentMeta[]> => {
      const response = await apiClient.get(
        `/workspaces/${currentWorkspaceId}/transactions/${transactionId}/attachments`
      );
      return response.data;
    },
    enabled: !!currentWorkspaceId && !!transactionId,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['attachments', currentWorkspaceId, transactionId] });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!currentWorkspaceId || !transactionId) throw new Error('Transação não salva');
      return postAttachment(currentWorkspaceId, transactionId, file);
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/attachments/${id}`);
    },
    onSuccess: invalidate,
  });

  // Baixa autenticada (cookies) e abre em nova aba via blob URL
  const open = async (attachment: AttachmentMeta) => {
    const response = await apiClient.get(
      `/workspaces/${currentWorkspaceId}/attachments/${attachment.id}`,
      { responseType: 'blob' }
    );
    const url = URL.createObjectURL(
      new Blob([response.data], { type: attachment.content_type })
    );
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  return {
    attachments: listQuery.data || [],
    isLoading: listQuery.isLoading,
    upload: uploadMutation.mutateAsync,
    remove: deleteMutation.mutateAsync,
    open,
    isUploading: uploadMutation.isPending,
  };
}

export interface AttachmentUploadFailure {
  filename: string;
  message: string;
}

/** Sobe uma leva de anexos numa transação recém-criada — o id só existe depois
 * do POST da despesa, então na criação os arquivos esperam em memória e vêm
 * para cá. Nunca lança: a despesa já está salva, um anexo que falha vira aviso,
 * não erro de submit. */
export function useAttachmentUploader() {
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useUIStore();

  return React.useCallback(
    async (transactionId: number, files: File[]): Promise<AttachmentUploadFailure[]> => {
      const failures: AttachmentUploadFailure[] = [];
      if (!currentWorkspaceId) {
        return files.map((file) => ({ filename: file.name, message: 'workspace não selecionado' }));
      }
      for (const file of files) {
        try {
          await postAttachment(currentWorkspaceId, transactionId, file);
        } catch (err) {
          failures.push({ filename: file.name, message: getApiErrorMessage(err, 'falha no envio') });
        }
      }
      if (failures.length < files.length) {
        queryClient.invalidateQueries({ queryKey: ['attachments', currentWorkspaceId, transactionId] });
      }
      return failures;
    },
    [currentWorkspaceId, queryClient],
  );
}
