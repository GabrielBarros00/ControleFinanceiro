## O que muda e por quê

<!-- O problema (com o número medido, quando houver) e a decisão. Quem revisa deve
entender o porquê sem abrir o diff. -->

## Checklist

Marque o que se aplica. O que não se aplica, risque ou diga por quê.

- [ ] Teste do que mudou; se é correção, o teste foi visto **falhando** sem ela
- [ ] Suítes verdes: backend (`python -m pytest`, `ruff check`) e frontend
      (`npm run lint`, `npm run typecheck`, `npm test`, `npm run build`)
- [ ] Schema mudou: migração Alembic, validada também no Postgres
- [ ] **MCP conferido** (checklist em `CONTRIBUTING.md` › "Mudou uma funcionalidade?
      Confira o MCP"): o que mudou nas tools, ou por que nada mudou
- [ ] Arquivos gerados em dia: `npm run typegen`, `python -m app.mcp.docs`,
      `npm run build:mcp-widget`
- [ ] Termo novo na tela ou no código: acrescentado ao `CONTEXT.md`
- [ ] Decisão de arquitetura: ADR novo em `docs/adr/`
- [ ] Mudança que a pessoa vê: `CHANGELOG.md`, em `[Não lançado]`

## Plano de testes

<!-- O que foi rodado e o resultado; o que ficou sem verificar, e por quê. -->
