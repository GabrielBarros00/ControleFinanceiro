import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  is_active?: boolean;
  needs_onboarding?: boolean;
}

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  setUser: (user: AuthUser | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true, // Start loading while we check session
  error: null,
  setUser: (user) => set({ user, isAuthenticated: !!user, isLoading: false, error: null }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error, isLoading: false }),
  logout: () => set({ user: null, isAuthenticated: false, isLoading: false, error: null }),
}));

interface UIState {
  currentWorkspaceId: number | null;
  setCurrentWorkspaceId: (id: number | null) => void;
}

// Persistido: manter o workspace selecionado entre sessões/reloads
export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      currentWorkspaceId: null,
      setCurrentWorkspaceId: (id) => set({ currentWorkspaceId: id }),
    }),
    { name: 'cf4-ui' }
  )
);
