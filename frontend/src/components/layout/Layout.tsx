import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { OnboardingModal } from './OnboardingModal';
import { useWorkspaceEvents } from '@/hooks/use-workspace-events';

interface LayoutProps {
  children: ReactNode;
  title: string;
  subtitle?: string;
}

export function Layout({ children, title, subtitle }: LayoutProps) {
  // Tempo real: WebSocket do workspace atual invalida queries em mutações remotas
  useWorkspaceEvents();

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="container mx-auto p-8 max-w-6xl space-y-8 animate-in fade-in duration-500">
          <header className="flex flex-col gap-1 py-4">
            <h1 className="text-3xl font-bold tracking-tight text-foreground">
              {title}
            </h1>
            {subtitle && <p className="text-muted-foreground font-medium">{subtitle}</p>}
          </header>
          {children}
        </div>
      </main>
      <OnboardingModal />
    </div>
  );
}
