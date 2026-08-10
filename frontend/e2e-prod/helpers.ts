import { expect, type APIRequestContext, type BrowserContext } from '@playwright/test';

// O backend limita auth por IP+rota (`RATE_LIMIT_AUTH_PER_MINUTE`); a suíte
// inteira roda em segundos e estoura o limite — e o `smoke_prod.py`, que no CI
// roda logo antes, TERMINA esgotando de propósito a janela de `/auth/login`.
// Retry em 429 espera a janela liberar em vez de desligar o rate limit (mantém
// o ambiente igual ao de produção).
export async function postWithRetry(request: APIRequestContext, url: string, data: unknown) {
  for (let attempt = 0; attempt < 8; attempt++) {
    const res = await request.post(url, { data });
    if (res.status() !== 429) return res;
    await new Promise((r) => setTimeout(r, 10_000));
  }
  throw new Error(`429 persistente em ${url}`);
}

export async function registerAndLogin(
  context: BrowserContext,
  user: { name: string; email: string; password: string },
) {
  const reg = await postWithRetry(context.request, '/api/v1/auth/register', user);
  expect(reg.ok(), `register ${user.email}: ${reg.status()}`).toBeTruthy();
  const login = await postWithRetry(context.request, '/api/v1/auth/login', {
    email: user.email,
    password: user.password,
  });
  expect(login.ok(), `login ${user.email}: ${login.status()}`).toBeTruthy();
}

export async function defaultWorkspace(context: BrowserContext) {
  const res = await context.request.get('/api/v1/workspaces/');
  expect(res.ok()).toBeTruthy();
  const [ws] = await res.json();
  await context.request.post('/api/v1/auth/onboarding', {
    data: { workspace_id: ws.id, salary: 5000 },
  });
  return ws;
}
