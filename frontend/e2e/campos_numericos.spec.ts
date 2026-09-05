import { test, expect, type Page } from '@playwright/test';

/*
 * O portão contra o zero à esquerda.
 *
 * Um campo mostra `0`, a pessoa digita `5`, e o campo passa a mostrar **`05`** —
 * e fica assim. O valor que chega no servidor está certo (5); quem mente é a
 * tela, e num app de dinheiro isso corrói a confiança no formulário inteiro.
 *
 * ## Por que nenhum teste pegava
 *
 * Porque testar formulário com `fill()` **substitui** o campo inteiro, e o
 * defeito só existe quando se **digita sobre** o que já está lá. Todo campo
 * daqui nasce preenchido (dia 1, dia 10, 12 parcelas), então digitar por cima é
 * exatamente o gesto de quem usa o produto — e era o único gesto que nenhum
 * teste fazia. Por isso aqui é `type()`, sempre, e nunca `fill()`.
 *
 * ## A causa, que explica o formato do teste
 *
 * Para `<input type="number">` controlado, o React decide se reescreve o DOM com
 * uma comparação FROUXA (`node.value != value`). Com `node.value === "05"` e
 * `value === 5`, `"05" == 5` é verdadeiro em JavaScript — o React conclui que
 * nada mudou e não reescreve. O zero fica.
 *
 * A aba de Configurações da Administração é o **controle positivo** deste teste:
 * ela é a única tela do app que já passava, porque é a única que renderiza
 * `value={String(...)}`. Se ela falhar, o defeito é do teste, não do app.
 */
const API = 'http://localhost:8000/api/v1';

async function entrar(page: Page) {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  /*
   * Conta descartável, SEMPRE — nunca a do `SUPERADMIN_EMAIL`.
   *
   * A primeira versão deste arquivo usava aquela conta para alcançar `/admin` no
   * controle positivo, e o efeito foi indireto e caro de achar: só o PRIMEIRO
   * usuário do banco recebe o papel pela janela de bootstrap (ADR 0026), então
   * registrar o mesmo e-mail aqui fazia a conta nascer como usuário comum — e
   * quem quebrava eram `a11y.spec.ts` e `mobile_layout.mobile.spec.ts`, que
   * dependem dela e não têm nada a ver com este arquivo.
   */
  const email = `num${ts}@e2e.com`;
  const api = page.context().request;
  await api.post(`${API}/auth/register`, { data: { name: 'Nina Números', email, password: 'senha123' } });
  await api.post(`${API}/auth/login`, { data: { email, password: 'senha123' } });
  await api.post(`${API}/auth/onboarding`, { data: { salary: 4000 } });
  const [ws] = await (await api.get(`${API}/workspaces/`)).json();
  return ws.id as number;
}

/**
 * O gesto: zerar o campo, digitar `0`, e então digitar `5` com o cursor no fim.
 *
 * `press('End')` importa: sem ele o cursor pode estar no começo e o resultado
 * seria `50`, que é outra coisa. O que se mede aqui é o zero que SOBRA à
 * esquerda, não a posição do cursor.
 */
async function digitarSobreZero(page: Page, seletor: string, rotulo: string) {
  const campo = page.locator(seletor).first();
  await campo.click();
  await campo.press('Control+a');
  await campo.type('0');
  // Alguns campos NÃO conseguem segurar o `0` intermediário: o `onChange` tem um
  // fallback (`|| 5`, `Math.max(1, … || 1)`) que salta para outro número a cada
  // tecla. Normalizar é certo — normalizar no meio da digitação impede de
  // digitar. Vale a mesma correção do zero à esquerda, e por isso falha aqui.
  await expect(
    campo,
    `${rotulo}: o campo não consegue exibir "0" enquanto se digita — ele salta `
    + `sozinho para outro valor, e isso impede de digitar um número que comece por 0`,
  ).toHaveValue('0');
  await campo.press('End');
  await campo.type('5');
  /*
   * A normalização é cobrada ao SAIR do campo, não a cada tecla — e a diferença
   * é deliberada.
   *
   * Exigir "5" no instante em que a tecla é digitada obrigaria o componente a
   * reescrever o campo a cada caractere, e é justamente isso que impedia apagar
   * o conteúdo para redigitar (o `podeEsvaziar` abaixo cobre o outro lado).
   * Enquanto a pessoa digita, o campo é dela; ao sair, ele se acerta.
   *
   * Isto continua sendo um portão de verdade para o defeito original: antes,
   * "05" sobrevivia ao blur, ao submit e a tudo mais — nada normalizava nunca.
   */
  await campo.blur();
  await expect(
    campo,
    `${rotulo}: o campo mostrava "0", recebeu "5" e devia exibir "5" ao sair`,
  ).toHaveValue('5');
}

