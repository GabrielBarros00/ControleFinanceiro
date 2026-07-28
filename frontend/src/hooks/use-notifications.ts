import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useAuthStore } from '@/stores';

export type NotificationType = 'workspace_invite' | 'member_added' | 'invite_revoked';

export interface AppNotification {
  id: number;
  type: NotificationType;
  title: string;
  body: string | null;
  workspace_id: number | null;
  workspace_name: string | null;
  invite_token: string | null;
  read_at: string | null;
  created_at: string;
}

interface NotificationListResponse {
  items: AppNotification[];
  unread: number;
}

/**
 * Avisos pessoais do usuário.
 *
 * Diferente do resto do app, isto NÃO passa pelo WebSocket: o canal de tempo
 * real é por sala de workspace, e quem recebe um convite ainda não é membro
 * daquele workspace — não teria como estar na sala. Por isso a lista é
 * revalidada por intervalo e ao voltar para a aba.
 */
export function useNotifications() {
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const query = useQuery({
    queryKey: ['notifications'],
    queryFn: async (): Promise<NotificationListResponse> => {
      const response = await apiClient.get('/notifications');
      return response.data;
    },
    enabled: isAuthenticated,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['notifications'] });
  };

  const markRead = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.post(`/notifications/${id}/read`);
    },
    onSuccess: invalidate,
  });

  const markAllRead = useMutation({
    mutationFn: async () => {
      await apiClient.post('/notifications/read-all');
    },
    onSuccess: invalidate,
  });

  const acceptInvite = useMutation({
    mutationFn: async (token: string) => {
      const response = await apiClient.post(`/invites/accept/${token}`);
      return response.data as { workspace_id: number };
    },
    onSuccess: () => {
      // Entrar num workspace muda tudo que a tela mostra
      queryClient.invalidateQueries();
    },
  });

  const declineInvite = useMutation({
    mutationFn: async (token: string) => {
      await apiClient.post(`/invites/decline/${token}`);
    },
    onSuccess: invalidate,
  });

  return {
    notifications: query.data?.items ?? [],
    unread: query.data?.unread ?? 0,
    isLoading: query.isLoading,
    markRead: markRead.mutateAsync,
    markAllRead: markAllRead.mutateAsync,
    acceptInvite: acceptInvite.mutateAsync,
    declineInvite: declineInvite.mutateAsync,
    isResponding: acceptInvite.isPending || declineInvite.isPending,
  };
}
