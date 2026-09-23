# Autenticação e autorização

O `/mcp` é um **resource server** OAuth 2.1; o **authorization server** é o
próprio app (o SDK do MCP não fornece um, e o login a reaproveitar é o do app).

## Descoberta

1. O cliente chama `POST /mcp` sem token e recebe **401** com:

   ```
   WWW-Authenticate: Bearer resource_metadata="https://<site>/.well-known/oauth-protected-resource/mcp",
                     scope="finance.read transactions.write accounts.write income.write settlements.write planning.write"
   ```

   (Com token inválido/expirado, acrescenta `error="invalid_token"`.)
2. `GET /.well-known/oauth-protected-resource/mcp` (RFC 9728) → `resource`
   (`https://<site>/mcp`), `authorization_servers` (`["https://<site>"]`),
   `scopes_supported`, `bearer_methods_supported: ["header"]`.
3. `GET /.well-known/oauth-authorization-server` (RFC 8414) → `issuer`,
   `authorization_endpoint`, `token_endpoint`, `registration_endpoint` (se DCR
   ligado), `revocation_endpoint`, `code_challenge_methods_supported: ["S256"]`,
   `token_endpoint_auth_methods_supported` (`none`, `client_secret_basic`,
   `client_secret_post`), `authorization_response_iss_parameter_supported: true`,
   `client_id_metadata_document_supported: true`.

Os endpoints do AS ficam em `/api/v1/oauth/*` (o nginx já encaminha `/api/`).

## Registro do cliente

- **CIMD** (preferido pela especificação 2026-07-28): o `client_id` é uma URL
  https com o documento de metadados do cliente (ex.: o do Claude Code). O servidor
  busca o documento com proteção de SSRF — só https na porta 443, sem redirect,
  sem credencial na URL, IP público conferido na resolução **e** no socket, até
  64 KB, 5 s de timeout, `client_id` do documento igual à URL — e guarda em cache
  entre 5 min e 24 h conforme o `Cache-Control`.
- **DCR** (RFC 7591, por compatibilidade: Antigravity, Gemini, MCP Inspector):
  `POST /api/v1/oauth/register` com `redirect_uris`, `client_name`,
  `token_endpoint_auth_method` (padrão RFC: `client_secret_basic`; clientes
  públicos mandam `none`). Limite de 20 registros por hora por IP.

**Regras de `redirect_uri`**: https, ou http só em loopback (`localhost`,
`127.0.0.1`, `[::1]`); sem fragmento, sem credencial, sem curinga. Para loopback a
**porta é ignorada** na comparação (agentes de terminal escolhem porta livre).
Redirect inválido nunca recebe redirecionamento: a pessoa vê o erro na tela.

## Autorização (Authorization Code + PKCE S256)

```
GET /api/v1/oauth/authorize?response_type=code&client_id=…&redirect_uri=…
    &code_challenge=…&code_challenge_method=S256&state=…&scope=…&resource=https://<site>/mcp
```

- `S256` obrigatório; `plain` é recusado. `state` até 1024 caracteres.
- `finance.read` é sempre incluído; `offline_access` é aceito e ignorado (refresh
  é sempre emitido).
- O pedido validado vira um **handle assinado de 10 minutos** e a pessoa é levada
  a `/oauth/consent?request=…` (tela do SPA, exige login — senha ou Google; o
  Google volta para o consentimento pelo `next` assinado).
- Autorizar/negar devolve o redirect com `code`, `state` e **`iss`** (RFC 9207) —
  ou `error=access_denied`.

## Token

`POST /api/v1/oauth/token` (**`application/x-www-form-urlencoded`**)

| grant | parâmetros |
|---|---|
| `authorization_code` | `code`, `redirect_uri`, `client_id`, `code_verifier`, `resource` |
| `refresh_token` | `refresh_token`, `client_id`, `scope` (opcional, só reduz), `resource` |

- Código: 5 min, **uso único** por `UPDATE` condicional; reutilizar um código
  revoga a concessão inteira.
- Access token opaco `cfm_at_…` (60 min); refresh `cfm_rt_…` (30 dias),
  **rotativo** — cada uso devolve um par novo; reapresentar um refresh já usado
  revoga a concessão (detecção de roubo).
- Só o **SHA-256** dos tokens e códigos vai para o banco.
- Erros no formato RFC 6749 (`invalid_grant`, `invalid_client`,
  `invalid_target`, …), com `Cache-Control: no-store`.

## Revogação

- `POST /api/v1/oauth/revoke` (RFC 7009): sempre 200; revogar um refresh revoga a
  concessão.
- Na tela **Configurações › Integrações com IA › Desconectar**.
- Automaticamente ao **trocar/redefinir a senha** e quando o admin **encerra as
  sessões** da pessoa ou a desativa.
- Conta desativada/excluída perde o acesso na próxima chamada (o usuário é
  recarregado a cada tool call).

## Escopos

| Escopo | Libera |
|---|---|
| `finance.read` (obrigatório) | Todas as leituras e as prévias |
| `transactions.write` | Criar, editar, excluir, restaurar, categorizar e importar lançamentos |
| `accounts.write` | Pagar fatura, transferir entre contas, conciliar saldo |
| `income.write` | Registrar e atualizar rendas |
| `settlements.write` | Registrar e desfazer acertos entre pessoas |
| `planning.write` | Recorrências, metas do mês e categorias |

Toda tool aparece no `tools/list` (lista determinística); sem o escopo, a chamada
falha com `PERMISSION_DENIED`, `required_scopes` e o desafio
`_meta["mcp/www_authenticate"]` (`error="insufficient_scope"`) que o ChatGPT usa
para reabrir a autorização pedindo o escopo que faltou.

**Escopo não é tudo.** A autorização efetiva é escopo ∩ papel no espaço (viewer
não escreve; member só edita o que é seu) ∩ `access_policy` (o que a pessoa
enxerga). Tokens do SPA (JWT de cookie) não valem no `/mcp`, e tokens de agente
não valem nas rotas REST.

## Clientes: callbacks conhecidos

| Cliente | Registro | Redirect |
|---|---|---|
| ChatGPT | DCR/CIMD | `https://chatgpt.com/connector_platform_oauth_redirect` |
| Claude (web/desktop) | CIMD | `https://claude.ai/api/mcp/auth_callback` |
| Claude Code | CIMD (`https://claude.ai/oauth/claude-code-client-metadata`) | loopback, qualquer porta |
| Codex | CIMD/DCR (`--oauth-client-registration auto`) | loopback |
| Gemini CLI, Antigravity | DCR | loopback |
