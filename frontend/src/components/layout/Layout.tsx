import type { ReactNode } from 'react';
import { AppShell } from './AppShell';
import { PageHeader } from './PageHeader';

interface LayoutProps {
  children: ReactNode;
  /** Se informado, renderiza um PageHeader padrão. Telas com header próprio
   *  (período/ação) devem omitir e renderizar o próprio <PageHeader>. */
  title?: string;
  subtitle?: string;
}

export function Layout({ children, title, subtitle }: LayoutProps) {
  return (
    <AppShell>
      {title && <PageHeader title={title} subtitle={subtitle} />}
      {children}
    </AppShell>
  );
}
