import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Home } from './pages/Home';
import { Layout } from './components/layout/Layout';
import { useAuth } from './hooks/use-auth';
import { useTheme } from './hooks/use-theme';
import { useAuthStore, useUIStore } from './stores';
import { Toaster } from './components/ui/toaster';
import { ConfirmProvider } from './components/ui/confirm';

// Code-splitting por rota: o dashboard carrega no bundle inicial; o resto
// (em especial o recharts dos relatórios) só quando a rota é visitada
const CreditCardList = React.lazy(() => import('./components/credit-cards/CreditCardList').then(m => ({ default: m.CreditCardList })));
const StatementView = React.lazy(() => import('./components/credit-cards/StatementView').then(m => ({ default: m.StatementView })));
const AmortizationTable = React.lazy(() => import('./components/financing/AmortizationTable').then(m => ({ default: m.AmortizationTable })));
const ReportsPage = React.lazy(() => import('./pages/Reports/ReportsPage').then(m => ({ default: m.ReportsPage })));
const SettingsPage = React.lazy(() => import('./pages/Settings/SettingsPage').then(m => ({ default: m.SettingsPage })));
const RecurringTransactionsPage = React.lazy(() => import('./pages/RecurringTransactionsPage').then(m => ({ default: m.RecurringTransactionsPage })));
const DebtsPage = React.lazy(() => import('./pages/DebtsPage').then(m => ({ default: m.DebtsPage })));
const EndividamentoPage = React.lazy(() => import('./pages/EndividamentoPage').then(m => ({ default: m.EndividamentoPage })));
const TransactionsPage = React.lazy(() => import('./pages/TransactionsPage').then(m => ({ default: m.TransactionsPage })));
const ImportPage = React.lazy(() => import('./pages/ImportPage').then(m => ({ default: m.ImportPage })));
const IncomePage = React.lazy(() => import('./pages/IncomePage').then(m => ({ default: m.IncomePage })));
const LoginPage = React.lazy(() => import('./pages/Auth/LoginPage').then(m => ({ default: m.LoginPage })));
const RegisterPage = React.lazy(() => import('./pages/Auth/RegisterPage').then(m => ({ default: m.RegisterPage })));
const ForgotPasswordPage = React.lazy(() => import('./pages/Auth/ForgotPasswordPage').then(m => ({ default: m.ForgotPasswordPage })));
const ResetPasswordPage = React.lazy(() => import('./pages/Auth/ResetPasswordPage').then(m => ({ default: m.ResetPasswordPage })));
const InviteAcceptPage = React.lazy(() => import('./pages/InviteAcceptPage').then(m => ({ default: m.InviteAcceptPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Sem defaults, `staleTime: 0` fazia toda invalidação do WebSocket
      // disparar refetch imediato de TODAS as famílias afetadas — e a tabela de
      // ws-events chega a 12 famílias por evento de transação. 30s absorvem a
      // rajada sem deixar dado velho na tela (o WS continua invalidando).
      staleTime: 30_000,
      // 4xx não melhora com repetição: só vale insistir em falha de rede/5xx.
      retry: (failureCount, error) => {
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

function RouteFallback() {
  return (
    <div className="min-h-[50vh] flex items-center justify-center">
      <div className="h-10 w-10 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
    </div>
  );
}

interface ProtectedRouteProps {
  children: React.ReactNode;
}

const ProtectedRoute = ({ children }: ProtectedRouteProps) => {
  const { isAuthenticated, isLoading } = useAuthStore();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="h-12 w-12 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
          <p className="text-muted-foreground text-sm font-medium animate-pulse">Carregando sua sessão...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    // Guarda a rota original COMPLETA (ex: /transactions?month=2026-05) para
    // voltar após o login. Só o pathname perdia a query string e o hash.
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/login" replace state={{ from }} />;
  }
  return <>{children}</>;
};

function CardsPage() {
  const [selectedCardId, setSelectedCardId] = React.useState<number | null>(null);
  const { currentWorkspaceId } = useUIStore();

  // Cartão selecionado não sobrevive à troca de workspace
  React.useEffect(() => {
    setSelectedCardId(null);
  }, [currentWorkspaceId]);

  return (
    <div className="space-y-12">
      <CreditCardList selectedCardId={selectedCardId} onSelectCard={setSelectedCardId} />
      <div className="space-y-6">
        <h3 className="text-xl font-semibold text-foreground">Faturas do Cartão</h3>
        <StatementView cardId={selectedCardId} />
      </div>
    </div>
  );
}

function AppContent() {
  // Initialize auth and theme
  useAuth();
  useTheme();

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-background text-foreground font-sans selection:bg-primary/30">
        <ConfirmProvider>
        <React.Suspense fallback={<RouteFallback />}>
        <Routes>
          {/* Public Routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          
          {/* Protected Routes */}
          <Route path="/" element={
            <ProtectedRoute>
              <Layout>
                <Home />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/transactions" element={
            <ProtectedRoute>
              <Layout>
                <TransactionsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/income" element={
            <ProtectedRoute>
              <Layout>
                <IncomePage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/cards" element={
            <ProtectedRoute>
              <Layout title="Cartões de Crédito" subtitle="Gerencie seus limites e faturas em um só lugar.">
                <CardsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/invite/:token" element={
            <ProtectedRoute>
              <InviteAcceptPage />
            </ProtectedRoute>
          } />

          <Route path="/financing" element={
            <ProtectedRoute>
              <Layout title="Financiamentos" subtitle="Amortizações, simulações e quitações antecipadas.">
                <AmortizationTable />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/reports" element={
            <ProtectedRoute>
              {/* Sem title: a ReportsPage tem PageHeader próprio (carrega o
                  seletor de período), senão o cabeçalho sai duplicado */}
              <Layout>
                <ReportsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/settings" element={
            <ProtectedRoute>
              <Layout title="Configurações" subtitle="Gerencie seu perfil e preferências do workspace.">
                <SettingsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/recurring" element={
            <ProtectedRoute>
              <Layout title="Recorrência" subtitle="Gerencie seus gastos fixos e automáticos.">
                <RecurringTransactionsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/debts" element={
            <ProtectedRoute>
              <Layout>
                <DebtsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/liabilities" element={
            <ProtectedRoute>
              <Layout>
                <EndividamentoPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/import" element={
            <ProtectedRoute>
              <Layout title="Importar" subtitle="Carregue transações via arquivo CSV.">
                <ImportPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </React.Suspense>
        </ConfirmProvider>
        <Toaster />
      </div>
    </BrowserRouter>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}

export default App;
