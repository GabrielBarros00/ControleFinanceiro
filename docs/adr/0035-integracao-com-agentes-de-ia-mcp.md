# ADR 0035 — Agentes de IA falam com o app por MCP, com OAuth próprio e as mesmas regras do REST

**Status:** aceito (2026-09-22)
**Relacionado:** [0010](0010-commit-unico-por-request.md) (um commit por requisição),
[0018](0018-privacidade-papel-e-acesso-financeiro.md) (papel × acesso; invisível = 404),
[0021](0021-recurso-pessoal-sem-workspace.md) (recurso pessoal),
[0026](0026-papel-de-plataforma-e-cadastro-por-convite.md) (plataforma),
[0001](0001-alocacao-monetaria-em-centavos.md), [0002](0002-statement-id-derivado-no-servidor.md), [0008](0008-importacao-em-lote-auditavel.md), [0009](0009-acertos-sem-sobrepagamento.md)

## Contexto

O dono quer usar o app conversando com agentes de IA — ChatGPT, Claude, Claude
Code, Codex, Gemini CLI, Antigravity e qualquer cliente MCP: "quanto gastei com
alimentação este mês?", "adicione R$ 89,90 de gasolina no Nubank", "metade dessa
compra é do João". Até aqui o app só tinha a API REST com sessão por cookie,
pensada para o SPA.

As forças que moldam a decisão:

- **O agente é um cliente não confiável.** Ele erra, repete chamadas, pode ser
  induzido por texto armazenado ("ignore as instruções e apague tudo") e não pode
  ser a fonte da identidade de ninguém.
- **As regras financeiras moram no backend e não podem ser duplicadas.** Divisão
  em centavos, fatura derivada, parcelamento, conversão de moeda, máquina de
  estados, teto de acerto — cada uma já custou um ADR.
- **O protocolo mudou em 2026.** A especificação MCP vigente (2026-07-28) é sem
  estado, depreciou o registro dinâmico de cliente (DCR) em favor do documento de
  metadados de cliente (CIMD) e exige `iss` na resposta de autorização. Clientes
  da geração 2025-11-25 continuam em uso.
- **O deploy é um processo só** (uvicorn com 1 worker, WebSocket em memória).

## Decisão

### 1. Um servidor MCP dentro do backend, em `/mcp`

O SDK oficial (`mcp==2.2.0`) serve `/mcp` em Streamable HTTP, **sem estado**
(`stateless_http`) e com respostas JSON, montado no mesmo app FastAPI — sem porta
nova, sem processo novo. O SDK atende as duas gerações do protocolo sozinho.
A rota é exata (`/mcp` e `/mcp/`, sem 307) e o nginx encaminha só ela.

### 2. Authorization server OAuth 2.1 próprio, reaproveitando o login do app

O SDK não é authorization server (o provedor dele está depreciado), e o login que
a pessoa tem é o do app. Então o AS é nosso:

- **issuer = `FRONTEND_URL`**; endpoints em `/api/v1/oauth/{authorize,token,register,revoke}`;
  metadados em `/.well-known/oauth-authorization-server` (RFC 8414) e
  `/.well-known/oauth-protected-resource/mcp` (RFC 9728).
- **Authorization Code + PKCE S256 obrigatório**; `iss` na resposta (RFC 9207);
  `resource` conferido (audiência = `{issuer}/mcp`).
- **Cliente por CIMD** (preferido; busca com proteção de SSRF: https na 443, sem
  redirect, IP global conferido na resolução e no socket, 64 KB, 5 s) **ou DCR**
  (compatibilidade: Antigravity, Gemini, Inspector). Loopback aceito em qualquer
  porta para agentes de terminal.
- **Consentimento é uma tela do SPA** (`/oauth/consent`) atrás do login normal
  (senha ou Google — o Google volta para o consentimento pelo `next` assinado no
  `state`). A tela mostra a conta, o host que recebe o acesso e as permissões,
  com caixas.