/**
 * Um campo numérico tem de poder ficar VAZIO enquanto se digita.
 *
 * Vários deles reagem a `0` com um fallback (`|| 5`, `Math.max(1, … || 1)`) que
 * salta para outro número no meio da digitação — e o efeito colateral é que não
 * dá para apagar o campo para redigitar: ele se repõe sozinho. Normalizar é
 * certo; normalizar a cada tecla, não.
 */
async function podeEsvaziar(page: Page, seletor: string, rotulo: string) {
  const campo = page.locator(seletor).first();
  await campo.click();
  await campo.press('Control+a');
  await campo.press('Backspace');
  // Sem `blur`: o vazio é um estado VÁLIDO da digitação, e é só isso que se
  // afirma aqui. Ao sair, o campo pode legitimamente voltar ao padrão — o que
  // ele não pode é se repor a cada tecla, impedindo de apagar para redigitar.
  await expect(
    campo,
    `${rotulo}: não foi possível apagar o campo — ele se repõe sozinho a cada tecla`,
  ).toHaveValue('');
}

test('novo cartão: dia de fechamento e de vencimento não guardam zero à esquerda', async ({ page }) => {
  await entrar(page);
  await page.goto('/me/cards');
  await page.getByRole('button', { name: /novo cartão/i }).first().click();
  await digitarSobreZero(page, '#closing-day', 'Dia de fechamento');
  await digitarSobreZero(page, '#due-day', 'Dia de vencimento');
  await podeEsvaziar(page, '#closing-day', 'Dia de fechamento');
});

test('novo financiamento: número de parcelas não guarda zero à esquerda', async ({ page }) => {
  await entrar(page);
  await page.goto('/me/financing');
  await page.getByRole('button', { name: /novo financiamento/i }).first().click();
  await digitarSobreZero(page, 'input[aria-label="Número de parcelas"]', 'Número de parcelas');
});

test('recorrência: dia do mês não guarda zero à esquerda', async ({ page }) => {
  const wsId = await entrar(page);
  await page.goto(`/w/${wsId}/recurring`);
  await page.getByRole('button', { name: /nova despesa/i }).first().click();
  await digitarSobreZero(page, '[role="dialog"] input[id$="-dom"]', 'Dia do mês');
  await podeEsvaziar(page, '[role="dialog"] input[id$="-dom"]', 'Dia do mês');
});

/*
 * O dia de fechamento SAIU do onboarding — cartão deixou de ser perguntado na
 * porta de entrada (a pergunta agora é "quanto você tem hoje, e onde", que é o
 * único dado que o app não deduz). A invariante não mudou de valor por causa
 * disso: ela seguiu o campo para o diálogo de cartão, que é onde ele vive.
 *
 * Apagar a versão do onboarding sem mover o teste teria trocado uma cobertura
 * real por um arquivo menor.
 */
test('cartão: o dia de fechamento aceita ser apagado', async ({ page }) => {
  const wsId = await entrar(page);
  void wsId;
  await page.goto('/me/cards');
  await page.getByRole('button', { name: /novo cartão/i }).first().click();
  await digitarSobreZero(page, '[role="dialog"] input#closing-day', 'Dia de fechamento');
  await podeEsvaziar(page, '[role="dialog"] input#closing-day', 'Dia de fechamento');
});

/*
 * CONTROLE POSITIVO — prova que o teste mede o app, e não o jeito de digitar.
 *
 * O `MoneyInput` já resolvia esta família de problemas antes desta rodada, por
 * um caminho próprio: ele guarda o texto em estado local e aplica uma máscara.
 * Digitar `5` sobre um campo zerado tem de produzir `0,05` — canônico, sem
 * sobra de dígito. Se o harness estivesse quebrado (não digitando, digitando no
 * lugar errado), este campo falharia junto com os outros, e a conclusão seria
 * outra.
 *
 * A versão anterior deste controle usava a aba de Configurações da
 * Administração, que eram os únicos campos corretos ANTES da correção. Ele
 * cumpriu esse papel durante a implementação e saiu: alcançar `/admin` exige a
 * conta do `SUPERADMIN_EMAIL`, que é única no banco e já pertence a outros dois
 * arquivos da suíte — registrar a mesma conta aqui tirava o papel de
 * superadministrador deles, e o que quebrava eram os testes vizinhos.
 */
test('controle: um campo com máscara própria termina canônico', async ({ page }) => {
  const wsId = await entrar(page);
  await page.goto(`/w/${wsId}/transactions`);
  await page.getByRole('button', { name: /nova despesa/i }).first().click();

  const valor = page.locator('[role="dialog"] input[inputmode="numeric"]').first();
  await valor.click();
  await valor.press('Control+a');
  await valor.type('5');
  await expect(
    valor,
    'o campo de dinheiro devia mascarar "5" como "0,05" — se ele falhar aqui, '
    + 'o defeito está no teste (ou no harness), não nos campos numéricos',
  ).toHaveValue('0,05');
});
