/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from "path"

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Separa os vendors pesados do código da app: melhora cache (mudam pouco)
        // e evita o chunk único > 500 kB. recharts/framer já entram por lazy route.
        // Forma de função (o bundler rolldown do Vite 8 não aceita o objeto).
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('recharts')) return 'recharts';
          if (id.includes('framer-motion')) return 'motion';
          if (id.includes('react-router') || id.includes('react-dom') || /[\\/]react[\\/]/.test(id)) {
            return 'react-vendor';
          }
          return undefined;
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // Fuso fixo: os bugs de data só aparecem em offset negativo, e o CI roda em
    // UTC. Sem fixar, o teste passaria na máquina do dev e não pegaria nada lá.
    env: { TZ: 'America/Sao_Paulo' },
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**', '**/e2e-prod/**', '**/e2e-shots/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/', 'src/test/', 'e2e/', 'e2e-prod/', 'e2e-shots/',
        // Gerado a partir do OpenAPI: medir cobertura de declaração de tipo não
        // diz nada, e o arquivo é grande o bastante para distorcer o total.
        'src/types/api.gen.ts',
      ],
      /*
       * PISO, não meta. O backend tem `--cov-fail-under=90` e o frontend não
       * tinha limite nenhum: a cobertura podia cair a cada PR sem que nada
       * apontasse — e foi assim que `OverviewPage`, `use-overview`, `AppShell`,
       * `BottomNav` e `nav-items` chegaram a 0% justamente nas telas da Onda 5.
       *
       * Os números são os de HOJE arredondados para baixo, de propósito: um piso
       * que já falha não é gate, é ruído que se aprende a ignorar. Ele existe
       * para impedir REGRESSÃO; subir é trabalho de cada onda, e o número aqui
       * sobe junto.
       */
      // Onda 7: 60/52/48/62 → 62/55/50/65. O que subiu foi o que a onda tocou —
      // pagamento parcial de fatura, limiares dos relatórios, o extrato global
      // (que nasceu coberto) e as duas listas de invalidação corrigidas.
      //
      // Onda 8: 62/55/50/65 → 63/55/51/65 (medido 63,21/55,55/51,92/65,98). A
      // auditoria apontou que a margem estava raspando o piso justamente nas
      // áreas dos defeitos, e a subida veio de testes escritos onde eles
      // moravam: a serialização HTTP dos filtros (o teste antigo mockava o hook
      // e por isso não via nada), a paginação do extrato e o estorno ao reabrir
      // fatura. Branches e lines ficam onde estão — a folga real é de meio
      // ponto, e um piso que já falha vira ruído.
      //
      // Onda 9: 63/55/51/65 → 63/56/52/66 (medido 63,48/56,46/52,36/66,11). A
      // auditoria anterior observou que a margem estava raspando o piso — e os
      // quatro defeitos graves desta onda confirmaram o diagnóstico ao passarem
      // por 2.348 testes de backend e 236 de frontend sem encostar em nenhum.
      // Os testes novos vão onde eles moravam: o valor de fatura na moeda do
      // cartão, o erro que virava um mês de zeros, o id inválido na URL e a
      // página fora do intervalo. `statements` fica em 63 de propósito — subiu
      // meio ponto, e um piso a meio ponto do medido falha no primeiro refactor.
      //
      // Onda do Admin (ADR 0026): 63/56/52/66 → 63/57/53/66 (medido
      // 64,14/57,81/54,58/66,65). A onda acrescentou uma superfície grande —
      // `AdminPage.tsx` e `use-admin.ts` —, e o primeiro efeito de código novo
      // é DERRUBAR a medição: os dois arquivos passaram a ser contados assim
      // que um teste os importou. A subida veio de cobrir o que eles fazem: o
      // portão `enabled` de toda consulta de `/admin` (sem ele, um usuário
      // comum dispara meia dúzia de 404 por carga de página), as chaves de
      // invalidação, o teto do nginx no tamanho de arquivo e a formatação de
      // dia civil.
      //
      // `statements` fica em 63 e `lines` em 66 de propósito: subir para 64/67
      // deixaria a margem em 0,14 e 0,65 ponto, e um piso que raspa o medido
      // falha no primeiro refactor — a lição registrada na Onda 9.
      //
      // Auditoria da onda: 64,35/58,17/54,67/66,84 (a tela de cadastro e o
      // helper de clipboard ganharam teste; os pisos seguem os mesmos).
      thresholds: {
        statements: 63,
        branches: 57,
        functions: 53,
        lines: 66,
      },
    },
  },
})
