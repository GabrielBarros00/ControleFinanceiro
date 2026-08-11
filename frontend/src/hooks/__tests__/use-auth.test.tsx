import { renderHook, waitFor } from '@testing-library/react';
import { useAuth } from '../use-auth';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { useAuthStore } from '@/stores';
import { registerQueryClient } from '@/api/client';

const createTestQueryClient = () => new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

describe('useAuth', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    // O interceptor de 401 age sobre o client REGISTRADO (o App faz isso no
    // boot). Sem registrar o do teste, a limpeza de cache na sessão expirada
    // não seria exercida e o teste mediria um caminho que não existe.
    registerQueryClient(queryClient);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it('should return user data when authenticated', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.user).toEqual({
      id: 1,
      name: 'Test User',
      email: 'test@example.com',
      is_active: true,
      needs_onboarding: false,
    });
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('should return null when not authenticated', async () => {
    server.use(
      http.get('http://localhost:8000/api/v1/auth/me', () => {
        return new HttpResponse(null, { status: 401 });
      })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.user).toBeFalsy();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('should call login and refetch user', async () => {
    let loginCalled = false;
    server.use(
      http.post('http://localhost:8000/api/v1/auth/login', () => {
        loginCalled = true;
        return HttpResponse.json({ message: 'Success' });
      })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    
    await result.current.login({ email: 'test@example.com', password: 'password' });
    
    expect(loginCalled).toBe(true);
  });

  it('should call register', async () => {
    let registerCalled = false;
    server.use(
      http.post('http://localhost:8000/api/v1/auth/register', () => {
        registerCalled = true;
        return HttpResponse.json({ id: 2, name: 'New User' });
      })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    
    await result.current.register({ name: 'New User', email: 'new@example.com', password: 'password' });
    
    expect(registerCalled).toBe(true);
  });

  it('surfaces the backend error message (envelope {error:{message}}) on login failure', async () => {
    // O backend responde no formato {"error":{"message":...}} — não em {detail}.
    server.use(
      http.post('http://localhost:8000/api/v1/auth/login', () => {
        return HttpResponse.json(
          { error: { code: 'UNAUTHORIZED', message: 'Esta conta usa login com Google.', details: {} } },
          { status: 401 }
        );
      })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });

    await expect(
      result.current.login({ email: 'g@example.com', password: 'x' })
    ).rejects.toBeTruthy();

    await waitFor(() =>
      expect(useAuthStore.getState().error).toBe('Esta conta usa login com Google.')
    );
  });

  it('should call logout and clear data', async () => {
    let logoutCalled = false;
    server.use(
      http.post('http://localhost:8000/api/v1/auth/logout', () => {
        logoutCalled = true;
        return HttpResponse.json({ message: 'Logged out' });
      })
    );

    const { result } = renderHook(() => useAuth(), { wrapper });

    await result.current.logout();

    expect(logoutCalled).toBe(true);
    // `undefined` (e não `null`): o logout descarta o cache INTEIRO com
    // queryClient.clear(), em vez de só sobrescrever ['auth-me'] com null. O que
    // importa é não sobrar dado do usuário anterior para quem entrar depois.
    expect(result.current.user).toBeFalsy();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('sessão expirada resolve para "não autenticado" sem entrar em laço', async () => {
    /*
     * A regressão que travou o app: com a sessão expirada, `/auth/me` dava 401,
     * o interceptor tentava `/auth/refresh` (também 401) e limpava o cache
     * INTEIRO — inclusive a própria `auth-me`. Remover uma query com observador
     * montado faz o react-query refazê-la na hora, então o ciclo recomeçava:
     * dezenas de me→refresh por segundo, e a tela presa no spinner porque
     * `isLoading` nunca virava `false`.
     *
     * O teste mede as duas coisas que importam: o estado ASSENTA em "não
     * autenticado" (é assim que o ProtectedRoute manda para /login) e o número
     * de idas ao servidor é pequeno e PARA de crescer.
     */
    let chamadasMe = 0;
    let chamadasRefresh = 0;
    server.use(
      http.get('http://localhost:8000/api/v1/auth/me', () => {
        chamadasMe += 1;
        return new HttpResponse(null, { status: 401 });
      }),
      http.post('http://localhost:8000/api/v1/auth/refresh', () => {
        chamadasRefresh += 1;
        return new HttpResponse(null, { status: 401 });
      }),
    );

    // Cache de outra tela: tem de sumir mesmo com a `auth-me` preservada
    queryClient.setQueryData(['transactions', 1], { items: [{ id: 7 }] });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(queryClient.getQueryData(['transactions', 1])).toBeUndefined();

    const depoisDoPrimeiro = chamadasMe;
    await new Promise((r) => setTimeout(r, 300));
    expect(chamadasMe).toBe(depoisDoPrimeiro);
    // O piso importa tanto quanto o teto: em rota PROTEGIDA, o 401 de
    // `/auth/me` significa "o access token venceu" e TEM de tentar renovar. Uma
    // auditoria sugeriu calar esse refresh pondo `/auth/me` na lista `AUTH_URLS`
    // para acabar com o barulho no console das telas públicas — o barulho é
    // real, mas a cura seria derrubar a sessão de todo mundo que só recarregou
    // a página. O silêncio nas telas públicas veio do `enabled` (ver abaixo).
    expect(chamadasRefresh).toBeGreaterThanOrEqual(1);
    expect(chamadasRefresh).toBeLessThanOrEqual(2);
  });

  it('logout descarta o cache de TODAS as queries, não só o auth-me', async () => {
    server.use(
      http.post('http://localhost:8000/api/v1/auth/logout', () =>
        HttpResponse.json({ message: 'Logged out' })
      )
    );

    // Dado de outra família, como o extrato do usuário que está saindo
    queryClient.setQueryData(['transactions', 1], { items: [{ id: 7, title: 'Segredo' }] });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await result.current.logout();

    // Numa máquina compartilhada, isto ficava em memória e aparecia na tela do
    // próximo usuário no intervalo até o refetch.
    expect(queryClient.getQueryData(['transactions', 1])).toBeUndefined();
  });

  describe('rota pública', () => {
    /*
     * Em `/login` e `/register` não existe sessão a sondar: `/auth/me` responde
     * 401 e o interceptor ainda tenta `/auth/refresh`, que responde 401 também.
     * Nada quebra, mas a página abre com dois erros de rede no console antes de
     * o usuário digitar qualquer coisa.
     *
     * `window.location.pathname` é o que o hook lê; no jsdom o padrão é `/`, que
     * NÃO é rota pública — por isso todos os testes acima seguem exercitando a
     * sonda ligada.
     */
    const irPara = (caminho: string) => {
      window.history.pushState({}, '', caminho);
    };

    afterEach(() => irPara('/'));

    it('não sonda /auth/me na tela de cadastro', async () => {
      let chamadasMe = 0;
      let chamadasRefresh = 0;
      server.use(
        http.get('http://localhost:8000/api/v1/auth/me', () => {
          chamadasMe += 1;
          return new HttpResponse(null, { status: 401 });
        }),
        http.post('http://localhost:8000/api/v1/auth/refresh', () => {
          chamadasRefresh += 1;
          return new HttpResponse(null, { status: 401 });
        }),
      );
      irPara('/register');

      const { result } = renderHook(() => useAuth(), { wrapper });

      await new Promise((r) => setTimeout(r, 200));
      expect(chamadasMe).toBe(0);
      expect(chamadasRefresh).toBe(0);
      // E o guard não pode ficar preso: "não sei se há sessão" tem de resolver
      expect(result.current.isLoading).toBe(false);
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('o login estabelece a sessão MESMO partindo de /login', async () => {
      /*
       * A armadilha desta mudança: `refetchQueries` ignora query desabilitada, e
       * o login acontece justamente na rota onde a sonda está desligada. Se o
       * `onSuccess` voltar a usá-lo, o login passa a resolver sem sessão — e o
       * usuário cai de volta em `/login` depois de entrar com a senha certa.
       */
      server.use(
        http.post('http://localhost:8000/api/v1/auth/login', () =>
          HttpResponse.json({ message: 'Success' })
        ),
      );
      irPara('/login');

      const { result } = renderHook(() => useAuth(), { wrapper });
      await result.current.login({ email: 'test@example.com', password: 'password' });

      await waitFor(() =>
        expect(queryClient.getQueryData(['auth-me'])).toMatchObject({
          email: 'test@example.com',
        })
      );
      expect(useAuthStore.getState().isAuthenticated).toBe(true);
    });
  });
});
