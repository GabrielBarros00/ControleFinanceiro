import { test, expect } from '@playwright/test';

/**
 * Sessão expirada numa rota de workspace: redireciona, não entra em laço.
 *
 * O relato do dono: abrir o site com a sessão vencida enchia o log do Compose
 * com `POST /auth/refresh 401` e `GET /auth/me 401` alternados, dezenas por
 * segundo, e a tela ficava presa no carregamento.
 *
 * Eram dois defeitos encadeados. O motor: `queryClient.clear()` no interceptor
 * de 401 removia a própria query `auth-me`, e remover uma query com observador
 * montado faz o react-query refazê-la na hora — `/auth/me` → 401 → `/refresh`
 * → 401 → clear() → `/auth/me` … O agravante: o guard de rota tratava
 * "requisição em voo" como "carregando", e como sempre havia uma em voo, ele
 * nunca concluía que a sessão estava morta e nunca redirecionava.
 *
 * Este teste roda contra o STACK REAL (Compose, porta 8890) porque foi lá que o
 * defeito apareceu — o unitário de `use-auth` cobre a mecânica; aqui se mede o
 * comportamento de ponta a ponta, inclusive o nginx.
 */
test('sessão expirada em rota de workspace redireciona para /login sem spam', async ({ page }) => {
  let chamadas = 0;
  page.on('request', (req) => {
    if (/\/api\/v1\/auth\/(me|refresh)/.test(req.url())) chamadas += 1;
  });

  // Cookie inválido = exatamente o estado do navegador do usuário
  await page.context().addCookies([
    { name: 'access_token', value: 'expirado', domain: 'localhost', path: '/' },
    { name: 'refresh_token', value: 'expirado', domain: 'localhost', path: '/' },
  ]);

  await page.goto('/w/2');

  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });

  // O que caracteriza o laço não é o total, é ele NÃO PARAR de crescer.
  const aposRedirecionar = chamadas;
  await page.waitForTimeout(3_000);
  expect(chamadas - aposRedirecionar).toBeLessThanOrEqual(2);
  expect(chamadas).toBeLessThan(10);
});
