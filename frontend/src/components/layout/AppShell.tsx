import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';
import { OnboardingModal } from './OnboardingModal';
import { NewTransactionDialog } from '@/components/dashboard/NewTransactionDialog';
import { TransactionDetailHost } from '@/components/dashboard/TransactionDetailHost';
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
        <main className="mx-auto w-full max-w-[1200px] flex-1 space-y-6 px-4 py-6 pb-24 animate-in fade-in duration-300 sm:px-6 md:px-8 md:py-8 md:pb-8">
          {children}
        </main>
      </div>
      <BottomNav />
      <OnboardingModal />
      <NewTransactionDialog open={open} onOpenChange={setOpen} />
      <TransactionDetailHost />
    </div>
  );
}
