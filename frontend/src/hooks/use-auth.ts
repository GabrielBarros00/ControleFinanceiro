import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';
import { useAuthStore, useUIStore } from '@/stores';

export function useAuth() {
  const queryClient = useQueryClient();
  const { setUser, logout: clearStore, setError } = useAuthStore();
  const { setCurrentWorkspaceId } = useUIStore();

  // Check current session
  const meQuery = useQuery({
    queryKey: ['auth-me'],
    queryFn: async () => {
      let user;
      try {
        const response = await apiClient.get('/auth/me');
        user = response.data;
      } catch (err) {
        clearStore();
        throw err;
      }
      setUser(user);

      // Falha ao listar workspaces não derruba a sessão (só a seleção fica como está)
      try {
        const wsResponse = await apiClient.get('/workspaces/');
        const workspaces = wsResponse.data;
        // Respeita seleção persistida; só troca se inválida/ausente
        const persistedId = useUIStore.getState().currentWorkspaceId;
        const stillValid = workspaces.some((w: { id: number }) => w.id === persistedId);
        if (!stillValid) {
          setCurrentWorkspaceId(workspaces.length > 0 ? workspaces[0].id : null);
        }
      } catch {
        // mantém sessão; hooks de workspace refazem a busca depois
      }

      return user;
    },
    retry: false,
    staleTime: 1000 * 60 * 5,
  });

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: async (credentials: { email: string; password: string }) => {
      const response = await apiClient.post('/auth/login', credentials);
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth-me'] });
    },
    onError: (error: unknown) => {
      setError(getApiErrorMessage(error, 'Erro ao realizar login'));
    }
  });

  // Register mutation
  const registerMutation = useMutation({
    // `invite_token` vem do link `/register?invite=<token>` e é o CONSENTIMENTO
    // de entrar naquele workspace. Sem ele o backend só cria a notificação.
    mutationFn: async (data: {
      name: string; email: string; password: string; invite_token?: string;
    }) => {
      const response = await apiClient.post('/auth/register', data);
      return response.data;
    },
    onSuccess: async () => {
      // Auto-login after registration could be implemented here or managed by the page
    },
    onError: (error: unknown) => {
      setError(getApiErrorMessage(error, 'Erro ao criar conta'));
    }
  });

  // Logout mutation
  const logoutMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post('/auth/logout');
    },
    onSuccess: () => {
      clearStore();
      // Limpa o cache INTEIRO, não só o ['auth-me']: as queries do usuário que
      // saiu (extrato, dívidas, membros, faturas) continuavam em memória e
      // apareciam para quem entrasse em seguida, no intervalo até o refetch —
      // numa máquina compartilhada isso é a finança de uma pessoa na tela de
      // outra. O `currentWorkspaceId` persistido já era revalidado; o cache não.
      queryClient.clear();
    }
  });

  return {
    user: meQuery.data,
    isAuthenticated: !!meQuery.data,
    isLoading: meQuery.isLoading || loginMutation.isPending || registerMutation.isPending,
    error: loginMutation.error || registerMutation.error,
    login: loginMutation.mutateAsync,
    register: registerMutation.mutateAsync,
    logout: logoutMutation.mutateAsync,
  };
}
