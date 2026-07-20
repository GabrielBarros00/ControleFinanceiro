# Sessões de refresh persistidas e endurecimento de produção

O refresh era stateless (SEC-004): o logout só limpava cookies, então um refresh token copiado valia os 7 dias inteiros, sem revogação nem rotação. E a app não tinha TrustedHost, CSP nem restrição de `/docs` em produção (SEC-006).

## Decisões

**Sessões de refresh persistidas com rotação e detecção de reuso (SEC-004).** Cada refresh token carrega um `jti` (uma linha em `RefreshSession`) e um `family` (a cadeia de rotações da mesma sessão).
- **Login/registro/OAuth** iniciam uma família nova (`start_session`).
- **Refresh** valida o `jti`, **rotaciona** (revoga o atual, emite o próximo na mesma família) e reemite o cookie.
- **Reuso**: reapresentar um `jti` já rotacionado denuncia roubo → a **família inteira** é revogada (o ladrão e a vítima caem juntos).
- **Logout** revoga a sessão do token — o cookie copiado deixa de valer imediatamente.
- **Legado**: tokens sem `jti` (emitidos antes da migração) são aceitos uma vez e migrados para uma sessão gerenciada — ninguém é deslogado no deploy.

A revogação de família precisa **persistir mesmo quando a requisição falha com 401**, então a rota faz `commit` no ramo de erro (exceção ao "um commit por request" do ADR 0010, justificada pela segurança).

**Endurecimento de produção (SEC-006).**
- `/docs`, `/redoc` e `/openapi.json` ficam **fora do ar** em produção (não expõem o mapa da API nem carregam scripts de CDN).
- `TrustedHostMiddleware` recusa `Host` forjado quando `ALLOWED_HOSTS` é configurado (padrão `*` desliga — o operador restringe).
- Headers: `Permissions-Policy` sempre; `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` só em produção (em dev quebraria o `/docs`).

## Consequências

- Migração `b8e3f105c7a9`: tabela `refreshsession` (jti único, índice de família).
- `revoke_session`/`rotate_session`/`start_session` em `app/services/session_service.py`; `auth.py` usa-os no login/refresh/logout/OAuth.
- Config ganha `ALLOWED_HOSTS`.
