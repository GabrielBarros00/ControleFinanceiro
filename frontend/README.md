# Frontend — Controle Financeiro V4

SPA em **React 19 + Vite + TypeScript**, com Tailwind/shadcn, **TanStack Query** (dados do servidor), **Zustand** (estado de UI/sessão), **react-hook-form + Zod** (formulários) e **Recharts** (gráficos).

Parte do monorepo — veja o [README principal](../README.md), a [arquitetura](../docs/ARCHITECTURE.md) e a [API](../docs/API.md).

## Scripts

```bash
npm run dev        # servidor de desenvolvimento (http://localhost:5173)
npm run build      # tsc -b + build de produção (dist/)
npm run preview    # serve o build localmente
npm test           # testes unitários (vitest)
npm run test:e2e   # end-to-end (Playwright — sobe backend+frontend)
npm run lint       # eslint
npm run typegen    # regenera src/types/api.gen.ts a partir do OpenAPI do backend
```

Em dev, o Vite faz proxy das chamadas para o backend em `http://localhost:8000` (veja `vite.config.ts`). Em produção, o SPA é servido pelo nginx do container do frontend, que também faz proxy de `/api`.

## Estrutura (`src/`)

```
api/          # cliente axios (baseURL, interceptors, refresh automático)
pages/        # telas por rota (Auth, Reports, Settings, Debts, Import, ...)
components/   # UI (shadcn), dashboard, formulário de transação, cartões, dívidas
hooks/        # TanStack Query por recurso + use-workspace-events (tempo real)
stores/       # Zustand (sessão, workspace atual, UI)
lib/          # utilitários (dinheiro, erros da API, métodos de pagamento)
types/        # tipos manuais + api.gen.ts (gerado do OpenAPI)
```

## Convenções

- **Dados do servidor** vivem no TanStack Query (chaves por recurso + workspace); não duplique em store global.
- **Tempo real**: `hooks/use-workspace-events.ts` mantém o WebSocket e invalida as *query keys* conforme o evento; lacuna de sequência → resync total.
- **Erros da API**: leia `err.response?.data?.error?.message` (helper em `lib/api-error.ts`).
- **Formulários**: validação com Zod espelha as regras do backend (ex.: percentuais somam exatamente 100 em centésimos; sem tolerância de float).
- **Diálogos de detalhe** derivam do cache por **ID** — nunca de snapshots do objeto — para refletir sempre o dado atual.
