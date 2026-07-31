import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useAuthStore } from '@/stores';
import { useWorkspaceId } from './use-workspace-id';

export type WorkspaceRole = 'owner' | 'admin' | 'member' | 'viewer';

/**
 * O que o membro pode VER — eixo separado do papel, que diz o que ele pode FAZER
 * (ADR 0018).
 *
 * `involved_only` (padrão) mostra só o que envolve a pessoa; `full_workspace`
 * abre os números da casa. O backend modelava os dois eixos desde a Onda 5, mas
 * o campo não existia em lugar nenhum do frontend: a permissão era concedível
 * apenas por chamada direta à API, e um admin não tinha como dá-la nem tirá-la
 * pela tela. `admin` e `owner` têm acesso completo pelo cargo e não são
 * rebaixáveis — por isso a UI não oferece o controle para eles.
 */
export type FinancialAccess = 'involved_only' | 'full_workspace';

export interface Member {
  user_id: number;
  role: WorkspaceRole;
  financial_access: FinancialAccess;
  user_name: string;
  user_email: string;
  joined_at: string;
}

export interface Invite {
  id: number;
  email: string | null;
  role: WorkspaceRole;
  financial_access: FinancialAccess;
  status: 'pending' | 'accepted' | 'revoked';
  expires_at: string;
  uses: number;
  max_uses: number | null;
}

export function useMembers() {
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceId();
  const currentUserId = useAuthStore((s) => s.user?.id);

  const membersQuery = useQuery({
    queryKey: ['members', currentWorkspaceId],
    queryFn: async (): Promise<Member[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/members`);
      return response.data;
    },
    enabled: !!currentWorkspaceId,
  });

  // A lista de convites é restrita a admin/owner no backend. Sem este gate, TODO
  // usuário disparava a requisição e levava 403 em cada carga de página — ruído
  // no log e uma ida à rede garantidamente inútil. O papel é derivado dos
  // membros já carregados (não dá para usar useWorkspaceRole aqui: ele depende
  // deste mesmo hook).
  const isAdmin = React.useMemo(() => {
    const eu = membersQuery.data?.find((m) => m.user_id === currentUserId);
    return eu?.role === 'admin' || eu?.role === 'owner';
  }, [membersQuery.data, currentUserId]);

  const invitesQuery = useQuery({
    queryKey: ['invites', currentWorkspaceId],
    queryFn: async (): Promise<Invite[]> => {
      const response = await apiClient.get(`/workspaces/${currentWorkspaceId}/invites`);
      return response.data;
    },
    enabled: !!currentWorkspaceId && isAdmin,
    retry: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['members', currentWorkspaceId] });
    queryClient.invalidateQueries({ queryKey: ['invites', currentWorkspaceId] });
  };

  const inviteByEmail = useMutation({
    mutationFn: async (data: {
      email: string; role: WorkspaceRole; financial_access?: FinancialAccess;
    }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/invites`, data);
      return response.data;
    },
    onSuccess: invalidate,
  });

  const createInviteLink = useMutation({
    mutationFn: async (data: {
      role: WorkspaceRole;
      financial_access?: FinancialAccess;
      expires_days?: number;
      max_uses?: number | null;
    }) => {
      const response = await apiClient.post(`/workspaces/${currentWorkspaceId}/invites/link`, data);
      return response.data as Invite & { token: string; url: string };
    },
    onSuccess: invalidate,
  });

  const revokeInvite = useMutation({
    mutationFn: async (inviteId: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/invites/${inviteId}`);
    },
    onSuccess: invalidate,
  });

  // Um PATCH para os dois eixos: `role` continua obrigatório no schema, então a
  // tela reenvia o papel atual quando muda só a visibilidade.
  const updateMember = useMutation({
    mutationFn: async ({ userId, role, financial_access }: {
      userId: number; role: WorkspaceRole; financial_access?: FinancialAccess;
    }) => {
      const response = await apiClient.patch(
        `/workspaces/${currentWorkspaceId}/members/${userId}`,
        financial_access ? { role, financial_access } : { role },
      );
      return response.data;
    },
    onSuccess: invalidate,
  });

  const removeMember = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/workspaces/${currentWorkspaceId}/members/${userId}`);
    },
    onSuccess: invalidate,
  });

  const leaveWorkspace = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/workspaces/${currentWorkspaceId}/leave`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries();
    },
  });

  return {
    members: membersQuery.data ?? [],
    invites: invitesQuery.data ?? [],
    isLoading: membersQuery.isLoading,
    inviteByEmail: inviteByEmail.mutateAsync,
    createInviteLink: createInviteLink.mutateAsync,
    revokeInvite: revokeInvite.mutateAsync,
    updateMember: updateMember.mutateAsync,
    removeMember: removeMember.mutateAsync,
    leaveWorkspace: leaveWorkspace.mutateAsync,
  };
}
