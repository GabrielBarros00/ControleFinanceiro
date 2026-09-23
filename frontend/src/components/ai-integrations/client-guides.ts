/**
 * Guias de conexão por cliente de IA.
 *
 * Tudo aqui foi conferido na documentação OFICIAL de cada produto em
 * VERIFICADO_EM, com o link ao lado — menus e planos desses produtos mudam com
 * frequência, e a tela diz a data para a pessoa saber quando desconfiar.
 *
 * Nenhum comando leva token: todos os clientes daqui fazem OAuth sozinhos a
 * partir da URL (descobrem o authorization server pelo 401 do /mcp). Por isso
 * não existe "token pessoal" nesta tela — e o `--trust` do Gemini CLI, que
 * pularia a confirmação das ferramentas, não é sugerido.
 */

export const VERIFICADO_EM = '22/09/2026';

/** Nome do servidor nos comandos — o mesmo em todos os clientes. */
export const NOME_DO_SERVIDOR = 'controle-financeiro';

export interface CommandBlock {
  label: string;
  /** Texto exato a copiar. */
  code: string;
  language: 'bash' | 'json' | 'text';
}

export interface ClientGuide {
  id: string;
  name: string;
  /** Uma linha: onde funciona e o que precisa. */
  requirements: string;
  steps: string[];
  commands: CommandBlock[];
  auth: string;
  docsUrl: string;
  docsLabel: string;
  /** Aviso de plano/disponibilidade, quando existe. */
  warning?: string;
  /** Cliente que ainda não dá para usar daqui (ex.: região). */
  unavailable?: boolean;
}

