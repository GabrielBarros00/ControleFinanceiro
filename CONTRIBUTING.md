# Guia de contribuição

Como configurar o ambiente, rodar as verificações e seguir as convenções do projeto.

## Ambiente de desenvolvimento

Pré-requisitos: **Python 3.12+**, **Node 20+**, e (opcional) **Docker** para rodar o stack completo ou testar contra Postgres.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # inclui produção + pytest/ruff
cp .env.example .env
python -m uvicorn app.main:app --reload             # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

Em dev o banco é SQLite (`backend/dev.db`), criado/migrado no startup; links de e-mail saem no console.

## Verificações (rode antes de abrir PR)

Opcional, mas recomendado: `pip install pre-commit && pre-commit install` — os hooks de [`.pre-commit-config.yaml`](.pre-commit-config.yaml) rodam ruff (backend) e eslint (frontend) automaticamente a cada commit.

```bash
make test        # pytest + vitest
make lint        # ruff + eslint

# Backend
cd backend && python -m pytest              # SQLite em memória
cd backend && ruff check app && ruff format --check app

# Frontend
cd frontend && npm test                     # vitest
cd frontend && npm run lint                 # eslint
cd frontend && npm run build                # tsc + vite build
cd frontend && npm run test:e2e             # Playwright (sobe backend+frontend)
```

### Rodar a suíte contra PostgreSQL

O CI e a validação de produção usam Postgres. Para reproduzir localmente:

```bash
docker run -d --rm --name cf_pg -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
# aguarde o banco aceitar conexões, então:
TEST_DATABASE_URL=postgresql+psycopg2://postgres:dev@localhost:5432/postgres \
  APP_ENV=test python -m pytest
```

> Os testes montam o schema via `create_all` a partir dos **models**, que podem declarar FKs que as migrações não criam. Por isso a suíte pode passar em SQLite (que não impõe FK) e falhar em Postgres — **sempre valide migrações/mudanças de model contra Postgres**.

## Migrações (Alembic)

Alembic é o **único** caminho de schema (ADR 0005). Ao mudar um model:

```bash
cd backend
alembic revision -m "descrição curta"       # crie a revisão
# edite o arquivo em alembic/versions/: escreva upgrade()/downgrade() IDEMPOTENTES
alembic upgrade head                         # aplique em dev  (ou: make migrate)
```

> **Não confie no auto-upgrade do startup.** Ele só roda com
> `APP_ENV == development`, e o `APP_ENV` vem do `.env` lido **relativo ao
> diretório de onde você subiu o processo**: quem inicia o uvicorn da raiz pega o
> `.env` de produção e o `dev.db` simplesmente não migra. A defasagem é
> silenciosa — numa auditoria o `dev.db` estava 15 revisões atrás do head. Rode
> **`make migrate`** (ou o `alembic upgrade head` acima) depois de trocar de
> branch.

- Mantenha a cadeia **linear** (um único *head*): `down_revision` aponta para o head anterior.
- `upgrade()` deve ser idempotente (checar `inspector` antes de `add_column`/`create_table`) — o DDL do SQLite não é transacional.
- Valide o upgrade **do zero** e contra uma **cópia** do banco, em SQLite e Postgres.

## Tipos gerados do OpenAPI

```bash
cd frontend && npm run typegen   # dump do OpenAPI + openapi-typescript → src/types/api.gen.ts
```
Zod é usado só para UX de formulário; o contrato de dados vem do backend.

## Mudou uma funcionalidade? Confira o MCP

Os agentes de IA (ChatGPT, Claude, Codex, Gemini…) usam o app pelo servidor MCP em
`backend/app/mcp/` ([ADR 0035](docs/adr/0035-integracao-com-agentes-de-ia-mcp.md)).
Toda funcionalidade **adicionada, alterada ou removida** tem de ser conferida lá
também, senão o agente fica com uma versão velha do app: recusa o que o app aceita,
ou aceita o que o app deixou de aceitar.

