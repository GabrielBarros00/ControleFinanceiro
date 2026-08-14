import type { ReactNode } from 'react';

/*
 * AuthShell — layout dividido das telas de auth (docs/frontend-redesign/07 §6):
 * painel de marca à esquerda (gradiente + proposta) e o formulário à direita.
 * No mobile some o painel e mostra só o formulário.
 */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen w-full md:grid md:grid-cols-[1.1fr_1fr] lg:grid-cols-[1.25fr_1fr]">
      <div className="relative hidden overflow-hidden bg-linear-to-br from-brand to-brand-hover p-12 text-primary-foreground md:flex md:flex-col md:justify-between">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <img src="/sidebar_icon.png" alt="" aria-hidden="true" className="h-9 w-9 rounded-lg" />
          Controle Financeiro
        </div>
        <div className="max-w-sm space-y-3">
          <h2 className="text-3xl font-semibold leading-tight">Suas finanças, com clareza.</h2>
          <p className="text-primary-foreground/80">
            Acompanhe gastos, divida contas e controle faturas — tudo em um lugar, calmo e no ponto.
          </p>
        </div>
        <p className="text-sm text-primary-foreground/60">Controle financeiro pessoal e compartilhado</p>
      </div>

      <div className="flex min-h-screen items-center justify-center bg-background p-4 md:min-h-0">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </div>
  );
}
