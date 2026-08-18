import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';
import { ScopeSwitcher } from './ScopeSwitcher';
import { OnboardingModal } from './OnboardingModal';
import { NewTransactionDialog } from '@/components/dashboard/NewTransactionDialog';
import { TransactionDetailHost } from '@/components/dashboard/TransactionDetailHost';
import { NotificationCenter } from '@/components/notifications/NotificationCenter';
import { PendingInvitesModal } from '@/components/notifications/PendingInvitesModal';
import { useWorkspaceEvents } from '@/hooks/use-workspace-events';
import { useNewTxStore } from '@/stores';

/*
 * AppShell — casca persistente das telas autenticadas (docs/frontend-redesign/04).
 * Sidebar no desktop, BottomNav no mobile, conteúdo centralizado (max 1200) e o
 * dialog global de "Nova despesa" (acionável do FAB e de qualquer tela).
 */
export function AppShell({ children }: { children: ReactNode }) {
  useWorkspaceEvents();
  const { open, setOpen } = useNewTxStore();

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        {/*
          Barra superior. À direita, a central de avisos: o convite passou a
          exigir aceite, e o aviso precisa estar visível de QUALQUER tela — não
          dá para depender de a pessoa abrir Configurações.

          À esquerda, e SÓ no celular, o seletor de escopo. No desktop ele já
          mora no topo da barra lateral; abaixo de `md` a barra lateral não
          existe, e esta faixa era uma tira de 40px com um sino solitário —
          enquanto a pergunta "estou no meu ou no espaço compartilhado?" não
          tinha resposta em lugar nenhum da tela, e trocar de espaço era
          simplesmente impossível.
        */}
        <div className="sticky top-0 z-30 flex items-center justify-between gap-2 border-b border-border/40 bg-background/80 px-2 py-2 backdrop-blur-sm sm:px-6 md:justify-end md:px-8">
          <ScopeSwitcher className="md:hidden" />
          <NotificationCenter />
        </div>
        {/* O `pb` reserva o espaço da barra inferior fixa MAIS a área segura do
            aparelho — sem a segunda parcela, no iPhone o último item da lista
            ficava atrás do indicador de home e não dava para tocá-lo. */}
        <main className="mx-auto w-full max-w-[1200px] flex-1 space-y-6 px-4 py-6 pb-[calc(6rem+env(safe-area-inset-bottom))] animate-in fade-in duration-300 sm:px-6 md:px-8 md:py-8 md:pb-8">
          {children}
        </main>
      </div>
      <BottomNav />
      <OnboardingModal />
      {/* Depois do onboarding (que termina em reload), o convite pendente é a
          primeira coisa a resolver — no sino ele passava batido. */}
      <PendingInvitesModal />
      <NewTransactionDialog open={open} onOpenChange={setOpen} />
      <TransactionDetailHost />
    </div>
  );
}
