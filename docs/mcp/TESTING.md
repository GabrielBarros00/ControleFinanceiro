# Testes da integração MCP

## Suíte automatizada (CI)

De dentro de `backend/`:

```bash
../.venv/Scripts/python.exe -m pytest tests/mcp -q          # a integração
../.venv/Scripts/python.exe -m pytest -q                    # tudo (inclui os gates do app)
../.venv/Scripts/python.exe -m app.mcp.docs --check          # TOOLS.md e CAPABILITY_MAP.md em dia
```

| Arquivo | O que prova |
|---|---|
| `test_mcp_transport.py` | 401 com `resource_metadata`/`scope`; token inválido/de sessão do app; Origin 403; cliente 2025-11-25 e 2026-07-28; `server/discover`; `/mcp/` sem 307; `tools/list` determinístico; argumento extra recusado; revogação e conta desativada valem na hora |
| `test_oauth_flow.py` | Metadados RFC 8414/9728; DCR; authorize (redirect inválido não é seguido, `state`, `iss`, loopback em qualquer porta, negar); token (PKCE certo/errado/`plain`, código de uso único e reuso que revoga, `redirect_uri`/cliente/`resource` divergentes, form-urlencoded, segredo DCR); refresh com rotação e reuso que revoga; revogação RFC 7009; troca de senha revoga |
| `test_oauth_cimd.py` | SSRF do CIMD (IP privado/loopback/link-local/mapeado, redirect, tamanho, timeout, content-type, `client_id` divergente, cache) |
| `test_tools_read.py` | Cada leitura: filtros, paginação, limites, ambiguidade, fatura que não cria nada |
| `test_tools_write.py` | Lançamentos: criação composta (cartão, parcelas somando ao centavo, divisão 3-vias, espaço implícito), idempotência (replay, conflito, chave livre após falha), **rollback** com falha injetada, escopo, papel viewer, edição (anterior/mudanças, divisão, valor com divisão, compra inteira), exclusão/restauração, anexo exige prévia, massa (prévia, token de outra pessoa/concessão/ação, conjunto mudou, teto) |
| `test_tools_write_more.py` | Fatura (fecha se o ciclo acabou, parcial, sobrepagamento, em curso, escopo, dono), transferência, conciliação, renda, acertos (teto, member só como pagador, terceiro não vê), recorrência, meta, categoria duplicada, importação |
| `test_isolation.py` | **Matriz A×B**: toda tool com id, chamada com os ids de outra pessoa, não vaza nem altera nada — com teste de denominador que reprova tool nova sem caso |
| `test_registry_contract.py` | Contrato de cada tool (nome, título, "Use quando/Não use", 4 annotations coerentes, schema fechado, saída, meta de segurança/UI, idempotência declarada), `tools/list` = registro, `TOOLS.md` em dia; **orçamento de contexto** do catálogo (descrição + entrada ≤ 60 mil caracteres) e schema de entrada sem o ruído do Pydantic (`title`, `anyOf` com nulo, `default: null`) |
| `test_capability_map.py` | Toda rota REST tem decisão; toda tool é citada; `CAPABILITY_MAP.md` em dia |
| `test_espelhos_do_app.py` | Os `Literal` das tools (forma de pagamento, status, frequência, `materialize`) têm exatamente os valores dos enums do app. Valor novo no app reprova até a tool acompanhar |
| `test_audit_and_safety.py` | Trilha sem conteúdo; `origin` no auditlog; log sem token; teto de uso e de escrita; erro interno sem SQL/stack; injeção por título; recurso de UI (CSP vazia, `openai/widgetCSP` com `redirect_domains`); URI do componente versionada com o hash do HTML (mudou o componente, muda a URI); a regra de que só as tools de exibição (`*_show`, mais a prévia de massa) desenham componente, e cada uma declara `openai/widgetDescription`; métricas do admin sem conteúdo |
| `test_plugin_package.py` | Manifestos do plugin válidos e skills citando só tools existentes |
| `evals/test_evals_golden.py` | As 30 trajetórias-ouro de `evals/cases.yaml` executadas contra o banco |

Também tocados: `tests/services/test_faturas_em_lote.py` (totais e saldos de fatura em
lote dão o mesmo número que fatura a fatura, e o número de consultas não cresce
com o histórico — era ~70 por chamada de `accounts_list` com 18 meses de dois
cartões), `tests/api/test_auth_session.py` (o `next` do login Google e o
open redirect), `tests/services/test_purge_old_records.py`,
`tests/test_nginx_proxy_config.py`, `tests/api/test_ws_event_contract.py` (segue os
comandos extraídos).

### Postgres

Corridas (código de autorização de uso único, reuso de refresh, chave de
idempotência concorrente, pagamento de fatura) só aparecem de verdade no
Postgres. Rode a suíte contra um banco descartável **recriado** (há colunas novas):

```bash
TEST_DATABASE_URL=postgresql://…/cf_test ../.venv/Scripts/python.exe -m pytest tests/mcp -q
```

## Frontend

```bash
cd frontend
npx vitest run src/components/ai-integrations src/pages/__tests__/OAuthConsentPage.test.tsx src/mcp-widget
npm run typecheck && npm run lint
npm run build:mcp-widget        # reconstrói backend/app/mcp/ui/widget.html e confere tamanho/CSP
```

- `mcp-widget/__tests__/Widget.test.tsx`: as quatro vistas com o **Preact de verdade** (o
  mesmo do build), situação da fatura em português, valor da compra na moeda do
  cartão, parcela sem o "(10/10)" repetido, plural sem "(s)".
- `mcp-widget/__tests__/bridge.conformidade.test.ts`: a ponte escrita à mão contra o
  host **oficial** do MCP Apps (`AppBridge`), que valida cada mensagem com os schemas
  do protocolo. Cobre handshake, tamanho, resultado, tema e variáveis de estilo,
  `tools/call`, `ui/open-link`, desmontagem e a corrida do resultado que chega antes
  de o componente se registrar.
- `mcp-widget/__tests__/bridge.test.ts`: o caminho do `window.openai`
  (`openai:set_globals`, resultado tardio, tema).

## Evals com um modelo de verdade (opcional)

```bash
cd backend && pip install anthropic
ANTHROPIC_API_KEY=… python scripts/mcp_live_eval.py --model claude-opus-5-5
```

Pontua seleção de tools, tools proibidas, número de chamadas, pergunta ao usuário
quando há ambiguidade e se a massa só rodou depois do "sim". Fora do CI (custa API).

## MCP Inspector (manual)

```bash
# backend + frontend locais (o Vite encaminha /mcp, /.well-known e /api)
npx @modelcontextprotocol/inspector@latest
```

No Inspector: Transport **Streamable HTTP**, URL `http://localhost:5173/mcp`,
autenticação OAuth. Ele se registra por DCR, abre `/oauth/consent` (entre no app
se pedir) e volta com o token. Roteiro: `tools/list` → `profile_get` →
`transactions_create` (repita com a mesma `idempotency_key` e veja
`replayed: true`) → `transactions_update` → `transactions_bulk_preview` →
`transactions_bulk_delete` com o token. Depois, **Desconectar** na tela do app e
ver o próximo call responder 401.
