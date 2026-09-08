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
  /** Quem tinha o foco quando o diálogo abriu — para devolvê-lo ao fechar. */
  origemDoFoco: HTMLElement | null;
  /*
   * Valores para o formulário nascer preenchido — o "Duplicar" do detalhe.
   *
   * Repetir um lançamento é o gesto mais comum que o app não tinha: o mesmo
   * mercado toda semana, a mesma mensalidade, a mesma corrida. Sem isso, a
   * pessoa abre o antigo, LÊ os campos, fecha, abre um novo e digita de novo o
   * que já estava na tela.
   *
   * O tipo é solto (`Record`) de propósito: `stores/` não deve conhecer o
   * formato do formulário de despesa. Quem semeia e quem consome são o mesmo
   * par de telas, e o tipo forte mora lá.
   */
  semente: Record<string, unknown> | null;
  /** Abre o diálogo já preenchido. */
  abrirCom: (semente: Record<string, unknown>) => void;
}

export const useNewTxStore = create<NewTxState>((set) => ({
  open: false,
  semente: null,
  abrirCom: (semente) => {
    const origem = document.activeElement;
    set({
      open: true,
      semente,
      origemDoFoco: origem instanceof HTMLElement ? origem : null,
    });
  },
  /*
   * Guarda quem ABRIU o diálogo e devolve o foco a ele ao fechar.
   *
   * O Radix faz isso sozinho quando o diálogo tem `DialogTrigger` — mas este é
   * global, acionado de um store a partir do FAB, do botão do cabeçalho e dos
   * estados vazios. Sem gatilho não há para onde voltar, e medimos o resultado:
   * depois do Escape, `document.activeElement` era o `<body>`. Para quem navega
   * por teclado isso significa recomeçar do início do documento — e a barra
   * lateral tem 21 itens antes do conteúdo.
   */
  setOpen: (open) => {
    if (open) {
      const origem = document.activeElement;
      set({ open: true, origemDoFoco: origem instanceof HTMLElement ? origem : null });
      return;
    }
    set((estado) => {
      const origem = estado.origemDoFoco;
      /*
       * O foco é devolvido no PRÓXIMO ciclo, e não aqui.
       *
       * O Radix também restaura foco ao desmontar um diálogo — inclusive o de
       * confirmação que pode ter aparecido por cima ("Descartar esta despesa?").
       * Restaurando de forma síncrona, a nossa chamada acontece primeiro e a do
       * Radix vem depois, apontando para um elemento que já saiu do DOM: o foco
       * termina no `<body>`, que é exatamente o que se queria corrigir.
       *
       * `isConnected`: o elemento pode ter saído do DOM enquanto o diálogo
       * estava aberto (a linha que o continha foi excluída, a lista recarregou).
       * Focar um nó órfão não faz nada e ainda deixa o foco no `<body>`.
       */
      setTimeout(() => {
        if (origem?.isConnected) origem.focus();
      }, 0);
      // A semente morre com o fechamento: o próximo "Nova despesa" tem de
      // nascer em branco, e não com a cópia do que se duplicou antes.
      return { open: false, origemDoFoco: null, semente: null };
    });
  },
  origemDoFoco: null,
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
