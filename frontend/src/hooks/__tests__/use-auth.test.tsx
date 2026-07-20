import { renderHook, waitFor } from '@testing-library/react';
import { useAuth } from '../use-auth';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from '@/stores';

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
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
  });
});
