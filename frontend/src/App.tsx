import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { OverviewPage } from './pages/OverviewPage';
import { WorkspaceGuard } from './components/layout/WorkspaceGuard';
import { useLastWorkspaceId } from './hooks/use-workspace-id';
import { registerQueryClient } from './api/client';
import { Layout } from './components/layout/Layout';
import { PageHeader } from './components/layout/PageHeader';
import { useAuth } from './hooks/use-auth';
import { useIsPlatformAdmin } from './hooks/use-admin';
import { useTheme } from './hooks/use-theme';
import { Toaster } from './components/ui/toaster';
import { ConfirmProvider } from './components/ui/confirm';

// Code-splitting por rota: o dashboard carrega no bundle inicial; o resto
// (em especial o recharts dos relatórios) só quando a rota é visitada
const CreditCardList = React.lazy(() => import('./components/credit-cards/CreditCardList').then(m => ({ default: m.CreditCardList })));
const StatementView = React.lazy(() => import('./components/credit-cards/StatementView').then(m => ({ default: m.StatementView })));
const AmortizationTable = React.lazy(() => import('./components/financing/AmortizationTable').then(m => ({ default: m.AmortizationTable })));
const ReportsPage = React.lazy(() => import('./pages/Reports/ReportsPage').then(m => ({ default: m.ReportsPage })));
const SettingsPage = React.lazy(() => import('./pages/Settings/SettingsPage').then(m => ({ default: m.SettingsPage })));
const MyReportsPage = React.lazy(() => import('./pages/MyReportsPage').then(m => ({ default: m.MyReportsPage })));
const GlobalLedgerPage = React.lazy(() => import('./pages/GlobalLedgerPage').then(m => ({ default: m.GlobalLedgerPage })));
const MySettlementsPage = React.lazy(() => import('./pages/MySettlementsPage').then(m => ({ default: m.MySettlementsPage })));
const PersonalSettingsPage = React.lazy(() => import('./pages/Settings/SettingsPage').then(m => ({ default: m.PersonalSettingsPage })));
const RecurringTransactionsPage = React.lazy(() => import('./pages/RecurringTransactionsPage').then(m => ({ default: m.RecurringTransactionsPage })));
const DebtsPage = React.lazy(() => import('./pages/DebtsPage').then(m => ({ default: m.DebtsPage })));
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
const PayablesPage = React.lazy(() => import('./pages/PayablesPage').then(m => ({ default: m.PayablesPage })));
const AccountsPage = React.lazy(() => import('./pages/AccountsPage'));
const WorkspacePayablesPage = React.lazy(() => import('./pages/WorkspacePayablesPage').then(m => ({ default: m.WorkspacePayablesPage })));
// Área administrativa: lazy como as demais. É a rota que menos gente visita —
// não faz sentido pagar o custo dela no bundle inicial de todo mundo.
const AdminPage = React.lazy(() => import('./pages/Admin/AdminPage').then(m => ({ default: m.AdminPage })));

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

/**
 * Guarda de rota autenticada.
 *
 * O estado vem do `useAuth()` (react-query) e NÃO do espelho em Zustand. A
 * diferença é a corrida que deixava o cadastro intermitente no E2E: depois do
 * auto-login, `invalidateQueries(['auth-me'])` marca a query como suja e dispara
 * um refetch — mas o store só é atualizado quando esse refetch RESOLVE. Entre
 * uma coisa e outra ele fica em `isLoading: false` + `isAuthenticated: false`,
 * um estado que significa "sessão morta" e mandava direto para `/login`,
 * enquanto a requisição de sessão ainda estava em voo e voltaria 200.
 *
 * `isFetching` fecha a janela: enquanto há requisição de sessão pendente, o
 * guard espera em vez de concluir que não há sessão.
 */
