import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { OverviewPage } from './pages/OverviewPage';
import { WorkspaceGuard } from './components/layout/WorkspaceGuard';
import { useLastWorkspaceId, useWorkspaceId } from './hooks/use-workspace-id';
import { registerQueryClient } from './api/client';
import { Layout } from './components/layout/Layout';
import { useAuth } from './hooks/use-auth';
import { useTheme } from './hooks/use-theme';
import { useAuthStore } from './stores';
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
const WorkspaceHome = React.lazy(() => import('./pages/Home').then(m => ({ default: m.Home })));
const CommitmentsPage = React.lazy(() => import('./pages/CommitmentsPage').then(m => ({ default: m.CommitmentsPage })));

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

// O interceptor de 401 precisa descartar o cache quando a sessão morre
registerQueryClient(queryClient);

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
  const currentWorkspaceId = useWorkspaceId();

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

/**
 * Rotas ANTIGAS (`/transactions`, `/income`, …) caem no último workspace
 * visitado; sem nenhum, na visão global. É o que mantém link velho e favorito
 * funcionando depois de o workspace ter ido para a URL (ADR 0020).
 */
function RedirectParaWorkspace({ sub = '' }: { sub?: string }) {
  const ultimo = useLastWorkspaceId();
  return <Navigate to={ultimo ? `/w/${ultimo}${sub}` : '/overview'} replace />;
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
          
          {/* ---- PESSOAL: sem workspace no caminho (ADR 0020) ---- */}
          <Route path="/overview" element={
            <ProtectedRoute><Layout><OverviewPage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/commitments" element={
            <ProtectedRoute>
              <Layout title="Compromissos financeiros" subtitle="Faturas e financiamentos a vencer — seus, em todos os workspaces.">
                <CommitmentsPage />
              </Layout>
            </ProtectedRoute>
          } />

          <Route path="/invite/:token" element={
            <ProtectedRoute><InviteAcceptPage /></ProtectedRoute>
          } />

          {/* ---- WORKSPACE: o id vive na URL ---- */}
          <Route path="/w/:workspaceId" element={
            <ProtectedRoute><Layout><WorkspaceGuard /></Layout></ProtectedRoute>
          }>
            <Route index element={<WorkspaceHome />} />
            <Route path="transactions" element={<TransactionsPage />} />
            <Route path="income" element={<IncomePage />} />
            <Route path="cards" element={<CardsPage />} />
            <Route path="financing" element={<AmortizationTable />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="recurring" element={<RecurringTransactionsPage />} />
            <Route path="debts" element={<DebtsPage />} />
            <Route path="liabilities" element={<EndividamentoPage />} />
            <Route path="import" element={<ImportPage />} />
          </Route>

          {/* ---- Rotas antigas: redirecionam para o último workspace ---- */}
          {/* `/` é o Início GLOBAL (ADR 0020) — não o painel de um workspace.
              Só as rotas ANTIGAS, que eram de workspace, caem na última casa. */}
          <Route path="/" element={<Navigate to="/overview" replace />} />
          {[
            'transactions', 'income', 'cards', 'financing', 'reports',
            'settings', 'recurring', 'debts', 'liabilities', 'import',
          ].map((rota) => (
            <Route
              key={rota}
              path={`/${rota}`}
              element={<ProtectedRoute><RedirectParaWorkspace sub={`/${rota}`} /></ProtectedRoute>}
            />
          ))}

          <Route path="*" element={<Navigate to="/overview" replace />} />
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
