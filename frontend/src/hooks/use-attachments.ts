import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
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
      const form = new FormData();
      form.append('file', file);
      const response = await apiClient.post(
        `/workspaces/${currentWorkspaceId}/transactions/${transactionId}/attachments`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      return response.data as AttachmentMeta;
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