const ProtectedRoute = ({ children }: ProtectedRouteProps) => {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-dvh flex items-center justify-center bg-background">
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

/**
 * Guarda da área administrativa (ADR 0026).
 *
 * Conveniência de interface, não segurança: quem barra de verdade é
 * `require_platform_role` no servidor, e as rotas de `/admin` respondem 404 para
 * quem não tem papel. Isto evita que um usuário comum que digite `/admin` veja
 * uma tela quebrada de requisições falhando — manda de volta para a visão geral.
 */
const AdminRoute = ({ children }: ProtectedRouteProps) => {
  const ehAdmin = useIsPlatformAdmin();
  if (!ehAdmin) return <Navigate to="/overview" replace />;
  return <>{children}</>;
};

function CardsPage() {
  // Cartão é PESSOAL (ADR 0021): não é mais zerado ao trocar de workspace,
  // porque não pertence a nenhum.
  const [selectedCardId, setSelectedCardId] = React.useState<number | null>(null);

  return (
    <div className="space-y-12">
      <PageHeader
        title="Cartões"
        subtitle="Seus cartões e faturas. Só você os vê — em qualquer espaço."
      />
      <CreditCardList selectedCardId={selectedCardId} onSelectCard={setSelectedCardId} />
      <div className="space-y-6">
        <h2 className="text-xl font-semibold text-foreground">Faturas do cartão</h2>
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
      <div className="min-h-dvh bg-background text-foreground font-sans selection:bg-primary/30">
        <ConfirmProvider>
        <React.Suspense fallback={<RouteFallback />}>
        <Routes>
          {/* Public Routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          
          {/* ---- PESSOAL: sem workspace no caminho (ADR 0020 + 0021) ----
              Renda, cartões, contas e financiamentos vieram para cá na Onda 5:
              são da PESSOA e a acompanham em todos os workspaces. */}
          <Route path="/overview" element={
            <ProtectedRoute><Layout><OverviewPage /></Layout></ProtectedRoute>
          } />
          {/* Contas a pagar (ADR 0029): o que ainda não saiu do caixa. Eixo
              diferente de `/me/commitments`, que é fatura e financiamento — a
              instituição, não a conta do mês. */}
          <Route path="/me/accounts" element={
            <ProtectedRoute><Layout><AccountsPage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/payables" element={
            <ProtectedRoute><Layout><PayablesPage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/income" element={
            <ProtectedRoute><Layout><IncomePage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/cards" element={
            <ProtectedRoute><Layout><CardsPage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/financing" element={
            <ProtectedRoute>
              <Layout title="Financiamentos" subtitle="Seus contratos e o cronograma de amortização.">
                <AmortizationTable />
              </Layout>
            </ProtectedRoute>
          } />
          <Route path="/me/reports" element={
            <ProtectedRoute><Layout><MyReportsPage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/ledger" element={
            <ProtectedRoute><Layout><GlobalLedgerPage /></Layout></ProtectedRoute>
          } />
          <Route path="/me/commitments" element={
            <ProtectedRoute>
              <Layout title="Compromissos financeiros" subtitle="Faturas e financiamentos a vencer — seus, em todos os seus espaços.">
                <CommitmentsPage />
              </Layout>
            </ProtectedRoute>
          } />
          {/* Acertos entre pessoas somando as casas (ADR 0027). `/w/:id/debts`
              continua existindo e é outra pergunta: "como está ESTE espaço",
              inclusive as dívidas entre terceiros, que aqui não aparecem. */}
          <Route path="/me/settlements" element={
            <ProtectedRoute><Layout><MySettlementsPage /></Layout></ProtectedRoute>
          } />
          {/* Perfil, senha, contas e tema não pertencem a workspace nenhum e
              mesmo assim só existiam dentro de `/w/:id/settings` — quem ficasse
              sem workspace válido não alcançava a própria senha pela interface. */}
          <Route path="/me/settings" element={
            <ProtectedRoute><Layout><PersonalSettingsPage /></Layout></ProtectedRoute>
          } />

          <Route path="/invite/:token" element={
            <ProtectedRoute><InviteAcceptPage /></ProtectedRoute>
          } />

          {/* ---- PLATAFORMA: quem opera o site (ADR 0026) ----
              Terceiro eixo, ao lado do pessoal e do workspace. Não leva
              `workspace_id` no caminho porque nada aqui pertence a uma casa —
              e nada aqui alcança o dinheiro de ninguém. */}
          <Route path="/admin" element={
            <ProtectedRoute>
              <AdminRoute>
                <Layout
                  title="Administração"
                  subtitle="Pessoas, convites e configuração do site."
                >
                  <AdminPage />
                </Layout>
              </AdminRoute>
            </ProtectedRoute>
          } />

          {/* ---- WORKSPACE: o id vive na URL ---- */}
          <Route path="/w/:workspaceId" element={
            <ProtectedRoute><Layout><WorkspaceGuard /></Layout></ProtectedRoute>
          }>
            <Route index element={<WorkspaceHome />} />
            <Route path="transactions" element={<TransactionsPage />} />
            <Route path="payables" element={<WorkspacePayablesPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="recurring" element={<RecurringTransactionsPage />} />
            <Route path="debts" element={<DebtsPage />} />
            <Route path="import" element={<ImportPage />} />
          </Route>

          {/* ---- Rotas antigas ----
              As que viraram PESSOAIS vão direto para `/me/...`; as que continuam
              sendo do workspace caem na última casa aberta. `/` é o Início
              GLOBAL (ADR 0020), não o painel de um workspace. */}
          <Route path="/" element={<Navigate to="/overview" replace />} />
          {Object.entries({
            income: '/me/income',
            cards: '/me/cards',
            financing: '/me/financing',
            liabilities: '/me/commitments',
          }).map(([antiga, nova]) => (
            <Route key={antiga} path={`/${antiga}`} element={<Navigate to={nova} replace />} />
          ))}
          {/* Também com o prefixo de workspace: quem tinha `/w/1/cards` salvo */}
          {Object.entries({
            'w/:workspaceId/income': '/me/income',
            'w/:workspaceId/cards': '/me/cards',
            'w/:workspaceId/financing': '/me/financing',
            'w/:workspaceId/liabilities': '/me/commitments',
          }).map(([antiga, nova]) => (
            <Route key={antiga} path={`/${antiga}`} element={<Navigate to={nova} replace />} />
          ))}
          {['transactions', 'payables', 'reports', 'settings', 'recurring', 'debts', 'import'].map((rota) => (
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
