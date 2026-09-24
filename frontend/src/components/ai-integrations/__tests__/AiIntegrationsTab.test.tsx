import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { ConfirmProvider } from '@/components/ui/confirm';
import { AiIntegrationsTab } from '../AiIntegrationsTab';
import { clientGuides, connectionProfile } from '../client-guides';

/**
 * Aba "Integrações com IA" (ADR 0035). O que ela não pode errar: o endereço
 * copiado, os comandos por cliente (com a URL da conta e SEM credencial), o
 * estado de cada conexão e o "Desconectar" que de fato revoga.
 */
const API = 'http://localhost:8000/api/v1';
const MCP_URL = 'https://financas.example.com/mcp';

const ESCOPOS = [
  { scope: 'finance.read', label: 'Ler suas finanças', description: 'Leitura.', required: true },
  { scope: 'transactions.write', label: 'Registrar lançamentos', description: 'Escrita.', required: false },
];

function status(extra: Record<string, unknown> = {}) {
  return {
    enabled: true,
    mcp_url: MCP_URL,
    transport: 'streamable-http',
    authentication: 'oauth2',
    server_name: 'controle-financeiro',
    server_version: '1.0.0',
    environment: 'production',
    account: { name: 'Alice Souza', email: 'alice@example.com', public_id: 'usr_abc' },
    scopes: ESCOPOS,
    connections: [
      {
        grant_id: 7, client_name: 'ChatGPT', client_kind: 'dcr', client_host: 'chatgpt.com',
        redirect_host: 'chatgpt.com', scopes: ['finance.read', 'transactions.write'],
        created_at: '2026-09-20T12:00:00', last_used_at: '2026-09-21T15:30:00', status: 'active',
      },
      {
        grant_id: 8, client_name: 'Claude Code', client_kind: 'cimd', client_host: 'claude.ai',
        redirect_host: 'localhost', scopes: ['finance.read'],
        created_at: '2026-08-01T12:00:00', last_used_at: null, status: 'expired',
      },
    ],
    last_used_at: '2026-09-21T15:30:00',
    ...extra,
  };
}

function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ConfirmProvider>
          <AiIntegrationsTab />
        </ConfirmProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function abrirAba(nome: string) {
  const gatilho = screen.getByRole('tab', { name: nome });
  fireEvent.mouseDown(gatilho);
  fireEvent.click(gatilho);
}

const copiar = vi.fn();

beforeEach(() => {
  copiar.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: copiar }, configurable: true });
  server.use(
    http.get(`${API}/me/ai-integrations`, () => HttpResponse.json(status())),
    http.get(`${API}/me/ai-integrations/activity`, () => HttpResponse.json([
      { id: 1, tool: 'transactions_create', title: 'Registrar despesa', kind: 'write', outcome: 'ok',
        error_code: null, client_name: 'ChatGPT', created_at: '2026-09-21T15:30:00', duration_ms: 12, replayed: false },
      { id: 2, tool: 'transactions_get', title: 'Ver lançamento', kind: 'read', outcome: 'error',
        error_code: 'NOT_FOUND', client_name: 'ChatGPT', created_at: '2026-09-21T15:31:00', duration_ms: 3, replayed: false },
    ])),
  );
});

afterEach(() => vi.useRealTimers());

