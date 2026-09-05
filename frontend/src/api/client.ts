import axios from 'axios';
import type { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores';

// O QueryClient é criado no App; o interceptor precisa dele para descartar o
// cache quando a sessão morre de vez (mesma limpeza do logout explícito). Sem
// isto, expirar a sessão deixava os dados do usuário em memória para a próxima
// pessoa que entrasse no mesmo navegador.
let queryClientRef: QueryClient | null = null;

export function registerQueryClient(client: QueryClient): void {
  queryClientRef = client;
}

export const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

export const apiClient = axios.create({
  baseURL,
  withCredentials: true, // Crucial for JWT cookies
  headers: {
    'Content-Type': 'application/json',
  },
  // FastAPI lê lista como parâmetro REPETIDO (`?source=a&source=b`); o padrão do
  // Axios serializa `source[]=a`, que o backend ignora SEM ERRO — 200, resposta
  // completa, filtro nenhum. No Extrato global o botão ficava marcado, a URL da
  // tela dizia `?source=income` e a tabela continuava mostrando tudo, totais
  // inclusive. O teste que existia mockava o hook e só via o array em memória:
  // a serialização HTTP nunca era exercitada (ver use-overview.serializacao).
  paramsSerializer: { indexes: null },
});

// Rotas de auth nunca disparam refresh (evita loop em login/refresh inválidos)
const AUTH_URLS = [
  '/auth/login',
  '/auth/register',
  '/auth/refresh',
  '/auth/logout',
  '/auth/forgot-password',
  '/auth/reset-password',
];

let refreshPromise: Promise<unknown> | null = null;

// Interceptor 401: tenta renovar a sessão via cookie refresh_token e repete a
// request original. Single-flight: várias 401 simultâneas disparam um único refresh.
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    const url: string = original?.url ?? '';
    const isAuthUrl = AUTH_URLS.some((u) => url.includes(u));

    if (status === 401 && original && !original._retry && !isAuthUrl) {
      original._retry = true;
      try {
        refreshPromise =
          refreshPromise ??
          apiClient.post('/auth/refresh').finally(() => {
            refreshPromise = null;
          });
        await refreshPromise;
        return apiClient(original);
      } catch {
        // Sessão realmente expirada.
        useAuthStore.getState().logout();
        /*
         * E é PRECISO derrubar também a `auth-me` do react-query — o store
         * sozinho não basta, e essa era a causa do "app travado".
         *
         * O comentário que existia aqui dizia "o ProtectedRoute redireciona ao
         * ver que não há usuário". Isso deixou de ser verdade quando o guard
         * passou a ler `useAuth()` (react-query) em vez do espelho em Zustand —
         * mudança certa, feita para resolver outra corrida, que deixou esta
         * linha órfã. Resultado medido: com o app ABERTO e a sessão expirando,
         * o guard continuava vendo `auth-me` no cache com dados válidos, dava a
         * sessão por viva e a tela girava para sempre. Só um F5 saía disso, e o
         * usuário não tinha como saber disso.
         *
         * `setQueryData(null)` e NÃO `removeQueries`: remover uma query com
         * observador montado faz o react-query refazê-la na hora, e o laço
         * `/auth/me` → 401 → `/auth/refresh` → 401 → … volta (é o defeito que o
         * `predicate` logo abaixo foi escrito para evitar). Definir o dado como
         * nulo deixa a query parada, com a resposta correta: não há sessão.
         */
        queryClientRef?.setQueryData(['auth-me'], null);
        // Descarta o cache do usuário que saiu — MENOS a própria `auth-me`.
        //
        // `queryClient.clear()` removia tudo, inclusive ela. E remover uma query
        // que tem observador montado faz o react-query montá-la de novo na hora:
        // `/auth/me` → 401 → `/auth/refresh` → 401 → clear() → `/auth/me` …
        // Era um laço fechado, dezenas de requisições por segundo, com a tela
        // presa no spinner porque a sessão nunca resolvia. Deixando a `auth-me`
        // no cache, ela fica em estado de ERRO — que é a resposta correta
        // ("não há sessão") e não dispara nada.
        queryClientRef?.removeQueries({
          predicate: (query) => query.queryKey[0] !== 'auth-me',
        });
      }
    }
    return Promise.reject(error);
  }
);
