import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // `.pytest_cache` entrou aqui porque `npm run lint` inteiro falhava com EPERM
  // ao tentar varrê-lo — o lint "passava" só quando apontado a `src/`, e a
  // auditoria externa encontrou o comando completo vermelho.
  globalIgnores([
    'dist', 'coverage', 'playwright-report', 'test-results',
    '.pytest_cache', 'node_modules', '.venv',
  ]),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // Estilo do projeto: payloads de API tipados de forma flexível
      '@typescript-eslint/no-explicit-any': 'warn',
      // catch (err) sem uso é aceito (erros exibidos com mensagem própria)
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        caughtErrors: 'none',
      }],
      // Regras ADVISÓRIAS do React Compiler (plugin v7): disparam em padrões
      // legítimos e intencionais deste app — reset de formulário ao abrir modal,
      // seleção padrão de item/fatura, sync de estado ao trocar de workspace e
      // leitura reativa via react-hook-form `watch`. Não indicam bug.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/incompatible-library': 'off',
    },
  },
  {
    /*
     * Cor sai do design system, não da paleta do Tailwind.
     *
     * O `index.css` define `--income`, `--expense`, `--success` e `--warning`
     * com a luminosidade escolhida para passar em 4,5:1 — e há comentário lá
     * explicando a conta. Ainda assim a auditoria encontrou 46 usos de cor crua
     * em 17 arquivos, e o axe reprovou três deles: `emerald-500` sobre fundo
     * claro dá 2,24:1, e conviver com `--income` põe DOIS verdes diferentes na
     * mesma tela.
     *
     * A regra é sobre o texto da classe porque é assim que o defeito entra:
     * alguém escreve `text-emerald-500` por hábito, o build passa em silêncio
     * (Tailwind conhece a classe) e ninguém vê até alguém medir contraste.
     *
     * `--color-chart-*` continua livre: gráfico é o único lugar em que a cor é
     * dado, não semântica — e essas já vêm de token.
     */
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', {
        selector:
          'Literal[value=/(^|[^a-z-])(bg|text|border|ring|from|to|via|fill|stroke|decoration|outline|shadow|divide|accent|caret|placeholder)-(emerald|amber|slate|rose|sky|zinc|gray|neutral|stone|lime|green|red|blue|indigo|violet|purple|fuchsia|pink|orange|yellow|teal|cyan)-[0-9]/]',
        message:
          'Cor crua do Tailwind. Use os tokens do design system: text-income, '
          + 'text-expense, bg-warning-subtle, text-muted-foreground, bg-muted… '
          + '(ver index.css). Cor crua já reprovou em contraste três vezes.',
      }, {
        /*
         * Jargão interno não vaza para o texto da tela.
         *
         * Achados reais: o subtítulo do gráfico de Relatórios terminava em
         * "(ADR 0022)" — o usuário não tem como saber o que é um ADR, e a
         * referência ocupa o lugar da explicação. E "Abrir a casa", em Acertos,
         * usa o vocabulário do CÓDIGO ("casa" = workspace) enquanto a interface
         * inteira diz "espaço".
         *
         * O alvo é `JSXText`: o que está escrito entre as tags é, por definição,
         * o que a pessoa lê. Comentário em JSX não é `JSXText`, então
         * o código continua livre para explicar as decisões pelo nome — que é
         * onde esse vocabulário deve viver.
         */
        /*
         * "casa" só é jargão quando ocupa o lugar de "espaço" — e é o artigo que
         * denuncia: "abrir A casa", "em todas AS casas". Solto, é português
         * comum, e o diálogo de criar espaço usa "casa" como EXEMPLO de nome
         * ("ex: casa, viagem, família"), que é justamente o texto certo. A regra
         * pegou esse caso na primeira execução; o padrão foi estreitado em vez de
         * o arquivo ser dispensado, senão a próxima regressão ali passa calada.
         */
        selector: 'JSXText[value=/(ADR [0-9]|[^a-z]workspaces?[^a-z]|[^a-z](a|as|da|das|na|nas|numa|cada|essa|dessa|nessa|outra|minha|sua) casas?[^a-z])/i]',
        message:
          'Jargão interno no texto da tela. "ADR NNNN" não diz nada a quem usa; '
          + '"casa"/"workspace" é o nome no código — na interface é "espaço".',
      }],
    },
  },
  {
    // Componentes shadcn/ui e utilitários de teste exportam helpers junto
    // com componentes por design
    files: ['src/components/ui/**/*.tsx', 'src/test/**/*.tsx', 'src/App.tsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
  {
    // O service worker (`public/sw.js`) roda num contexto que não é o da página:
    // `self` é o `ServiceWorkerGlobalScope`, e `clients`/`skipWaiting` não
    // existem em `globals.browser`. Sem este bloco o `no-undef` acusa cinco
    // símbolos legítimos — e a saída era o `/* eslint-env */`, que o ESLint 9
    // não aceita mais.
    files: ['public/**/*.js'],
    languageOptions: {
      globals: globals.serviceworker,
    },
  },
])
