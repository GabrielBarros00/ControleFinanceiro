import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { useAuthStore, type PlatformRole } from '@/stores';

/**
 * Administração do SITE (ADR 0026).
 *
 * Tudo o que sai daqui é metadado — contagem, tamanho, data, papel,
 * configuração. Nenhum destes tipos tem campo de valor financeiro, e isso é
 * decisão de projeto, não omissão: o administrador opera o servidor, a vida
 * financeira de cada um continua sendo dela (ADRs 0018 e 0021).
 */

export interface AdminOverview {
  usuarios_total: number;
  usuarios_ativos: number;
  usuarios_novos_30d: number;
  workspaces: number;
  lancamentos: number;
  anexos_bytes: number;
  anexos_qtd: number;
  convites_pendentes: number;
  sessoes_vivas: number;
  banco_bytes: number | null;
}

export interface AdminUser {
  id: number;
  name: string;
  email: string;
  is_active: boolean;
  platform_role: PlatformRole;
  created_at: string;
  deleted_at: string | null;
  needs_onboarding: boolean;
  last_login_at: string | null;
  workspaces: number;
  lancamentos: number;
  anexos_bytes: number;
}

export interface AdminUsersPage {
  total: number;
  items: AdminUser[];
  limit: number;
  offset: number;
}

export interface AdminSaude {
  cambio_ultima_data: string | null;
  cambio_cotacoes: number;
  banco_bytes: number | null;
  anexos_bytes: number;
  sessoes_expiradas_pendentes_de_expurgo: number;
  auditoria_linhas: number;
  auditoria_mais_antiga: string | null;
}

export interface ChaveDeConfiguracao {
  nome: string;
  descricao: string;
  origem_ambiente: string | null;
  /** Veio do banco (o admin gravou) ou ainda acompanha o `.env`. */
  sobrescrito: boolean;
}

export interface AdminSettings {
  valores: Record<string, unknown>;
  chaves: ChaveDeConfiguracao[];
  limite_nginx_bytes: number;
}

export interface RegistrationInvite {
  id: number;
  email: string | null;
  token: string;
  status: 'pending' | 'accepted' | 'revoked';
  expires_at: string;
  max_uses: number | null;
  uses: number;
  created_by_user_id: number | null;
  accepted_by_user_id: number | null;
  created_at: string;
  link: string;
}

export interface AdminAuditRow {
  id: number;
  action: string;
  resource_type: string | null;
  resource_id: number | null;
  user_id: number | null;
  workspace_id: number | null;
  ip_address: string | null;
  created_at: string;
}

/** Se a pessoa logada opera o site. Usado só para exibir/ocultar a área. */
export function useIsPlatformAdmin(): boolean {
  const papel = useAuthStore((s) => s.user?.platform_role);
  return papel === 'admin' || papel === 'superadmin';
}

export function useIsSuperadmin(): boolean {
  return useAuthStore((s) => s.user?.platform_role) === 'superadmin';
}

export function useAdminOverview() {
  const habilitado = useIsPlatformAdmin();
  return useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: async (): Promise<AdminOverview> =>
      (await apiClient.get('/admin/overview')).data,
    // Sem este gate, TODO usuário dispararia a requisição e levaria 404 em cada
    // carga de página — ruído no console e uma ida à rede garantidamente inútil.
    // É o mesmo cuidado que `useMembers` tem com a lista de convites.
    enabled: habilitado,
  });
}

export function useAdminSaude() {
  const habilitado = useIsPlatformAdmin();
  return useQuery({
    queryKey: ['admin', 'saude'],
    queryFn: async (): Promise<AdminSaude> => (await apiClient.get('/admin/health')).data,
    enabled: habilitado,
  });
}

