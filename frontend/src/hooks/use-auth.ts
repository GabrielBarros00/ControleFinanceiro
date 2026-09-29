import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { getApiErrorMessage } from '@/lib/api-error';
import { useAuthStore, useUIStore, type AuthUser } from '@/stores';
import { esquecerSeqsDoBootstrap, registrarSeqDoBootstrap } from '@/lib/seq-do-bootstrap';

/**
 * Rotas que existem justamente para quem NÃO tem sessão.
 *
 * Sondar `/auth/me` nelas é garantir um 401 — e o navegador registra toda
 * resposta de erro no console, então a tela de cadastro abria com dois erros de
 * rede (`/auth/me` e o `/auth/refresh` que o interceptor dispara em seguida)
 * antes de o usuário digitar qualquer coisa. A suíte que proíbe erro no console
 * só olhava rotas protegidas e não via nada disso.
 */
const ROTAS_PUBLICAS = ['/login', '/register', '/forgot-password', '/reset-password'];

function emRotaPublica(): boolean {
  return ROTAS_PUBLICAS.includes(window.location.pathname);
}

/**
 * "O servidor não respondeu" é diferente de "o servidor disse que você não está
 * logado" — e o app tratava as duas como a segunda.
 *
 * Com a API fora do ar, recarregar qualquer página levava à tela de **login**:
 * "Bem-vindo, entre com suas credenciais". A sessão estava viva; o app só não
 * tinha conseguido perguntar. Para quem usa um app de finanças, "sua sessão
 * sumiu" é uma mensagem cara — e a pessoa digita a senha, que também falha,
 * agora com um erro de credencial que não tem nada a ver com o problema.
 *
 * Sem `response` = a requisição não chegou (rede, DNS, servidor parado).
 * 5xx = chegou e o servidor quebrou. Nos dois casos a resposta honesta é
 * "não deu para falar com o servidor", com um botão de tentar de novo.
 */
export function ehFalhaDeInfraestrutura(erro: unknown): boolean {
  const status = (erro as { response?: { status?: number } })?.response?.status;
  if (status === undefined) return true;
  return status >= 500;
}

/*
 * Prazo de cada tentativa da carga da sessão — menor que o padrão do cliente.
 *
 * É esta carga que segura a tela inteira em "Carregando sua sessão…". Depois do
 * aparelho dormir, a primeira requisição pode sair por uma conexão morta e não
 * voltar nunca; com 10 s ela vira falha de rede, e o `retry` da `auth-me` tenta
 * de novo — já por outra conexão, que é o que o F5 fazia.
 */
export const PRAZO_DA_SESSAO_MS = 10_000;

/**
 * A sessão + a seleção de workspace, fora do hook para poder ser chamada de dois
 * lugares: como `queryFn` da `auth-me` e diretamente pelo login (ver abaixo por
 * que o login não pode depender de refetch).
 */
