import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';
import { OAuthConsentPage } from '../OAuthConsentPage';

/**
 * Consentimento de agente de IA (ADR 0035). A tela precisa mostrar QUEM pede
 * (e para onde o acesso vai), QUAL conta, O QUE poderá ser feito — e mandar ao
 * servidor exatamente as permissões marcadas.
 */
const API = 'http://localhost:8000/api/v1';

const PEDIDO = {
  client: { name: 'ChatGPT', kind: 'dcr', client_host: 'chatgpt.com', redirect_host: 'chatgpt.com', loopback_only: false },
  account: { name: 'Alice Souza', email: 'alice@example.com' },
  scopes: [
    { scope: 'finance.read', label: 'Ler suas finanças', description: 'Leitura.', required: true },
    { scope: 'transactions.write', label: 'Registrar lançamentos', description: 'Escrita.', required: false },
    { scope: 'accounts.write', label: 'Mexer no saldo das contas', description: 'Contas.', required: false },
  ],
};

const assign = vi.fn();

function abrir(search: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/oauth/consent${search}`]}>
        <OAuthConsentPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  assign.mockReset();
  Object.defineProperty(window, 'location', { value: { ...window.location, assign }, writable: true });
  server.use(http.get(`${API}/oauth/consent`, () => HttpResponse.json(PEDIDO)));
});

describe('OAuthConsentPage', () => {
  it('mostra o aplicativo, o destino e a conta', async () => {
    abrir('?request=abc');
    expect(await screen.findByText('Autorizar “ChatGPT”?')).toBeInTheDocument();
    expect(screen.getByText('chatgpt.com')).toBeInTheDocument();
    expect(screen.getByText(/alice@example.com/)).toBeInTheDocument();
    // A leitura é obrigatória: marcada e travada.
    const leitura = screen.getByRole('checkbox', { name: /Ler suas finanças/ });
    expect(leitura).toBeChecked();
    expect(leitura).toBeDisabled();
  });

  it('aprovar manda só as permissões marcadas e volta ao aplicativo', async () => {
    let corpo: unknown = null;
    server.use(http.post(`${API}/oauth/consent/approve`, async ({ request }) => {
      corpo = await request.json();
      return HttpResponse.json({ redirect_to: 'https://chatgpt.com/cb?code=x&state=y&iss=z' });
    }));
    abrir('?request=abc');
    await screen.findByText('Autorizar “ChatGPT”?');
    fireEvent.click(screen.getByRole('checkbox', { name: /Mexer no saldo/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Autorizar' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://chatgpt.com/cb?code=x&state=y&iss=z'));
    expect(corpo).toEqual({ request: 'abc', scopes: ['finance.read', 'transactions.write'] });
  });

  it('negar também devolve ao aplicativo (com access_denied)', async () => {
    server.use(http.post(`${API}/oauth/consent/deny`, () =>
      HttpResponse.json({ redirect_to: 'https://chatgpt.com/cb?error=access_denied' })));
    abrir('?request=abc');
    await screen.findByText('Autorizar “ChatGPT”?');
    fireEvent.click(screen.getByRole('button', { name: 'Negar' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://chatgpt.com/cb?error=access_denied'));
  });

  it('agente de terminal ganha o aviso de loopback', async () => {
    server.use(http.get(`${API}/oauth/consent`, () =>
      HttpResponse.json({ ...PEDIDO, client: { ...PEDIDO.client, name: 'Claude Code', redirect_host: 'localhost', loopback_only: true } })));
    abrir('?request=abc');
    expect(await screen.findByText(/roda no seu computador/)).toBeInTheDocument();
  });

  it('pedido vencido explica o que fazer', async () => {
    server.use(http.get(`${API}/oauth/consent`, () =>
      HttpResponse.json({ error: { message: 'pedido de autorização inválido ou expirado' } }, { status: 400 })));
    abrir('?request=velho');
    expect(await screen.findByText('Pedido expirado ou inválido')).toBeInTheDocument();
    expect(screen.getByText(/valem 10 minutos/)).toBeInTheDocument();
  });

  it('erro vindo do authorize não chama a API', async () => {
    const chamou = vi.fn();
    server.use(http.get(`${API}/oauth/consent`, () => { chamou(); return HttpResponse.json(PEDIDO); }));
    abrir('?error=invalid_client&error_description=x');
    expect(await screen.findByText('Não foi possível conectar')).toBeInTheDocument();
    expect(screen.getByText(/não foi reconhecido/)).toBeInTheDocument();
    expect(chamou).not.toHaveBeenCalled();
  });
});