describe('AiIntegrationsTab', () => {
  it('mostra o status, o endpoint e a conta conectada', async () => {
    renderizar();
    expect(await screen.findByText('Endpoint MCP')).toBeInTheDocument();
    expect(screen.getAllByText(MCP_URL).length).toBeGreaterThan(0);
    expect(screen.getByText('Disponível')).toBeInTheDocument();
    expect(screen.getByText('OAuth 2.1 com PKCE')).toBeInTheDocument();
    expect(screen.getByText(/Alice Souza · alice@example.com/)).toBeInTheDocument();
  });

  it('copia a URL e mostra "Copiado"', async () => {
    renderizar();
    await screen.findByText('Endpoint MCP');
    fireEvent.click(screen.getByRole('button', { name: /Copiar URL: Endereço/ }));
    await waitFor(() => expect(copiar).toHaveBeenCalledWith(MCP_URL));
    expect(await screen.findByText('Copiado')).toBeInTheDocument();
  });

  it('gera os comandos de cada cliente com a URL da conta', async () => {
    renderizar();
    await screen.findByText('Endpoint MCP');
    abrirAba('Codex');
    expect(screen.getByText(`codex mcp add controle-financeiro --url ${MCP_URL}`)).toBeInTheDocument();
    expect(screen.getByText('codex mcp login controle-financeiro')).toBeInTheDocument();
    abrirAba('Claude Code');
    expect(screen.getByText(`claude mcp add --transport http controle-financeiro --scope user ${MCP_URL}`)).toBeInTheDocument();
    abrirAba('Gemini CLI');
    expect(screen.getByText(`gemini mcp add --transport http --scope user controle-financeiro ${MCP_URL}`)).toBeInTheDocument();
    expect(screen.getAllByText(/verificado em 23\/09\/2026/).length).toBeGreaterThan(0);
  });

  it('mostra cada conexão com o estado dela e a atividade recente', async () => {
    renderizar();
    await screen.findByText('Endpoint MCP');
    expect(screen.getByText('Ativa')).toBeInTheDocument();
    expect(screen.getByText('Autorização expirada')).toBeInTheDocument();
    expect(screen.getAllByText('Registrar lançamentos').length).toBeGreaterThan(0);
    expect(await screen.findByText('Registrar despesa')).toBeInTheDocument();
    expect(screen.getByText('NOT_FOUND')).toBeInTheDocument();
  });

  it('desconectar pede confirmação e revoga', async () => {
    const revogou = vi.fn();
    server.use(http.delete(`${API}/me/ai-integrations/connections/7`, () => {
      revogou();
      return HttpResponse.json({ status: 'ok' });
    }));
    renderizar();
    await screen.findByText('Endpoint MCP');
    const botoes = screen.getAllByRole('button', { name: /Desconectar/ });
    fireEvent.click(botoes[0]);
    const dialogo = await screen.findByRole('dialog');
    expect(within(dialogo).getByText(/Desconectar ChatGPT\?/)).toBeInTheDocument();
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Desconectar' }));
    await waitFor(() => expect(revogou).toHaveBeenCalledTimes(1));
  });

  it('sem conexões mostra o estado vazio', async () => {
    server.use(http.get(`${API}/me/ai-integrations`, () => HttpResponse.json(status({ connections: [] }))));
    renderizar();
    expect(await screen.findByText('Nenhum agente conectado')).toBeInTheDocument();
  });

  it('integração desligada pelo admin', async () => {
    server.use(http.get(`${API}/me/ai-integrations`, () => HttpResponse.json(status({ enabled: false }))));
    renderizar();
    expect(await screen.findByText('Integração desativada')).toBeInTheDocument();
  });

  it('erro de carga oferece tentar de novo', async () => {
    server.use(http.get(`${API}/me/ai-integrations`, () => HttpResponse.json({ error: { message: 'x' } }, { status: 500 })));
    renderizar();
    expect(await screen.findByText('Não foi possível carregar as integrações')).toBeInTheDocument();
  });
});

describe('client-guides', () => {
  const guias = clientGuides(MCP_URL);

  it('nenhum comando carrega credencial nem pula confirmação', () => {
    const comandos = guias.flatMap((g) => g.commands.map((c) => c.code)).join(' ');
    expect(comandos).not.toMatch(/Bearer|cfm_at_|--header|--trust|token=/i);
    // O único lugar em que --trust aparece é o aviso para NÃO usá-lo.
    const gemini = guias.find((g) => g.id === 'gemini-cli')!;
    expect(gemini.steps.join(' ')).toMatch(/não use a opção --trust/);
  });

  it('todo guia tem link oficial https e passos', () => {
    for (const g of guias) {
      expect(g.docsUrl).toMatch(/^https:\/\//);
      expect(g.steps.length).toBeGreaterThan(0);
    }
  });

  it('o JSON do Antigravity usa serverUrl', () => {
    const antigravity = guias.find((g) => g.id === 'antigravity')!;
    expect(JSON.parse(antigravity.commands[0].code)).toEqual({ mcpServers: { 'controle-financeiro': { serverUrl: MCP_URL } } });
  });

  it('o perfil de conexão não tem segredo e aponta os metadados', () => {
    const perfil = JSON.parse(connectionProfile({ mcpUrl: MCP_URL, serverName: 's', serverVersion: '1', scopes: ['finance.read'] }));
    expect(perfil.authentication.protected_resource_metadata).toBe('https://financas.example.com/.well-known/oauth-protected-resource/mcp');
    expect(JSON.stringify(perfil)).not.toMatch(/secret|token|password/i);
  });
});