**O que o CI já barra sozinho:**

- Rota REST nova ou removida sem decisão em `backend/app/mcp/capability_map.py`
  (`tests/mcp/test_capability_map.py`). Toda rota diz qual tool a expõe, ou por
  que não expõe.
- Valor novo num enum espelhado pelas tools: forma de pagamento, status do
  lançamento, frequência (`tests/mcp/test_espelhos_do_app.py`).
- `docs/mcp/TOOLS.md` e `docs/mcp/CAPABILITY_MAP.md` desatualizados: rode
  `cd backend && python -m app.mcp.docs` e comite o resultado.
- Tool que recebe id sem caso de isolamento entre usuários
  (`tests/mcp/test_isolation.py`).
- Componente visual desatualizado: rode `cd frontend && npm run build:mcp-widget`
  e comite `backend/app/mcp/ui/widget.html`. Se o HTML mudou (inclusive por
  atualização de dependência), some 1 em `WIDGET_VERSION` e atualize `WIDGET_SHA256`
  em `backend/app/mcp/ui/__init__.py`. A URI é chave de cache no ChatGPT, e o teste
  `test_mudou_o_componente_mudou_a_uri` mostra o hash novo.

**O que nenhum gate pega, e você confere à mão:**

- **A regra mora no comando, não na rota.** As escritas vivem em
  `backend/app/services/commands/`, e o REST e o MCP chamam o mesmo código. Regra
  escrita direto na rota o agente não vê.
- **Campo novo, renomeado ou removido** num schema de entrada ou de saída: a tool
  correspondente (`backend/app/mcp/tools/`) e a saída (`backend/app/mcp/schemas.py`,
  `serializers.py`) precisam acompanhar?
- **Caminho diferente para o mesmo pedido.** O app às vezes manda a edição
  completa onde uma tool mandaria a parcial. Foi assim que "trocar a moeda" passou
  sem converter até a verificação final do PR #104. Teste o caso pela tool, em
  `backend/tests/mcp/`.
- **Visibilidade**: as leituras do MCP usam os predicados da `access_policy`. Filtro
  novo feito à mão numa rota tem de ir para lá.
- **Textos que descrevem o comportamento**: descrição da tool ("Use quando / Não
  use quando"), instruções do servidor (`backend/app/mcp/instructions.py`), skills
  (`integrations/controle-financeiro-plugin/skills/`) e casos de eval
  (`backend/tests/mcp/evals/cases.yaml`).
- **Remoção**: o nome de uma tool publicada não muda nem some de uma vez. A política
  de versões está em [docs/mcp/OPERATIONS.md](docs/mcp/OPERATIONS.md).

## Convenções

- **Commits**: mensagens no estilo convencional (`feat:`, `fix:`, `docs:`, `chore:`, `test:`), imperativo, em PT-BR. Uma mudança coesa por commit.
- **Erros**: sempre no envelope `{"error": {...}}` (ver [docs/API.md](docs/API.md)); mensagens de negócio em PT-BR.
- **Transações**: serviços usam `flush()`, a rota faz o `commit` (ADR 0010). Não commite dentro de um serviço.
- **Escritas**: a regra vai em `app/services/commands/` (a rota só faz o commit e responde). É o que mantém o app e os agentes de IA com a mesma regra (ADR 0035).
- **Dinheiro**: `Decimal`/centavos, nunca `float`. Use `app/domain/money.py`.
- **Decisões**: mudanças arquiteturais relevantes viram um ADR em [docs/adr/](docs/adr/README.md).
- **Vocabulário**: termo novo na tela ou no código entra no [CONTEXT.md](CONTEXT.md), o glossário do domínio. Renomeou um campo citado lá? `tests/test_context_md.py` reprova até o glossário acompanhar.
- **WebSocket**: o backend roda com **1 worker** (gerenciador in-process); não altere isso sem introduzir um broker.
