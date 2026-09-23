# Operação da integração MCP

## Deploy

Nada de serviço novo: o `/mcp` vive no container `backend`, e o `frontend` (nginx)
encaminha:

| Caminho | Destino | Observação |
|---|---|---|
| `= /mcp`, `= /mcp/` (regex exata) | backend | `proxy_buffering off`, timeouts de 120 s, corpo até 1 MB |
| `^~ /.well-known/oauth-` | backend | metadados RFC 9728 / RFC 8414 |
| `= /.well-known/openai-apps-challenge` | backend | verificação de domínio da OpenAI |
| `/api/` (já existia) | backend | inclui `/api/v1/oauth/*` |

Variáveis novas (todas com padrão; ver `.env.example` e `docs/mcp/README.md`):
`MCP_ENABLED`, `MCP_*_TTL_*`, `MCP_ALLOWED_ORIGINS`, `MCP_CIMD_ENABLED`,
`MCP_DCR_ENABLED`, `MCP_RATE_LIMIT_UNITS_PER_MINUTE`,
`MCP_WRITE_RATE_LIMIT_PER_MINUTE`, `MCP_BULK_MAX_ITEMS`,
`OPENAI_APPS_CHALLENGE_TOKEN`.

**`FRONTEND_URL` é o issuer OAuth** e define a URL do recurso
(`${FRONTEND_URL}/mcp`). Mudar o domínio invalida as conexões existentes (a
audiência muda) — os agentes precisarão reconectar.

A migração `47b0bd9dde21` cria as tabelas `oauthclient`, `oauthgrant`,
`oauthauthorizationcode`, `oauthtoken`, `mcptoolcall`, `mcpoperation`,
`mcpconfirmation` e as colunas `auditlog.origin` e `user.public_id` (com
backfill). É idempotente por inspeção e tem `downgrade`.

## Cloudflare / WAF

Os agentes chamam de data centers (OpenAI, Anthropic, Google), sem navegador. Se
o Bot Fight Mode, "Under Attack" ou regras de desafio estiverem ativos, crie uma
exceção (Skip) para:

- `/mcp` e `/mcp/`
- `/.well-known/oauth-protected-resource*`, `/.well-known/oauth-authorization-server`, `/.well-known/openai-apps-challenge`
- `/api/v1/oauth/token`, `/api/v1/oauth/register`, `/api/v1/oauth/revoke`

`/api/v1/oauth/authorize` e a tela `/oauth/consent` são abertas pelo NAVEGADOR da
pessoa e podem continuar sob as regras normais. Faixa de saída da Anthropic
documentada: `160.79.104.0/21` (<https://platform.claude.com/docs/en/api/ip-addresses>).
Nada disso foi alterado no Cloudflare por esta mudança.

## Saúde e métricas

- `GET /api/v1/health` (inalterado).
- Admin › **Saúde**: conexões ativas, chamadas e falhas em 24 h e, por tool,
  volume, falhas e p95 de duração (só metadado).
- Log estruturado `mcp_tool_call` (tool, cliente, resultado, código de erro,
  duração, `request_id`, `replayed`) — sem argumentos nem tokens.
- `mcptoolcall` no banco, com a mesma informação + ids afetados.
- Tela do usuário: **Configurações › Integrações com IA** (conexões e atividade).

## Depuração

| Sintoma | Onde olhar |
|---|---|
| Cliente não chega ao login | `curl -i -X POST https://<site>/mcp` deve dar 401 com `WWW-Authenticate`; `curl https://<site>/.well-known/oauth-protected-resource/mcp` deve dar 200 JSON |
| `invalid_target` | `resource` do cliente ≠ `${FRONTEND_URL}/mcp` |
| `invalid_client` com CIMD | O documento de metadados do cliente não passou na busca/validação (o `error_description` diz o motivo), ou `MCP_CIMD_ENABLED=false` |
| 403 no `/mcp` vindo de navegador | `Origin` fora de `FRONTEND_URL`/`MCP_ALLOWED_ORIGINS` |
| `INTERNAL_ERROR` para o agente | Procure o `correlation_id` no log (`mcp_tool_erro_inesperado`) |
| `RATE_LIMITED` | Teto por pessoa + cliente (`MCP_RATE_LIMIT_*`) |

`smoke_prod.py` percorre, pelo nginx: 401 do `/mcp`, metadados, CORS do token
endpoint, DCR, authorize → consentimento → código → token com PKCE, uma tool,
`/mcp/` sem 307, revogação e 401 depois dela.

## Expurgo

`scripts/purge_old_records.py` (cron mensal) remove: `mcptoolcall` mais antigo que
o corte (180 dias), e — assim que vencem — códigos de autorização, tokens,
confirmações de massa e chaves de idempotência; e clientes OAuth registrados
há mais de 7 dias que nenhuma pessoa autorizou (lixo do registro dinâmico, que é aberto).

## Versionamento das tools

- `serverInfo.version` (`app/mcp/server.py`, hoje `1.0.0`) segue semver próprio,
  independente do app.
- **Nome de tool publicado não muda.** Argumento novo só entra opcional.
- Quebra de contrato = tool nova com sufixo `_v2`; a antiga ganha "[DEPRECATED]" no
  início da descrição e `_meta.deprecated` por pelo menos 90 dias, e sai numa
  versão maior.
- `TOOLS.md` e `CAPABILITY_MAP.md` são gerados; o CI reprova se ficarem velhos.

## Rollback

- Desligar sem deploy de código: `MCP_ENABLED=false` e reiniciar o backend
  (`/mcp`, o OAuth e os metadados respondem 404; a tela de Integrações mostra
  "Integração desativada"; o resto do app segue normal).
- Revogar todas as conexões: `UPDATE oauthgrant SET revoked_at = now(),
  revoked_reason = 'rollback' WHERE revoked_at IS NULL;` (e os tokens deixam de
  valer na próxima chamada).
- Reverter o código: as rotas REST continuam com o mesmo contrato (a extração dos
  comandos não mudou nenhuma resposta), e a migração tem `downgrade`.
