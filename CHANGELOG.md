# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
segue [SemVer](https://semver.org/lang/pt-BR/).

## [4.0.0] — 2026-07-20

Primeira versão pública. Base completa da aplicação.

### Adicionado
- Workspaces com papéis (owner/admin/member/viewer) e convites por e-mail e por link.
- Despesas com divisão (igual/porcentagem/valor fixo) e **divisão por item** (quantidade × valor unitário).
- Ajustes de total (desconto, imposto, gorjeta, frete, cashback, arredondamento).
- Origem do pagamento por pagador (método + conta/carteira); múltiplos pagadores.
- Dívidas consolidadas e acertos validados (sem sobrepagamento).
- Cartões de crédito com ciclo de fatura (aberta→fechada→paga + reabertura), total congelado, limite comprometido e parcelamento coeso.
- Recorrências (diária/semanal/mensal/anual) com materialização completa e escopos de edição.
- Financiamentos SAC/PRICE por mês de calendário, com quitação antecipada simulada.
- Importação de CSV em lote, com decisão por linha e idempotência.
- Renda, orçamento por categoria e previsão de fim de mês.
- Atualização em tempo real por WebSocket, com sequência de integridade e resync.
- Autenticação por cookie HttpOnly com rotação de refresh e detecção de reuso, Google OAuth e reset de senha.
- Trilha de auditoria por workspace; hardening de produção (CSRF, rate limit, TrustedHost, CSP).
- Deploy via Docker Compose (nginx + backend + Postgres) e migrações Alembic.

### Integridade financeira
- Alocação monetária em centavos (sem parcela negativa; soma exata).
- Política única de status/moeda para todas as agregações.
- Atomicidade por requisição (um único commit).
- Fatura derivada no servidor; máquina de estados da despesa.

Decisões documentadas em [docs/adr/](docs/adr/README.md).
