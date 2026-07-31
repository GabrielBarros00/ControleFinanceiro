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
        const workspaces: { id: number; owner_user_id?: number | null }[] = wsResponse.data;
        // Respeita seleção persistida; só troca se inválida/ausente
        const persistedId = useUIStore.getState().currentWorkspaceId;
        const stillValid = workspaces.some((w) => w.id === persistedId);
        if (!stillValid) {
          // Default = o workspace PRÓPRIO. A lista vem ordenada por id, e quem
          // entrou por convite tem o workspace da outra pessoa em primeiro
          // (foi criado antes) — o app abria direto nas finanças da outra
          // família. Só cai no primeiro da lista quem não é dono de nenhum.
          const proprio = workspaces.find((w) => w.owner_user_id === user?.id);
          setCurrentWorkspaceId((proprio ?? workspaces[0])?.id ?? null);
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
      // `refetchQueries` AGUARDADO, não `invalidateQueries`. Invalidar só marca
      // a query como suja e volta na hora; o `mutateAsync` do login resolvia
      // antes de a sessão existir para o resto do app, e a tela navegava para
      // uma rota protegida que ainda não sabia quem era o usuário. Aguardando o
      // refetch, `loginMutation.isPending` cobre a transição inteira.
      await queryClient.refetchQueries({ queryKey: ['auth-me'] });
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
    // "Carregando" = **ainda não sei se há sessão**. Nunca mais que isso.
    //
    // Três condições, cada uma por um defeito já visto:
    //
    // - `isLoading` (a primeira carga, antes de qualquer resposta) e não
    //   `isFetching`: com `isFetching` puro, um refetch em segundo plano
    //   (foco da janela, reconexão) piscava a tela de carregamento e
    //   DESMONTAVA o que estivesse aberto — um diálogo em preenchimento, por
    //   exemplo.
    // - **Sem `isError` no cálculo**, e é por isso que ele não aparece aqui:
    //   sessão expirada tem de resolver para "não autenticado" e redirecionar
    //   para `/login`. Uma condição que continuasse verdadeira no erro deixava
    //   o usuário preso no spinner para sempre.
    // - As mutações cobrem a transição de login/cadastro por inteiro, porque o
    //   `onSuccess` do login AGUARDA o refetch de `auth-me` (ver acima). Era
    //   essa janela — mutação concluída, sessão ainda desconhecida — que fazia o
    //   cadastro cair em `/login` de forma intermitente.
    isLoading:
      meQuery.isLoading || loginMutation.isPending || registerMutation.isPending,
    error: loginMutation.error || registerMutation.error,
    login: loginMutation.mutateAsync,
    register: registerMutation.mutateAsync,
    logout: logoutMutation.mutateAsync,
  };
}
