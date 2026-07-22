import { create } from 'zustand';

export type ToastVariant = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
  duration: number; // ms; <= 0 nunca fecha sozinho
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
  success: (title: string, description?: string) => push('success', title, description),
  // Erros ficam um pouco mais na tela
  error: (title: string, description?: string) => push('error', title, description, 7000),
  info: (title: string, description?: string) => push('info', title, description),
  warning: (title: string, description?: string) => push('warning', title, description),
};