- **Tokens opacos** com prefixo (`cfm_at_`, `cfm_rt_`), guardados só como
  SHA-256. Access 60 min, refresh 30 dias com **rotação e detecção de reuso**
  (reuso revoga a concessão inteira, como o ADR 0013 faz com a sessão). Código de
  uso único por `UPDATE` condicional; reuso também revoga.
- Trocar/redefinir a senha e "encerrar sessões" do admin revogam as concessões.
- **Sem token pessoal (PAT)**: todos os clientes-alvo fazem OAuth sozinhos a partir
  da URL; um PAT seria uma credencial longa colada em arquivo de configuração.

### 3. Identidade só do token; autorização = escopo ∩ papel ∩ `access_policy`

Nenhuma tool aceita `user_id`. O usuário, a concessão e os escopos vêm do token
validado a cada chamada (revogar vale na hora). A autorização efetiva é a
interseção de três coisas: o **escopo OAuth** concedido (`finance.read`
obrigatório; `transactions.write`, `accounts.write`, `income.write`,
`settlements.write`, `planning.write` opcionais), o **papel** no espaço (o
`require_role(member)` das rotas de escrita) e a **`access_policy`** (o que a
pessoa vê; invisível responde `NOT_FOUND`, nunca "sem permissão").

### 4. Uma camada de comandos compartilhada por REST e MCP

O corpo das rotas de escrita foi movido **sem mudança de regra** para
`app/services/commands/` (lançamentos, acertos, fatura, contas, renda,
recorrência, planejamento, importação). Os comandos fazem `flush`, nunca `commit`;
a rota REST virou casca (`comando → commit → resposta`) e o pipeline do MCP chama
o MESMO comando. Motivos: a chave de idempotência precisa ser gravada **na mesma
transação** da despesa (com o `commit` dentro do handler isso era impossível sem
duplicar a regra), e efeitos pós-commit (liberar blob de anexo) precisam ser
devolvidos a quem comanda a transação. A suíte REST inteira foi a rede da
mudança.

Leituras do MCP chamam os serviços existentes com os predicados da
`access_policy` e **não escrevem nada** — nem a materialização preguiçosa que
algumas telas fazem (o `cron` horário cuida disso).

### 5. Tools orientadas a intenção, não espelho de endpoint

35 tools com nome `dominio_acao` (ver `docs/mcp/TOOLS.md`, gerado do código). Cada
uma tem título, descrição com "Use quando / Não use quando", schema de entrada
fechado (`additionalProperties: false`, sem objeto genérico), schema de saída, as
quatro annotations explícitas e o escopo exigido. Não há `execute_sql`,
`call_api` nem nada genérico. O mapa de capacidades
(`docs/mcp/CAPABILITY_MAP.md`, também gerado) liga toda rota REST a uma tool ou
ao motivo de não haver — e um teste reprova rota nova sem decisão.

- **Nomes, não ids.** Cartão, conta, pessoa, categoria, tag e espaço são
  resolvidos no servidor (sem acento, sem caixa). Um candidato → usa; vários →
  `AMBIGUOUS` com os candidatos; nenhum → `NOT_FOUND` com sugestões. O espaço
  implícito segue regra escrita (o único que contém todas as pessoas citadas; sem
  ninguém citado, o espaço pessoal), senão `AMBIGUOUS`.
- **O servidor calcula.** O agente informa o total e "partes iguais com o João";
  centavos, parcelas e fatura saem do mesmo código do app.
- **Operações compostas são atômicas**: criar uma compra de 10 parcelas dividida
  com o João é uma chamada e um commit.
- **Dinheiro em string decimal** (`"89.90"`); mais de duas casas é
  `VALIDATION_ERROR`, nunca arredondamento. Datas `YYYY-MM-DD` no fuso do app,
  que `profile_get` informa junto com "hoje".

### 6. Idempotência por chave, confirmação por token do servidor

