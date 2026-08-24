import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/** Papel no SITE (ADR 0026) — eixo separado do papel no workspace. */
export type PlatformRole = 'user' | 'admin' | 'superadmin';

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  is_active?: boolean;
  needs_onboarding?: boolean;
  /**
   * Decide se a navegação mostra o item "Admin". Só isso.
   *
   * Nada de autorização se apoia neste campo: quem barra é
   * `require_platform_role` no servidor, e as rotas administrativas respondem
   * 404 para quem não tem papel. Esconder o item é conveniência de interface —
   * se fosse a tranca, bastaria chamar a rota direto.
   */
  platform_role?: PlatformRole;
  /**
   * Token de cache da foto de perfil (8 primeiros do SHA-256 do conteúdo), ou
   * ausente para quem não tem foto. A URL é montada em `lib/avatar.ts`.
   */
  avatar_version?: string | null;
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

// Dialog global de "Nova despesa" — acionado pelo FAB (mobile), header e empty
// states de qualquer tela. NÃO persistido: não deve reabrir no reload.
interface NewTxState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const useNewTxStore = create<NewTxState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

// Detalhe/edição global de um lançamento — abre por id a partir de qualquer lugar
// que referencia a transação (Início, Lançamentos, Dívidas). 'view' = preview
// read-only; 'edit' = form completo. NÃO persistido.
type TxDetailMode = 'view' | 'edit';

interface TxDetailState {
  txId: number | null;
  mode: TxDetailMode;
  open: (txId: number, mode?: TxDetailMode) => void;
  setMode: (mode: TxDetailMode) => void;
  close: () => void;
}

export const useTxDetailStore = create<TxDetailState>((set) => ({
  txId: null,
  mode: 'view',
  open: (txId, mode = 'view') => set({ txId, mode }),
  setMode: (mode) => set({ mode }),
  close: () => set({ txId: null, mode: 'view' }),
}));
