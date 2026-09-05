import { create } from 'zustand';

export type ToastVariant = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
  duration: number; // ms; <= 0 nunca fecha sozinho
  /**
   * Uma ação no próprio aviso — hoje só "Desfazer".
   *
   * Ela existe porque a alternativa ao desfazer é a confirmação: perguntar
   * "tem certeza?" a cada exclusão treina a pessoa a responder "sim" sem ler, e
   * aí o diálogo não protege mais nada. Deixar agir e oferecer a volta protege
   * de verdade e não cobra nada de quem acertou.
   *
   * O aviso com ação fica MAIS TEMPO na tela (ver `toast.comAcao`): 5 segundos
   * para ler, decidir e alcançar o botão é pouco.
   */
  action?: { label: string; onClick: () => void };
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, 'id'>) => string;
  dismiss: (id: string) => void;
}

// Store leve para toasts. O helper imperativo `toast.*` abaixo funciona fora de
// componentes React (ex.: catch de handlers) via getState().
export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => {
    const id = Math.random().toString(36).slice(2);
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }));
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));

const DEFAULT_DURATION = 5000;

function push(variant: ToastVariant, title: string, description?: string, duration = DEFAULT_DURATION) {
  return useToastStore.getState().push({ variant, title, description, duration });
}

export const toast = {
  /**
   * Aviso com um botão — o "Desfazer" da exclusão.
   *
   * Dez segundos, e não os cinco padrão: o aviso comum é só informação e pode
   * sumir; este é uma janela de decisão, e ela precisa durar o tempo de ler,
   * entender que a linha errada sumiu e mover o ponteiro até o botão.
   */
  comAcao: (
    title: string,
    action: { label: string; onClick: () => void },
    description?: string,
  ) => useToastStore.getState().push({
    variant: 'info', title, description, duration: 10_000, action,
  }),
  success: (title: string, description?: string) => push('success', title, description),
  // Erros ficam um pouco mais na tela
  error: (title: string, description?: string) => push('error', title, description, 7000),
  info: (title: string, description?: string) => push('info', title, description),
  warning: (title: string, description?: string) => push('warning', title, description),
};
