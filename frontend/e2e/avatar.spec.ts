import { test, expect } from '@playwright/test';

/*
 * Foto de perfil, do arquivo escolhido até o rosto na tela.
 *
 * Vive no E2E, e não no vitest, por um motivo concreto: metade do caminho é API
 * de navegador que o jsdom não tem. `reduzirImagem` (`lib/avatar.ts`) usa
 * `createImageBitmap` e `canvas.toBlob` para reduzir a foto a 256×256 ANTES de
 * subir — é o que dispensa uma biblioteca de imagem no backend e o que impede a
 * foto de 4 MB da câmera de sair do aparelho. Um teste de unidade teria de
 * simular as duas, e passaria a afirmar que os mocks funcionam.
 *
 * O que este arquivo prova, em ordem:
 *   1. escolher um arquivo troca o círculo de inicial por uma `<img>` de verdade;
 *   2. a URL carrega o token de cache (`?v=`), que é o que faz a troca aparecer
 *      mesmo com `Cache-Control: immutable`;
 *   3. a foto acompanha a pessoa para fora do perfil (a barra lateral);
 *   4. remover devolve a inicial.
 */
const API = 'http://localhost:8000/api/v1';

// PNG 1×1 de verdade. Precisa ser decodificável: `createImageBitmap` recusa
// bytes inventados, e o backend confere os magic bytes de qualquer forma.
const PNG_1x1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

test('a foto de perfil sobe, aparece e sai', async ({ browser }) => {
  test.setTimeout(90_000);
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `foto${ts}@e2e.com`;
  const context = await browser.newContext();
  await context.request.post(`${API}/auth/register`, {
    data: { name: 'Fabiana Foto', email, password: 'senha123' },
  });
  await context.request.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await context.request.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });

  const page = await context.newPage();
  await page.goto('/me/settings');
  await expect(page.getByRole('heading', { name: /Suas configurações|Configurações/ })).toBeVisible();

  // Antes: nenhuma imagem de perfil, só a inicial.
  await expect(page.getByRole('img', { name: /Foto de/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Adicionar foto' })).toBeVisible();

  // O input é `hidden` e acionado por `ref` — `setInputFiles` alcança mesmo assim.
  await page.locator('input[type="file"]').setInputFiles({
    name: 'retrato.png',
    mimeType: 'image/png',
    buffer: PNG_1x1,
  });

  const foto = page.getByRole('img', { name: 'Foto de Fabiana Foto' }).first();
  await expect(foto).toBeVisible({ timeout: 15_000 });

  // O `?v=` é o que faz a URL mudar quando a foto muda; sem ele, a resposta
  // `immutable` deixaria a imagem antiga no cache por um ano.
  const src = await foto.getAttribute('src');
  expect(src, `src recebido: ${src}`).toMatch(/\/auth\/users\/\d+\/avatar\?v=[0-9a-f]{8}$/);

  // E a imagem realmente carrega (não é um `src` quebrado apontando para 404).
  await expect
    .poll(() => foto.evaluate((el: HTMLImageElement) => el.naturalWidth))
    .toBeGreaterThan(0);

  // A foto acompanha a pessoa para fora do perfil: a barra lateral lê do mesmo
  // `avatar_version` da store.
  await expect(page.getByRole('img', { name: 'Foto de Fabiana Foto' })).toHaveCount(2);

  await page.getByRole('button', { name: 'Remover' }).click();
  await expect(page.getByRole('img', { name: /Foto de/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Adicionar foto' })).toBeVisible();

  await context.close();
});