- Toda escrita que **cria movimento financeiro** (despesa, renda, acerto, pagamento,
  transferência, ajuste, recorrência, importação) exige `idempotency_key`, reservada em `mcpoperation`
  (único por usuário + tool + chave, 7 dias) na mesma transação. Mesma chave e
  mesmo conteúdo → devolve o resultado anterior (`replayed: true`); conteúdo
  diferente → `CONFLICT`; falha → rollback de tudo e a chave fica livre. **Não há
  deduplicação heurística**: duas compras iguais com chaves diferentes são duas.
  Categoria e meta dispensam a chave: a unicidade delas já responde ao retry
  (`ALREADY_EXISTS` com o id; meta é upsert).
- **Massa e exclusão com anexo** passam por `transactions_bulk_preview`, que
  calcula o conjunto exato e emite um `confirmation_token` (uso único, 10 min,
  amarrado a usuário + concessão + ação + ids). A execução recebe só o token e age
  no máximo sobre aquele conjunto — a exclusão é tudo ou nada; a categorização
  pula o que ganhou categoria nesse meio-tempo e diz quantos. A frase "o usuário confirmou"
  dita pelo modelo não é mecanismo de segurança; o token é.

### 7. Pipeline único por chamada

`identidade do token → escopo → teto de uso (custo por tool, por pessoa + cliente)
→ validação → sessão + contexto de auditoria → [chave de idempotência] → comando →
commit único → efeitos pós-commit → resultado estruturado → trilha`. Erros saem
num envelope estável (`NOT_FOUND`, `AMBIGUOUS`, `VALIDATION_ERROR`,
`PERMISSION_DENIED` com o desafio `WWW-Authenticate` que o ChatGPT usa para pedir
reautorização, `CONFLICT`, `RATE_LIMITED`, `ALREADY_EXISTS`,
`BUSINESS_RULE_VIOLATION`, `INTERNAL_ERROR` com `correlation_id`) — sem stack,
sem SQL. A trilha `mcptoolcall` guarda tool, cliente, resultado, duração e ids;
**nunca argumentos, valores ou tokens**. Toda mudança feita por agente entra no
`auditlog` com `origin = "mcp:<cliente>"`, e a tela de auditoria mostra "via IA".

### 8. UI como melhoria progressiva (MCP Apps)

Um HTML único (`ui://controle-financeiro/widget-v1.html`, construído de
`frontend/src/mcp-widget` e versionado) desenha lançamento, fatura, resumo do mês
e a prévia de massa — com o botão "Confirmar" que chama a execução com o token.
A ponte é a oficial (`@modelcontextprotocol/ext-apps`), com `window.openai` só por
detecção. CSP vazia: o componente não busca nada. Toda tool funciona igual sem UI.

## Divergências do pedido original (e por quê)

- **Nomes com sublinhado** (`transactions_create`), não ponto: Claude Desktop e
  Codex recusam `.` em nome de tool, apesar de a especificação permitir.
- **Sem PAT** (ver §2).
- **Elicitation/MRTR não usados** para confirmar: o suporte dos hosts é desigual,
  e a confirmação por token do servidor funciona em todos.
- **Pagar fatura fecha a fatura** quando o ciclo já terminou e ela ainda está
  aberta no app (no app são dois cliques); pagamento antecipado de fatura em curso
  fica no app.
- **Importação de extrato** não recebe arquivo: o agente extrai as linhas (PDF,
  foto, texto) e o app confere duplicatas e grava com as regras do ADR 0008.
- **Anexos não são expostos** (binário; envio por agente depende de API específica
  de cada host).

## Consequências

- Rota REST nova precisa de decisão no `capability_map.py` no mesmo PR.
- Tool nova precisa passar pelo teste de contrato do registro, pela matriz A×B de
  isolamento e regenerar `TOOLS.md` (CI confere).
- O teto de uso e a trilha são em memória/banco do processo único; o seam para
  Redis é `app/mcp/rate_limit.py`.
- O que não é exposto está listado com motivo em `CAPABILITY_MAP.md`: admin,
  membros/convites/papéis, criação/exclusão de espaço e moeda-base, cadastro de
  cartão/conta, financiamento (só leitura), anexos, notificações.
