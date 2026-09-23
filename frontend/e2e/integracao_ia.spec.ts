import { test, expect } from '@playwright/test';
import { createHash, randomBytes } from 'node:crypto';

/*
 * Integração com agentes de IA (ADR 0035), de ponta a ponta no navegador.
 *
 * O que só o E2E prova: que a TELA de consentimento é alcançada pelo
 * `/oauth/authorize`, mostra quem pede e para onde vai o acesso, e que o
 * "Autorizar" leva o navegador de volta ao agente com um código que vira token
 * — e que "Desconectar" na tela de Integrações corta o acesso na hora.
 *
 * O "agente" aqui é o próprio teste: registra-se por DCR com redirect loopback
 * (como Claude Code/Codex/Gemini CLI) e intercepta a volta ao 127.0.0.1.
 */
const API = 'http://localhost:8000/api/v1';
const ISSUER = 'http://localhost:5173';
const RESOURCE = `${ISSUER}/mcp`;
const REDIRECT = 'http://127.0.0.1:9123/callback';

function pkce() {
  const verificador = randomBytes(48).toString('base64url');
  const desafio = createHash('sha256').update(verificador).digest('base64url');
  return { verificador, desafio };
}

test('agente se conecta pelo consentimento, usa uma tool e é desconectado', async ({ browser }) => {
  test.setTimeout(120_000);
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `agente${ts}@e2e.com`;
  const context = await browser.newContext();
  await context.request.post(`${API}/auth/register`, { data: { name: 'Iara Integra', email, password: 'senha123' } });
  await context.request.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

  // 1) O agente se registra (DCR, cliente público de terminal).
  const registro = await context.request.post(`${API}/oauth/register`, {
    data: {
      client_name: 'Agente E2E', redirect_uris: [REDIRECT], token_endpoint_auth_method: 'none',
      grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'],
    },
  });
  expect(registro.status()).toBe(201);
  const { client_id } = await registro.json();

  // 2) A pessoa é levada ao authorize e cai na tela de consentimento do app.
  const { verificador, desafio } = pkce();
  const page = await context.newPage();
  let volta = '';
  await page.route('http://127.0.0.1:9123/**', async (route) => {
    volta = route.request().url();
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<p>ok</p>' });
  });
  const params = new URLSearchParams({
    response_type: 'code', client_id, redirect_uri: REDIRECT, state: 'st-e2e',
    code_challenge: desafio, code_challenge_method: 'S256',
    scope: 'finance.read transactions.write', resource: RESOURCE,
  });
  await page.goto(`${API}/oauth/authorize?${params}`);
  await expect(page.getByRole('heading', { name: 'Autorizar “Agente E2E”?' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('127.0.0.1')).toBeVisible();
  await expect(page.getByText(/roda no seu computador/)).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /Registrar/ })).toBeChecked();

  // 3) Autorizar devolve o navegador ao agente com código, state e iss.
  await page.getByRole('button', { name: 'Autorizar' }).click();
  await expect.poll(() => volta, { timeout: 15_000 }).toContain('code=');
  const retorno = new URL(volta);
  expect(retorno.searchParams.get('state')).toBe('st-e2e');
  expect(retorno.searchParams.get('iss')).toBe(ISSUER);

  // 4) O código vira token (PKCE) e o token chama uma tool.
  const troca = await context.request.post(`${API}/oauth/token`, {
    form: {
      grant_type: 'authorization_code', code: retorno.searchParams.get('code')!, redirect_uri: REDIRECT,
      client_id, code_verifier: verificador, resource: RESOURCE,
    },
  });
  expect(troca.status()).toBe(200);
  const { access_token } = await troca.json();
  const chamarPerfil = () => context.request.post('http://localhost:8000/mcp', {
    headers: { Authorization: `Bearer ${access_token}`, Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25' },
    data: { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'profile_get', arguments: {} } },
  });
  const perfil = await chamarPerfil();
  expect(perfil.status()).toBe(200);
  expect((await perfil.json()).result.structuredContent.email).toBe(email);

  // 5) A conexão aparece na tela, com a atividade; desconectar corta na hora.
  await page.goto('/me/settings?tab=ai');
  await expect(page.getByRole('heading', { name: /Integrações com IA/ })).toBeVisible();
  await expect(page.getByText('Agente E2E').first()).toBeVisible();
  await expect(page.getByText('Conta conectada')).toBeVisible();
  await page.getByRole('button', { name: /Desconectar/ }).first().click();
  await page.getByRole('dialog').getByRole('button', { name: 'Desconectar' }).click();
  await expect(page.getByText('Nenhum agente conectado')).toBeVisible({ timeout: 15_000 });
  expect((await chamarPerfil()).status()).toBe(401);
  await context.close();
});
