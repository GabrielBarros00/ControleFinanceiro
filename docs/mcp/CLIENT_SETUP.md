# Conectando cada cliente

Passos conferidos na documentação oficial de cada produto em **22/09/2026**;
Claude Code, Codex e Gemini CLI testados na prática em **23/09/2026** (ver
[TESTING.md](TESTING.md#agentes-de-terminal-de-verdade-manual)).
Menus e planos mudam com frequência: o link oficial vale mais que esta página, e a
tela **Configurações › Integrações com IA** do app mostra os mesmos guias com a URL
da conta já preenchida.

URL do servidor: `https://<seu-site>/mcp` (em produção,
`https://financas.capamericagod.com/mcp`). Nenhum passo pede token ou senha: todos
os clientes abaixo fazem OAuth sozinhos e abrem a tela de consentimento do app.

## ChatGPT

Requisito: Modo desenvolvedor — planos **Plus, Pro, Business, Enterprise e
Education, na web**.

1. Configurações › **Segurança e login** › ative **Developer mode**.
2. **ChatGPT Plugins** › botão **+** › crie um app de modo desenvolvedor.
3. Dê nome e descrição; em **Conexão**, escolha endpoint público e cole a URL.
4. Crie a conexão; o ChatGPT abre o consentimento do app.
5. Após mudar tools no servidor: abra a conexão e use **Refresh**.

Ações que não são `readOnlyHint` pedem confirmação no ChatGPT antes de rodar.
Docs: <https://developers.openai.com/plugins/deploy/connect-chatgpt> ·
<https://developers.openai.com/api/docs/guides/developer-mode>

## Claude (web e desktop)

Requisito: planos Free (1 conector personalizado), Pro, Max, Team e Enterprise.
Em Team/Enterprise, o Owner adiciona em **Organization settings › Connectors**.

1. **Customize › Connectors** › **+** › **Add custom connector**.
2. Cole a URL e **Add** (não é preciso preencher Advanced settings — o Claude se
   identifica por CIMD).
3. Numa conversa: **+** › **Connectors** › ligue o conector.

Docs: <https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp>

## Claude Code

```bash
claude mcp add --transport http controle-financeiro --scope user https://<seu-site>/mcp
```

Depois, dentro do Claude Code, `/mcp` e escolha o servidor para autenticar — ou
`claude mcp login controle-financeiro` no terminal (`--no-browser` em máquina sem
navegador).

Docs: <https://code.claude.com/docs/en/mcp>

## Codex

```bash
codex mcp add controle-financeiro --url https://<seu-site>/mcp
codex mcp login controle-financeiro
```

`codex mcp login` aceita `--scopes` e `--oauth-client-registration auto|cimd|dcr`.

Docs: <https://learn.chatgpt.com/docs/extend/mcp?surface=cli>

## Gemini CLI

```bash
gemini mcp add --transport http --scope user controle-financeiro https://<seu-site>/mcp
```

Dentro do Gemini CLI: `/mcp auth controle-financeiro`. **Não use `--trust`**: ele
pula a confirmação de TODAS as tools do servidor.

> **Conta Google pessoal (plano gratuito) não funciona mais.** Em 23/09/2026 o Google
> recusa esse login no Gemini CLI: *"This client is no longer supported for Gemini Code
> Assist for individuals… please migrate to the Antigravity suite"*. O Gemini CLI
> segue funcionando com chave da API do Gemini (`GEMINI_API_KEY`) ou com Vertex AI.
> Para conta pessoal, use o **Antigravity** (abaixo). Conferido na prática: o servidor
> aparece como *Connected* no `gemini mcp list`, com as tools listadas.

Docs: <https://geminicli.com/docs/tools/mcp-server/>

## Antigravity

No painel do agente: **…** › **MCP Servers** › **Manage MCP Servers** › **View raw
config** (arquivo global `~/.gemini/config/mcp_config.json`; por workspace
`.agents/mcp_config.json`). Acrescente:

```json
{
  "mcpServers": {
    "controle-financeiro": { "serverUrl": "https://<seu-site>/mcp" }
  }
}
```

O Antigravity faz o OAuth sozinho (registro dinâmico). No terminal, `/mcp` abre o
gerenciador.

Docs: <https://antigravity.google/docs/mcp/>

## Gemini (web)

"Custom apps" do Gemini web existe hoje **só nos EUA**, para maiores de 18 anos,
conta Google pessoal e em inglês (Settings › Connected Apps › Custom apps). Para
o público do app (Brasil), use o Gemini CLI ou o Antigravity. Gemini Enterprise
tem conector MCP próprio, configurado pelo administrador da organização.

Docs: <https://support.google.com/gemini/answer/17209137?hl=en>

## Qualquer cliente MCP

- Transporte: Streamable HTTP em `https://<seu-site>/mcp` (protocolo 2026-07-28;
  2025-11-25 também atendido).
- Autorização: OAuth 2.1 com PKCE S256; descoberta pelo 401 do `/mcp`; registro
  por CIMD ou DCR. Detalhes em [AUTHENTICATION.md](AUTHENTICATION.md).

## Anexar arquivos pelo terminal

Nos agentes que rodam comandos no seu computador (Claude Code, Codex, Gemini
CLI), dá para pedir *"anexe o recibo.pdf dos Downloads à compra do
mercado"*. O agente chama `attachments_upload_link`, que devolve um comando `curl`
pronto, e roda esse comando. O arquivo vai do disco direto para o app, sem passar
pela conversa.

- O link vale **uma vez**, por **10 minutos**, e só para aquele lançamento. Precisa da
  permissão *registrar lançamentos* (`transactions.write`) na conexão.
- Valem as regras da tela: JPG, PNG, WebP ou PDF, o tamanho máximo e a cota do espaço.
- O agente pede sua permissão para rodar o `curl`, como faz com qualquer comando.
- No **PowerShell do Windows**, `curl` é outro comando; o certo é `curl.exe`. O Codex
  percebeu isso sozinho no teste.
- No **Codex**, o sandbox padrão não tem rede. Para o `curl` chegar ao app, aprove o
  comando quando ele pedir ou rode com a rede do sandbox liberada.
- No **ChatGPT e no Claude na web** não há terminal: o anexo continua pela tela do
  lançamento no app.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| O cliente não abre o login | Proxy/WAF bloqueando `/.well-known/*` ou `/api/v1/oauth/*` (ver OPERATIONS.md) |
| "invalid_target" na troca | `resource` diferente de `https://<site>/mcp` (site atrás de outro domínio) |
| Ferramentas antigas no ChatGPT | Falta **Refresh** na conexão |
| `PERMISSION_DENIED` numa escrita | A conexão foi autorizada sem aquele escopo: reconecte marcando a permissão |
| 401 depois de um tempo | Refresh expirado (30 dias) ou senha trocada: reconecte |
| "Link de envio inválido ou expirado" no `curl` | O link já foi usado ou passou dos 10 minutos: peça ao agente um novo |
| `curl` do PowerShell pede "Uri" ou falha no `-F` | É o `Invoke-WebRequest`: use `curl.exe` |
