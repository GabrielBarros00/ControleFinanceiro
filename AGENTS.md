# Instruções para agentes de IA

Vale para qualquer agente que trabalhe neste repositório (Codex, Claude Code,
Gemini, Cursor…). O guia completo para humanos é o [CONTRIBUTING.md](CONTRIBUTING.md);
este arquivo resume o que não pode ser esquecido e aponta para lá.

## O projeto

Controle Financeiro: finanças pessoais e compartilhadas (lançamentos, divisão entre
pessoas, cartões e faturas, contas, rendas, dívidas e acertos).

- `backend/`: FastAPI + SQLModel, com Alembic para o schema. Postgres em produção e
  SQLite em dev e nos testes.
- `frontend/`: React + Vite + TypeScript + Tailwind v4.
- `backend/app/mcp/`: servidor MCP para agentes de IA
  ([ADR 0035](docs/adr/0035-integracao-com-agentes-de-ia-mcp.md), [docs/mcp/](docs/mcp/README.md)).
- Decisões de arquitetura ficam em [docs/adr/](docs/adr/README.md). Mudança
  arquitetural relevante vira um ADR novo, com o próximo número.

Tudo é em **português do Brasil**: código, comentários, mensagens de erro, commits,
PRs e documentação.

## Regras que não se negociam

- **Dinheiro** é `Decimal` em centavos, nunca `float` (ADR 0001).
- **Escritas**: a regra fica em `backend/app/services/commands/`. Comandos fazem
  `flush()`, e a rota faz o único `commit` e responde (ADR 0010). O app e os
  agentes de IA chamam o mesmo comando, e é isso que os mantém com a mesma regra.
- **Schema** só muda por Alembic (ADR 0005). Valide a migração também contra
  Postgres, porque o SQLite não pega tudo.
- **Erros da API** saem no envelope `{"error": {...}}`, com mensagem em pt-BR
  ([docs/API.md](docs/API.md)).
- **Um worker só** no backend (o WebSocket é in-process). Não mude isso.
- **Visibilidade** passa pela `app/domain/access_policy.py`: o que a pessoa não
  pode ver responde 404.

## Mudou, adicionou ou removeu uma funcionalidade? Confira o MCP

Toda mudança no app tem de ser conferida no servidor MCP **na mesma entrega**. Sem
isso, o agente de IA fica com uma versão velha do app: recusa o que o app aceita, ou
aceita o que ele deixou de aceitar. O CI barra parte disso:

- rota nova sem decisão no `capability_map.py`;
- enum espelhado pelas tools;
- documentação gerada desatualizada;
- tool sem teste de isolamento.

Campo novo em schema, caminho diferente (edição parcial × completa) e os textos das
tools passam calados. Siga o checklist em
[CONTRIBUTING.md › Mudou uma funcionalidade? Confira o MCP](CONTRIBUTING.md#mudou-uma-funcionalidade-confira-o-mcp),
teste o caso pela tool em `backend/tests/mcp/`, e diga no relatório o que mudou no
MCP, ou por que nada mudou.

## Como verificar

O backend só roda **de dentro de `backend/`** (o `.env` é lido relativo ao diretório
do processo; da raiz ele pega o `.env` do deploy).

```bash
cd backend && python -m pytest -q            # suíte inteira (SQLite)
cd backend && ruff check .                   # lint (o CI não roda `ruff format`)
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd frontend && npm run test:e2e              # Playwright, sobe backend e frontend
```

- Use `npm run typecheck`, **não** `npx tsc --noEmit`. O `tsconfig.json` da raiz tem
  `"files": []`, e o comando solto não checa nada.
- Não rode `ruff format` / `make format` no backend inteiro. O código nunca foi
  formatado assim, e o diff viraria ruído misturado à sua mudança.
- Para rodar contra Postgres, use `TEST_DATABASE_URL` (ver CONTRIBUTING.md).

**Arquivos gerados**: regenere e comite junto; o CI compara.

| Mudou | Rode | Gera |
|---|---|---|
| Rota ou schema da API | `cd frontend && npm run typegen` | `frontend/src/types/api.gen.ts` |
| Tool MCP ou `capability_map.py` | `cd backend && python -m app.mcp.docs` | `docs/mcp/TOOLS.md`, `docs/mcp/CAPABILITY_MAP.md` |
| `frontend/src/mcp-widget/` | `cd frontend && npm run build:mcp-widget` | `backend/app/mcp/ui/widget.html` |

## Git

- Branch a partir da `main`. PRs são mergeados por squash.
- Commits convencionais em pt-BR (`feat(escopo): …`, `fix(escopo): …`), uma mudança
  coesa por commit.
- Não comite artefatos locais (`*.db`, `frontend/openapi.json`, resultados de teste)
  nem arquivos que não são seus.
- Commit, push, PR e deploy só quando o dono pedir.