export function useAdminUsers(params: { busca?: string; offset?: number } = {}) {
  const habilitado = useIsPlatformAdmin();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['admin', 'users', params.busca ?? '', params.offset ?? 0],
    queryFn: async (): Promise<AdminUsersPage> =>
      (
        await apiClient.get('/admin/users', {
          params: { busca: params.busca || undefined, offset: params.offset ?? 0 },
        })
      ).data,
    enabled: habilitado,
  });

  // Toda mutação invalida `['admin']` inteiro: mudar um papel ou desativar
  // alguém mexe na lista E nos números da visão geral, e invalidar só a lista
  // deixaria os totais do topo mentindo até o próximo F5.
  const invalidar = () => queryClient.invalidateQueries({ queryKey: ['admin'] });

  const patch = useMutation({
    mutationFn: async (dados: {
      userId: number;
      is_active?: boolean;
      platform_role?: PlatformRole;
    }) => {
      const { userId, ...corpo } = dados;
      return (await apiClient.patch(`/admin/users/${userId}`, corpo)).data;
    },
    onSuccess: invalidar,
  });

  const revogarSessoes = useMutation({
    mutationFn: async (userId: number) =>
      (await apiClient.post(`/admin/users/${userId}/revoke-sessions`)).data,
    onSuccess: invalidar,
  });

  const remover = useMutation({
    mutationFn: async (userId: number) =>
      (await apiClient.delete(`/admin/users/${userId}`)).data,
    onSuccess: invalidar,
  });

  return { ...query, patch, revogarSessoes, remover };
}

export function useAdminSettings() {
  const habilitado = useIsPlatformAdmin();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['admin', 'settings'],
    queryFn: async (): Promise<AdminSettings> => (await apiClient.get('/admin/settings')).data,
    enabled: habilitado,
  });

  const salvar = useMutation({
    mutationFn: async (valores: Record<string, unknown>) =>
      (await apiClient.put('/admin/settings', { valores })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin'] }),
  });

  const testarEmail = useMutation({
    mutationFn: async (para: string) =>
      (await apiClient.post('/admin/settings/test-email', { para })).data as {
        enviado: boolean;
        configurado: boolean;
        detalhe: string | null;
        /** Host:porta por onde o envio saiu — pode não ser a porta do `.env`. */
        rota: string | null;
      },
  });

  return { ...query, salvar, testarEmail };
}

export function useRegistrationInvites() {
  const habilitado = useIsPlatformAdmin();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['admin', 'invites'],
    queryFn: async (): Promise<RegistrationInvite[]> =>
      (await apiClient.get('/admin/registration-invites')).data,
    enabled: habilitado,
  });

  const criar = useMutation({
    mutationFn: async (dados: { email?: string; max_uses?: number }) =>
      (await apiClient.post('/admin/registration-invites', dados)).data as RegistrationInvite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin'] }),
  });

  const revogar = useMutation({
    mutationFn: async (id: number) =>
      (await apiClient.delete(`/admin/registration-invites/${id}`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin'] }),
  });

  return { ...query, criar, revogar };
}

export function useAdminAudit(filtros: { resource_type?: string } = {}) {
  const habilitado = useIsPlatformAdmin();
  return useQuery({
    queryKey: ['admin', 'audit', filtros.resource_type ?? ''],
    queryFn: async (): Promise<AdminAuditRow[]> =>
      (
        await apiClient.get('/admin/audit', {
          params: { resource_type: filtros.resource_type || undefined },
        })
      ).data,
    enabled: habilitado,
  });
}

/**
 * Convite de cadastro emitido por usuário COMUM — fora da área administrativa.
 *
 * Vive neste arquivo porque compartilha os tipos, mas a rota é `/me/...` e não
 * exige papel de plataforma: é o "chame alguém para o site" de quem já está
 * dentro, limitado por `who_can_invite` e pela cota mensal.
 */
export function useMeusConvitesDeCadastro() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['me', 'registration-invites'],
    queryFn: async (): Promise<RegistrationInvite[]> =>
      (await apiClient.get('/me/registration-invites')).data,
  });

  const convidar = useMutation({
    mutationFn: async (dados: { email?: string }) =>
      (await apiClient.post('/me/registration-invites', dados)).data as RegistrationInvite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['me', 'registration-invites'] }),
  });

  return { ...query, convidar };
}
