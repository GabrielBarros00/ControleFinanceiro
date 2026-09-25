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
| `test_registry_contract.py` | Contrato de cada tool (nome, título, "Use quando/Não use", 4 annotations coerentes, schema fechado, saída, meta de segurança/UI, idempotência declarada), `tools/list` = registro, `TOOLS.md` em dia; **orçamento de contexto** do catálogo (descrição + entrada ≤ 60 mil caracteres) e schema de entrada sem o ruído do Pydantic (`title`, `anyOf` com nulo, `default: null`) e **só com as palavras de JSON Schema que o Gemini aceita** (`examples` vira texto na descrição) |
| `test_anexo_pelo_terminal.py` | O anexo pelo terminal: do link ao anexo (token no cabeçalho e nunca na URL, auditoria "via IA"), reenvio que não anexa de novo, arquivo recusado (tipo, conteúdo disfarçado) que não gasta o link, cabeçalho ausente/inventado/de outro tipo, registro de outra ação mesmo com o prefixo certo, link expirado e de conexão revogada, papel rebaixado a viewer depois do link, sem escopo de escrita, cota do espaço |
| `test_itens_da_nota.py` | Itens e ajustes: o cenário do relatório (§27: R$ 100 em 2x, arroz de um, shampoo de outro, refrigerante dividido → compra inteira com os itens uma vez só, 55/45, parcelas de 50), desconto com total omitido, itens que não fecham o total (com a diferença nos detalhes), quantidade que não fecha em centavos, parcelado com ajuste recusado, parcelado sem divisão por item que não perde itens, edição que troca a nota inteira, `expected_version` (conflito e exclusão com versão velha), versão que muda só com tag |
| `test_paridade.py` | As lacunas do relatório: assinatura dividida com a sua parte, renda recorrente pelo agente, excluir recorrência cancelando o que está em aberto, renda com descrição/conta, excluir e restaurar, extrato com saldo corrente e caixa do mês, transferências, pagamentos de fatura e estorno (idempotente), financiamento (pagar/desfazer), ler/apagar anexo, anexo grande que não vai ao modelo, arquivo da conversa do ChatGPT e o SSRF do download, categorias/tags, agrupamento por título/categoria/pessoa, desfazer importação (lote invisível para outro membro), alteração em massa e conflito, histórico (e invisível para quem não vê), capacidades no perfil |
| `test_capability_map.py` | Toda rota REST tem decisão; toda tool é citada; `CAPABILITY_MAP.md` em dia |
| `test_espelhos_do_app.py` | Os `Literal` das tools (forma de pagamento, status, frequência, `materialize`) têm exatamente os valores dos enums do app. Valor novo no app reprova até a tool acompanhar |
| `test_audit_and_safety.py` | Trilha sem conteúdo; `origin` no auditlog; log sem token; teto de uso e de escrita; erro interno sem SQL/stack; injeção por título; recurso de UI (CSP vazia, `openai/widgetCSP` com `redirect_domains`); URI do componente versionada com o hash do HTML (mudou o componente, muda a URI); a regra de que só as tools de exibição (`*_show`, mais a prévia de massa) desenham componente, e cada uma declara `openai/widgetDescription`; métricas do admin sem conteúdo |
| `test_plugin_package.py` | Manifestos do plugin válidos e skills citando só tools existentes |
| `evals/test_evals_golden.py` | As 36 trajetórias-ouro de `evals/cases.yaml` executadas contra o banco |

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

- `mcp-widget/__tests__/Widget.test.tsx`: as vistas com o **Preact de verdade** (o
  mesmo do build) e uma ponte falsa. Trava o CONTRATO com o servidor: cada botão chama
  a tool certa com os argumentos certos (só o campo que mudou, a versão lida, uma
  `idempotency_key` por clique, o cursor da página), a diferença antes → depois, o
  Desfazer do `_meta`, `CONFLICT` sem fingir que salvou, tela cheia só quando o host
  deixa, e o limite de erro. Oito mutações no código foram vistas reprovando.
