/**
 * Os rótulos que as suítes de ponta a ponta digitam — num lugar só.
 *
 * ## O episódio
 *
 * Uma rodada de melhorias de texto trocou "Começar Setup" por "Começar" e
 * "Próximo Passo" por "Próximo". As suítes de `e2e/` foram atualizadas junto,
 * porque elas rodam a cada `npm run test:e2e`. As de `e2e-prod/` não: elas só
 * sobem no CI, atrás do docker compose, e o erro só apareceu quarenta minutos
 * depois — num job vermelho cuja causa não tinha nada a ver com o que ele testa
 * (sessão atrás do nginx).
 *
 * É o mesmo padrão que este projeto já registrou duas vezes: **portão que não
 * roda na máquina apodrece**. A defesa aqui não é lembrar de atualizar os dois
 * lugares — é não ter dois lugares.
 *
 * ## Por que texto, e não `data-testid`
 *
 * Porque o teste deve falhar quando o texto muda. O rótulo de um botão de
 * onboarding é conteúdo do produto: se ele mudar sem que ninguém repare, o que
 * está errado é o processo, não o seletor. O que este arquivo evita é que a
 * mesma mudança precise ser feita em N arquivos — e que a descoberta de uma
 * delas custe uma rodada de CI.
 *
 * `src/components/layout/__tests__/OnboardingModal.rotulos.test.tsx` fecha o
 * ciclo: ele renderiza o diálogo de verdade e confere que estes textos existem,
 * em segundos, no `npm run test` de todo dia.
 */
export const ONBOARDING = {
  /*
   * Textos EXATOS, não trechos.
   *
   * A primeira versão daqui usava `/Começar/` — e o portão do vitest passou
   * feliz com "Começar Setup", que é exatamente o texto que estava quebrando o
   * CI. Uma expressão regular frouxa num teste de acoplamento não testa o
   * acoplamento: ela casa com o antes E com o depois.
   *
   * No `getByRole` do Testing Library, `name` como string casa com o nome
   * acessível INTEIRO — é a igualdade que faz o portão valer. No Playwright a
   * mesma string casa por trecho, o que é a tolerância certa lá: a suíte não
   * deve quebrar por um espaço a mais.
   */
  comecar: 'Começar',
  /** Passo 2 → 3, quando há salário preenchido. */
  proximo: 'Próximo',
  /** Passo 3: sai sem cadastrar cartão (recarrega a página). */
  pular: 'Pular esta etapa',
  /** O campo do passo 2. */
  salario: 'Salário / Renda Líquida',
} as const;

/** O título da primeira tela depois do onboarding. */
export const TITULO_INICIO = 'Hoje';

/**
 * Outros textos que as suítes digitam e que já derivaram em silêncio.
 *
 * "Sair da Conta" virou "Sair da conta" na mesma rodada de melhorias de texto —
 * e o `e2e-prod` continuou procurando a versão antiga por trás de OUTRA falha,
 * que o escondia. Dois rótulos podres no mesmo arquivo, um encobrindo o outro.
 */
export const ROTULOS = {
  sair: 'Sair da conta',
} as const;

/**
 * Onde cada rótulo mora — o arquivo que a suíte de fato visita.
 *
 * Sem isto a varredura é frouxa demais para servir: "Sair da conta" aparece no
 * menu lateral, na gaveta do celular E em Configurações, e a suíte clica no de
 * **Configurações**. Renomear só esse (foi o que aconteceu) deixa o texto vivo
 * nos outros dois, a varredura passa e o CI reprova assim mesmo.
 *
 * Amarrar rótulo a arquivo troca "este texto existe em algum lugar" por "este
 * texto existe ONDE a suíte vai clicar", que é a pergunta que interessa.
 */
export const ONDE: Record<string, string> = {
  'Sair da conta': 'src/pages/Settings/SettingsPage.tsx',
  'Começar': 'src/components/layout/OnboardingModal.tsx',
  'Próximo': 'src/components/layout/OnboardingModal.tsx',
  'Pular esta etapa': 'src/components/layout/OnboardingModal.tsx',
  'Salário / Renda Líquida': 'src/components/layout/OnboardingModal.tsx',
};
