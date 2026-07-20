import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'playwright-report', 'test-results']),
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
    // Componentes shadcn/ui e utilitários de teste exportam helpers junto
    // com componentes por design
    files: ['src/components/ui/**/*.tsx', 'src/test/**/*.tsx', 'src/App.tsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
])