async function buscarSessao(
  setUser: (user: AuthUser | null) => void,
  clearStore: () => void,
  setCurrentWorkspaceId: (id: number | null) => void,
  semearEspacos: (espacos: unknown[]) => void,
  /** Esta é a carga que libera a página? Só ela registra o seq (`lib/seq-do-bootstrap.ts`). */
  registrarSeq: boolean,
) {
  /*
   * As duas JUNTAS, e não uma depois da outra (auditoria 2026-09-26, P5): a
   * primeira tela esperava duas idas e voltas antes de começar a buscar os dados
   * dela — com rede lenta, ~3 s em "Carregando sua sessão…".
   *
   * Não quebra o que a Onda 5 construiu em cima desta função: o seq do
   * `/workspaces/` continua lido ANTES de qualquer consulta da página, porque a
   * `ProtectedRoute` só desenha quando esta função inteira termina. E sessão
   * expirada não dispara duas renovações: o interceptor de 401 é single-flight.
   */
  const [sessao, espacos] = await Promise.allSettled([
    apiClient.get('/auth/me', { timeout: PRAZO_DA_SESSAO_MS }),
    apiClient.get('/workspaces/', { timeout: PRAZO_DA_SESSAO_MS }),
  ]);
  if (sessao.status === 'rejected') {
    // Só o servidor dizendo "não há sessão" apaga o espelho. Uma falha de rede
    // num refetch em segundo plano (a volta da aba com a conexão ainda subindo)
    // desligava o tempo real e os avisos de quem continuava logado.
    if (!ehFalhaDeInfraestrutura(sessao.reason)) clearStore();
    throw sessao.reason;
  }
  const user = sessao.value.data;
  setUser(user);

  // Falha ao listar workspaces não derruba a sessão (só a seleção fica como está)
  try {
    if (espacos.status === 'rejected') throw espacos.reason;
    const workspaces: { id: number; owner_user_id?: number | null; event_seq?: number }[] = espacos.value.data;
    if (registrarSeq) registrarSeqDoBootstrap(workspaces);
    // A mesma lista que `useWorkspaces` buscaria de novo logo em seguida: com o
    // cache semeado, a barra lateral e o seletor já a têm.
    semearEspacos(workspaces);
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
}

export function useAuth() {
  const queryClient = useQueryClient();
  const { setUser, logout: clearStore, setError } = useAuthStore();
  const { setCurrentWorkspaceId } = useUIStore();

  // `undefined` = nenhuma sessão carregada ainda nesta aba (primeira carga, ou
  // depois do logout, que limpa o cache): é a carga que libera a página.
  const carregarSessao = () => buscarSessao(
    setUser, clearStore, setCurrentWorkspaceId,
    (espacos) => queryClient.setQueryData(['workspaces'], espacos),
    queryClient.getQueryData(['auth-me']) === undefined,
  );

  // Check current session
  const meQuery = useQuery({
    queryKey: ['auth-me'],
    queryFn: carregarSessao,
    // Em rota pública não há o que sondar. O `enabled` é lido a cada render, e
    // todo componente que usa este hook está dentro do Router — a navegação
    // re-renderiza e a sonda liga sozinha ao entrar numa rota protegida.
    //
    // Isto NÃO é a mesma coisa que pôr `/auth/me` na lista `AUTH_URLS` do
    // interceptor: lá o 401 é o sinal de "access token venceu, renove", e
    // bloqueá-lo derrubaria a sessão de quem só recarregou a página.
    enabled: !emRotaPublica(),
    // Nunca insistir num 401 — ele é uma RESPOSTA ("não há sessão"), não uma
    // falha. Mas insistir em queda de rede e em 5xx, que são falhas de verdade
    // e costumam durar segundos: sem isso, um soluço de conexão já mandava para
    // a tela de login quem tinha sessão válida.
    retry: (tentativas, erro) => ehFalhaDeInfraestrutura(erro) && tentativas < 2,
    staleTime: 1000 * 60 * 5,
  });

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: async (credentials: { email: string; password: string }) => {
      const response = await apiClient.post('/auth/login', credentials);
      return response.data;
    },
    onSuccess: async () => {
      // `fetchQuery` AGUARDADO, e nenhuma das duas alternativas serve:
      //
      // - `invalidateQueries` só marca a query como suja e volta na hora; o
      //   `mutateAsync` do login resolvia antes de a sessão existir para o resto
      //   do app, e a tela navegava para uma rota protegida que ainda não sabia
      //   quem era o usuário.
      // - `refetchQueries` resolvia isso, mas **ignora query desabilitada** — e
      //   o login acontece justamente em `/login`, onde a sonda está desligada
      //   de propósito (ver `enabled` acima). Com ele, entrar deixaria de
      //   estabelecer a sessão.
      //
      // `fetchQuery` não olha para `enabled`, popula o cache com a MESMA chave e
      // continua sendo aguardado — então `loginMutation.isPending` segue
      // cobrindo a transição inteira, que é o que fazia o cadastro cair em
      // `/login` de forma intermitente.
      await queryClient.fetchQuery({
        queryKey: ['auth-me'],
        queryFn: carregarSessao,
        staleTime: 0,
      });
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
      esquecerSeqsDoBootstrap();
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
    /**
     * Não deu para falar com o servidor — que NÃO é a mesma coisa que estar
     * deslogado. Quem consome isto é o `ProtectedRoute`: com esta bandeira ele
     * mostra "sem conexão" e um botão de tentar de novo, em vez de mandar para
     * a tela de login alguém cuja sessão está perfeitamente viva.
     */
    //
    // Só enquanto a sessão nunca foi conhecida (`data` ainda `undefined`). Com
    // a pessoa já dentro, um refetch que falha por rede (a volta da aba, com o
    // Wi-Fi ainda conectando) trocava o app INTEIRO por esta tela — os dados que
    // estavam à vista sumiam por causa de uma checagem de fundo. Cada tela já
    // mostra o erro das próprias consultas.
    //
    // `isPaused` cobre o outro lado da mesma moeda: sem rede, o react-query nem
    // tenta — a consulta fica pausada, sem erro e sem "carregando", e o guard
    // concluía "não há sessão" e mandava para o login.
    falhaDeConexao:
      meQuery.data === undefined &&
      ((meQuery.isError && ehFalhaDeInfraestrutura(meQuery.error)) ||
        (meQuery.isPending && meQuery.isPaused)),
    tentarSessaoDeNovo: () => meQuery.refetch(),
    error: loginMutation.error || registerMutation.error,
    login: loginMutation.mutateAsync,
    register: registerMutation.mutateAsync,
    logout: logoutMutation.mutateAsync,
  };
}
