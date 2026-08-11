import { request } from '@playwright/test';

/**
 * Abre o cadastro para a suíte, usando a própria API de administração.
 *
 * Contra o stack de produção o cadastro nasce POR CONVITE (ADR 0026), e os
 * specs daqui criam usuários pela API como atalho — eles testam nginx,
 * WebSocket e sessão, não o portão de entrada. Quem testa o portão é
 * `scripts/smoke_prod.py`, que roda antes no CI e verifica exatamente o
 * contrário: que sem convite ninguém entra.
 *
 * Fazer isso PELA API DE ADMIN, e não mexendo no banco, tem um efeito colateral
 * bom: se a autenticação de plataforma, o PUT de configuração ou a janela de
 * bootstrap quebrarem, a suíte inteira falha aqui, com mensagem clara — em vez
 * de sete specs falhando em cascata com "403 no register".
 */
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8890';
const ADMIN_EMAIL = process.env.SMOKE_SUPERADMIN_EMAIL || 'smoke-admin@example.com';
const ADMIN_SENHA = 'senha123';

/**
 * O `smoke_prod.py` TERMINA esgotando de propósito a janela de `/auth/login`
 * para provar que o rate limit está de pé — e no CI ele roda imediatamente
 * antes deste setup. Sem esperar a janela abrir, o primeiro login daqui levaria
 * 429 e a suíte inteira falharia por um motivo que não tem nada a ver com ela.
 * É a mesma razão do `postWithRetry` em `helpers.ts`.
 */
async function postComEspera(
  api: Awaited<ReturnType<typeof request.newContext>>,
  url: string,
  data: unknown,
) {
  for (let tentativa = 0; tentativa < 8; tentativa++) {
    const res = await api.post(url, { data });
    if (res.status() !== 429) return res;
    await new Promise((r) => setTimeout(r, 10_000));
  }
  throw new Error(`429 persistente em ${url} — o rate limit não liberou a janela`);
}

async function globalSetup() {
  const api = await request.newContext({ baseURL: BASE });

  try {
    // Tenta criar a conta pela janela de bootstrap. O resultado é IGNORADO de
    // propósito, e quem decide é o login logo abaixo:
    //
    // - 200 → a suíte rodou sozinha e a janela criou a conta agora;
    // - 403 → o `smoke_prod.py` já a criou (no CI ele roda antes). O portão de
    //   cadastro corre ANTES da checagem de e-mail duplicado, então "já existe"
    //   e "não existe" respondem o mesmo 403 — é a propriedade anti-enumeração
    //   do ADR 0026, e é por isso que este status não distingue nada.
    //
    // Tratar 403 como falha, como esta função fazia, quebrava a suíte
    // exatamente quando o smoke tinha passado.
    const reg = await postComEspera(api, '/api/v1/auth/register', {
      name: 'Admin E2E', email: ADMIN_EMAIL, password: ADMIN_SENHA,
    });

    const login = await postComEspera(api, '/api/v1/auth/login', {
      email: ADMIN_EMAIL, password: ADMIN_SENHA,
    });
    if (!login.ok()) {
      throw new Error(
        `não foi possível entrar como superadministrador `
        + `(register=${reg.status()}, login=${login.status()}): ${await login.text()}\n`
        + `Confira SUPERADMIN_EMAIL=${ADMIN_EMAIL} no .env do stack — `
        + `e que a senha da conta seja "${ADMIN_SENHA}".`,
      );
    }

    const put = await api.put('/api/v1/admin/settings', {
      data: { valores: { registration_mode: 'open' } },
    });
    if (!put.ok()) {
      throw new Error(
        `não foi possível abrir o cadastro (${put.status()}): ${await put.text()}`,
      );
    }
  } finally {
    await api.dispose();
  }
}

export default globalSetup;