export function clientGuides(mcpUrl: string): ClientGuide[] {
  return [
    {
      id: 'chatgpt',
      name: 'ChatGPT',
      requirements: 'ChatGPT na web, com o Modo desenvolvedor ligado.',
      steps: [
        'No ChatGPT (web), abra Configurações › Segurança e login e ative "Modo desenvolvedor" (Developer mode).',
        'Vá em ChatGPT Plugins e toque no botão "+" para criar um app de modo desenvolvedor.',
        'Dê um nome (ex.: Controle Financeiro) e, em Conexão, escolha endpoint público e cole a URL abaixo.',
        'Crie a conexão. O ChatGPT abre esta tela do app para você entrar e autorizar o acesso.',
        'Numa conversa, habilite o app. Ações de escrita pedem sua confirmação antes de rodar.',
      ],
      commands: [{ label: 'URL do servidor', code: mcpUrl, language: 'text' }],
      auth: 'OAuth: o ChatGPT se registra sozinho e você autoriza nesta tela do app, escolhendo as permissões.',
      docsUrl: 'https://developers.openai.com/plugins/deploy/connect-chatgpt',
      docsLabel: 'OpenAI — Conectar do ChatGPT',
      warning: 'Modo desenvolvedor: planos Plus, Pro, Business, Enterprise e Education, na web.',
    },
    {
      id: 'claude',
      name: 'Claude',
      requirements: 'Claude na web ou no app de desktop.',
      steps: [
        'No Claude, abra Customize › Connectors.',
        'Toque em "+" e em "Add custom connector".',
        'Cole a URL abaixo e toque em "Add" (não é preciso preencher "Advanced settings").',
        'Ao conectar, o Claude abre esta tela do app para você entrar e autorizar.',
        'Numa conversa, use o "+" › Connectors para ligar o conector.',
      ],
      commands: [{ label: 'URL do servidor', code: mcpUrl, language: 'text' }],
      auth: 'OAuth automático (o Claude se identifica pelo próprio documento de metadados de cliente).',
      docsUrl: 'https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp',
      docsLabel: 'Claude — Custom connectors',
      warning:
        'Disponível nos planos Free (1 conector personalizado), Pro, Max, Team e Enterprise. Em Team/Enterprise, quem adiciona é o Owner da organização.',
    },
    {
      id: 'claude-code',
      name: 'Claude Code',
      requirements: 'Claude Code instalado no computador.',
      steps: [
        'Rode o comando abaixo no terminal (vale para todos os seus projetos).',
        'Dentro do Claude Code, rode /mcp e escolha o servidor para autenticar — o navegador abre esta tela do app.',
        'Ou autentique pelo terminal com o segundo comando.',
      ],
      commands: [
        {
          label: 'Adicionar',
          code: `claude mcp add --transport http ${NOME_DO_SERVIDOR} --scope user ${mcpUrl}`,
          language: 'bash',
        },
        { label: 'Autenticar (opcional)', code: `claude mcp login ${NOME_DO_SERVIDOR}`, language: 'bash' },
      ],
      auth: 'OAuth pelo navegador; o Claude Code guarda e renova o token sozinho.',
      docsUrl: 'https://code.claude.com/docs/en/mcp',
      docsLabel: 'Claude Code — MCP',
    },
    {
      id: 'codex',
      name: 'Codex',
      requirements: 'Codex CLI instalado no computador.',
      steps: [
        'Rode o primeiro comando para registrar o servidor.',
        'Rode o segundo para autenticar — o navegador abre esta tela do app para você autorizar.',
      ],
      commands: [
        { label: 'Adicionar', code: `codex mcp add ${NOME_DO_SERVIDOR} --url ${mcpUrl}`, language: 'bash' },
        { label: 'Autenticar', code: `codex mcp login ${NOME_DO_SERVIDOR}`, language: 'bash' },
      ],
      auth: 'OAuth (`codex mcp login`); o registro do cliente é automático.',
      docsUrl: 'https://learn.chatgpt.com/docs/extend/mcp?surface=cli',
      docsLabel: 'Codex — MCP',
    },
    {
      id: 'gemini-cli',
      name: 'Gemini CLI',
      requirements: 'Gemini CLI instalado no computador.',
      steps: [
        'Rode o comando abaixo para registrar o servidor para o seu usuário.',
        'No Gemini CLI, rode o comando de autenticação — o navegador abre esta tela do app.',
        'Deixe o Gemini CLI perguntando antes de cada ação: não use a opção --trust, que pula essas confirmações.',
      ],
      commands: [
        {
          label: 'Adicionar',
          code: `gemini mcp add --transport http --scope user ${NOME_DO_SERVIDOR} ${mcpUrl}`,
          language: 'bash',
        },
        { label: 'Autenticar (dentro do Gemini CLI)', code: `/mcp auth ${NOME_DO_SERVIDOR}`, language: 'text' },
      ],
      auth: 'OAuth com registro dinâmico de cliente, feito pelo próprio Gemini CLI.',
      docsUrl: 'https://geminicli.com/docs/tools/mcp-server/',
      docsLabel: 'Gemini CLI — MCP servers',
    },
    {
      id: 'antigravity',
      name: 'Antigravity',
      requirements: 'Google Antigravity (IDE).',
      steps: [
        'No painel do agente, toque em "…" › MCP Servers › Manage MCP Servers › View raw config.',
        'Acrescente o bloco abaixo dentro de "mcpServers" e salve (arquivo global: ~/.gemini/config/mcp_config.json).',
        'O Antigravity faz o OAuth sozinho e abre esta tela do app para você autorizar. No terminal do Antigravity, /mcp abre o gerenciador.',
      ],
      commands: [
        {
          label: 'mcp_config.json',
          code: JSON.stringify({ mcpServers: { [NOME_DO_SERVIDOR]: { serverUrl: mcpUrl } } }, null, 2),
          language: 'json',
        },
      ],
      auth: 'OAuth com registro dinâmico de cliente (sem configurar credencial).',
      docsUrl: 'https://antigravity.google/docs/mcp/',
      docsLabel: 'Antigravity — MCP',
    },
    {
      id: 'generic',
      name: 'Outro cliente MCP',
      requirements: 'Qualquer cliente com MCP remoto (Streamable HTTP) e OAuth 2.1.',
      steps: [
        'Cadastre um servidor MCP remoto do tipo HTTP (Streamable HTTP) com a URL abaixo.',
        'O cliente descobre a autorização sozinho: o /mcp responde 401 com o endereço dos metadados OAuth.',
        'Autorize nesta tela do app, escolhendo as permissões.',
      ],
      commands: [{ label: 'URL do servidor', code: mcpUrl, language: 'text' }],
      auth: 'OAuth 2.1 com PKCE (S256). Registro por documento de metadados (CIMD) ou dinâmico (DCR).',
      docsUrl: 'https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index.md',
      docsLabel: 'Especificação MCP — Autorização',
    },
    {
      id: 'gemini-web',
      name: 'Gemini (web)',
      requirements: 'Apps personalizados do Gemini: só nos EUA, maiores de 18 anos, conta Google pessoal e em inglês.',
      steps: [
        'Hoje o recurso não está disponível no Brasil. Onde estiver: gemini.google.com › Settings › Connected Apps › Custom apps.',
        'Para usar o Gemini com este app agora, use o Gemini CLI ou o Antigravity.',
      ],
      commands: [],
      auth: 'OAuth com registro dinâmico de cliente.',
      docsUrl: 'https://support.google.com/gemini/answer/17209137?hl=en',
      docsLabel: 'Gemini — Custom apps',
      unavailable: true,
    },
  ];
}

/**
 * O "perfil de conexão": o que um cliente genérico precisa saber, em JSON.
 * Sem token nenhum — a autenticação é por OAuth, a partir da própria URL.
 */
export function connectionProfile(args: {
  mcpUrl: string;
  serverName: string;
  serverVersion: string;
  scopes: string[];
}) {
  const origem = new URL(args.mcpUrl).origin;
  return JSON.stringify(
    {
      name: NOME_DO_SERVIDOR,
      server: args.serverName,
      version: args.serverVersion,
      transport: 'streamable-http',
      url: args.mcpUrl,
      authentication: {
        type: 'oauth2',
        protected_resource_metadata: `${origem}/.well-known/oauth-protected-resource/mcp`,
        authorization_server_metadata: `${origem}/.well-known/oauth-authorization-server`,
        pkce: 'S256',
        scopes: args.scopes,
      },
    },
    null,
    2,
  );
}
