# Política de Segurança

## Reportando uma vulnerabilidade

Se encontrar uma vulnerabilidade, **não abra uma issue pública**. Reporte de forma privada usando o recurso **"Report a vulnerability"** (Security Advisories) do GitHub neste repositório, ou por e-mail ao mantenedor.

Inclua: descrição, passos para reproduzir, impacto potencial e, se possível, uma sugestão de correção. O objetivo de resposta é reconhecer o recebimento em poucos dias úteis e coordenar uma correção antes de qualquer divulgação pública.

## Modelo de segurança (resumo)

O projeto adota, por design:

- **Sessão em cookies HttpOnly** (access + refresh); o frontend nunca acessa os tokens.
- **Refresh com rotação e detecção de reuso** — reapresentar um token rotacionado revoga toda a família de sessões (ADR 0013).
- **RBAC** por papel (`viewer < member < admin < owner`); o backend é sempre a autoridade.
- **Isolamento multi-tenant** por `workspace_id` em todas as consultas; IDs aninhados são validados (anti-IDOR).
- **CSRF** por validação de `Origin`/`Referer` em métodos mutantes, além de cookies `SameSite=Lax`.
- **Rate limiting** em endpoints de autenticação.
- **Hardening**: `TrustedHost`, CSP e `X-Frame-Options`/`Permissions-Policy`; `/docs` desligado em produção.
- **Validação de boot**: em `APP_ENV=production` o backend **recusa subir** com `SECRET_KEY` fraca, `COOKIE_SECURE=False` ou banco não-Postgres.
- **Uploads**: whitelist de tipo + verificação de *magic bytes* + limite de tamanho + hash SHA-256.
- **Auditoria**: trilha por workspace; o hash de senha nunca é registrado.

## Boas práticas ao operar

- Gere `SECRET_KEY` e `POSTGRES_PASSWORD` fortes e **nunca** commite um `.env` (ver [SETUP.md](SETUP.md)).
- Sirva sob **HTTPS** em produção (`APP_ENV=production` + `COOKIE_SECURE=True`).
- Restrinja `ALLOWED_HOSTS` aos domínios reais.
- Faça **backup** periódico do volume do Postgres.
