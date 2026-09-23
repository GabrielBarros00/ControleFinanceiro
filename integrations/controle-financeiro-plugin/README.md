# Pacote de plugin — Controle Financeiro

Pacote no formato **Agent Plugins** (o mesmo para ChatGPT e Codex), conferido em
<https://developers.openai.com/plugins/build/plugins> em 22/09/2026.

```
controle-financeiro-plugin/
├── plugin.json      identidade + apresentação (extensions.com.openai.interface)
├── mcp.json         o servidor MCP (streamable-http) de produção
├── skills/          fluxos de várias etapas que as descrições das tools não cobrem
│   ├── revisar-fatura/SKILL.md
│   ├── fechamento-do-mes/SKILL.md
│   └── conciliar-extrato/SKILL.md
└── assets/          logo e ícone (os do PWA)
```

**Nada aqui foi publicado.** Publicar é decisão do dono do app. Antes de submeter:

1. Publicar a política de privacidade e os termos (modelos em
   `docs/mcp/legal/`) e acrescentar `privacyPolicyURL` e `termsOfServiceURL` em
   `extensions.com.openai.interface` — ficaram de fora de propósito, para não
   apontar para páginas que ainda não existem.
2. Conferir a URL de `mcp.json` (produção: `https://financas.capamericagod.com/mcp`).
3. Verificação de domínio: definir `OPENAI_APPS_CHALLENGE_TOKEN` no `.env` do
   servidor com o valor que o painel da OpenAI fornecer; o app responde em
   `/.well-known/openai-apps-challenge`.
4. Seguir o checklist de `docs/mcp/OPENAI_APP.md`.

## Por que só três skills

Skill é para o que precisa de várias chamadas em ordem e de julgamento no meio.
Registrar uma compra — mesmo parcelada e dividida — é uma chamada só
(`transactions_create`), e as descrições das tools já dizem como; uma skill ali
seria uma segunda fonte de instrução para divergir da primeira.
