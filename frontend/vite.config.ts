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
      exclude: ['node_modules/', 'src/test/', 'e2e/', 'e2e-prod/', 'e2e-shots/'],
    },
  },
})