- `mcp-widget/__tests__/bridge.conformidade.test.ts`: a ponte escrita à mão contra o
  host **oficial** do MCP Apps (`AppBridge`), que valida cada mensagem com os schemas
  do protocolo. Cobre handshake, tamanho, resultado, tema e variáveis de estilo,
  `tools/call`, `ui/open-link`, desmontagem, a corrida do resultado que chega antes
  de o componente se registrar, e as mensagens da v4: `ui/request-display-mode`,
  `ui/update-model-context` (só com a capacidade anunciada), `ui/message` e
  `ui/notifications/tool-input`.
- `backend/tests/mcp/test_componente_meta.py`: o `_meta` de cada escrita (vista, modo,
  editor, desfazer), EXECUTANDO o desfazer e conferindo o efeito, e o gate que lê o
  código do componente: toda tool que ele chama tem de ser `app_callable`.
- Revisão visual (manual): um host falso com dados de exemplo para cada vista,
  fotografado pelo Playwright em 360 e 768 px, claro e escuro, e conferido a olho. A
  memória (30 componentes seguidos, heap no tempo, laço de redimensionamento) é
  medida no mesmo tipo de host antes de mexer no teto de tamanho.
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

## Agentes de terminal de verdade (manual)

A suíte prova o servidor; ela não prova que um cliente real entende as tools. Em
23/09/2026 os binários de cada cliente foram apontados para o backend local, com um
token de acesso emitido para um usuário de teste (o login OAuth de cada CLI abre o
navegador; para rodar sem interação, o token entra pelo cabeçalho):

```bash
# backend local com o issuer no próprio backend (sem Vite)
cd backend && FRONTEND_URL=http://localhost:8000 ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# Claude Code — mcp.json: {"mcpServers":{"cf":{"type":"http","url":"http://localhost:8000/mcp",
#                          "headers":{"Authorization":"Bearer cfm_at_…"}}}}
claude -p "Anexe o arquivo recibo-mercado.png (que está nesta pasta) a uma compra recente de mercado" \
  --mcp-config mcp.json --strict-mcp-config \
  --allowedTools "mcp__cf__transactions_search,mcp__cf__transactions_get,mcp__cf__attachments_upload_link,Bash(curl:*),Bash(curl.exe:*)"

# Codex — o sandbox precisa de rede para o curl chegar ao app
CF_TOKEN=cfm_at_… codex exec --skip-git-repo-check --sandbox workspace-write \
  -c 'sandbox_workspace_write.network_access=true' \
  -c 'mcp_servers.cf.url="http://localhost:8000/mcp"' -c 'mcp_servers.cf.bearer_token_env_var="CF_TOKEN"' \
  -c 'approval_policy="never"' "Anexe o arquivo recibo-mercado.png desta pasta ao lançamento #16"

# Gemini CLI — .gemini/settings.json na pasta do teste:
#   {"mcpServers":{"controle-financeiro":{"httpUrl":"http://localhost:8000/mcp",
#                  "headers":{"Authorization":"Bearer cfm_at_…"}}}}
gemini mcp list        # espera "Connected"
```

O que rodou: Claude Code e Codex consultaram (`profile_get`, `statements_get`,
`reports_summary`) e **anexaram um arquivo ponta a ponta** — a tool emitiu o link, o
agente rodou o `curl` (no PowerShell, o Codex usou `curl.exe` sozinho) e o anexo
apareceu no lançamento com a origem `mcp:<cliente>` na auditoria. O Gemini CLI conectou
e listou as tools, mas o modelo não rodou: o Google deixou de aceitar o login com conta
pessoal gratuita no Gemini CLI. Com `GEMINI_API_KEY` ou Vertex AI, funciona.

Repita ao mexer no catálogo, no formato do schema ou no fluxo de anexo. O token de teste
vale 60 minutos; apague o banco de teste depois.
