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
        // Sessão realmente expirada: o ProtectedRoute redireciona ao ver que
        // não há usuário.
        useAuthStore.getState().logout();
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
