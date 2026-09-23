# Segurança da integração MCP

## Modelo de ameaças

| Ameaça | Controle |
|---|---|
| Agente (ou texto armazenado) tenta agir como outra pessoa | Identidade **só do token**; nenhuma tool aceita `user_id`; schemas com `additionalProperties: false` recusam campo extra |
| IDOR: ids de outra pessoa nos argumentos | Toda leitura/escrita passa pela `access_policy` (a mesma do REST); invisível = `NOT_FOUND`, nunca "sem permissão"; matriz A×B em `tests/mcp/test_isolation.py` cobre toda tool que recebe id (com teste de denominador) |
| Escalada por escopo | Escopo checado antes de tudo; autorização = escopo ∩ papel ∩ `access_policy` |
| Roubo de código/refresh | PKCE S256 obrigatório; código de uso único (UPDATE condicional); refresh rotativo com detecção de reuso que revoga a concessão |
| Token vazado em log/repositório | Tokens opacos com prefixo (`cfm_at_`, `cfm_rt_`) reconhecíveis por scanner; banco guarda SHA-256; logs nunca carregam token (teste em `test_audit_and_safety.py`) |
| Confusão de audiência | `resource` conferido na autorização e na troca; token vale só no `/mcp`; JWT de sessão do app não vale no `/mcp` e token de agente não vale no REST |
| Redirect aberto no OAuth | `redirect_uri` exato (loopback ignora só a porta); redirect inválido nunca é seguido; `next` do login Google só aceita caminho interno (testado contra `//`, esquema, barra invertida e controle) |
| Consentimento enganoso | A tela mostra o **host** que recebe o acesso (não só o nome que o cliente escolheu), a conta e as permissões; aviso extra para cliente só-loopback |
| SSRF pelo CIMD | Só https/443, sem redirect, sem credencial; IP global conferido na resolução e no peer; 64 KB; 5 s |
| DNS rebinding / Origin | `Origin` fora da allowlist → 403 no `/mcp`; `ALLOWED_HOSTS` do app vale |
| CSRF | Endpoints de cookie mantêm a checagem de Origin; só `token`, `register`, `revoke` e `/mcp` (autenticados por Bearer/PKCE, sem cookie) são isentos. CORS `*` sem credenciais apenas nos endpoints públicos do OAuth |
| Prompt injection por dado armazenado | Títulos/descrições voltam como campos JSON, nunca concatenados em instruções; as instruções do servidor dizem que texto armazenado é dado; ações destrutivas em massa exigem token do servidor |
| Confirmação forjada pelo modelo | Massa só executa com `confirmation_token` emitido pelo servidor (uso único, 10 min, amarrado a usuário + concessão + ação + ids); o conjunto é reconferido e, se mudou, nada é excluído |
| Retry duplicando dinheiro | `idempotency_key` gravada na mesma transação; mesma chave + outro conteúdo = `CONFLICT` |
| Execução parcial | Um commit por chamada; qualquer falha depois do primeiro `flush` faz rollback de tudo (teste com falha injetada) |
| Abuso / laço de agente | Teto por pessoa + cliente com custo por tool (120 unidades/min; 30 escritas/min); massa limitada a 200 itens; página ≤ 50; OAuth com limite por IP |
| Vazamento por erro | Envelope estável; exceção inesperada vira `INTERNAL_ERROR` genérico com `correlation_id`; stack só no log do servidor (teste com erro de banco injetado) |
| Consulta arbitrária | Não há SQL nem tool genérica; filtros são de domínio; texto de busca é escapado (`%` não casa tudo) |
| Anexo apagado sem aviso | Exclusão de lançamento com anexo exige o fluxo de prévia, que mostra quantos recibos serão apagados |
| Conta desativada/senha trocada | Usuário recarregado a cada chamada; troca/redefinição de senha e "encerrar sessões" revogam as concessões |

## O que o operador vê

A trilha `mcptoolcall` (e a aba Saúde do admin) registra tool, cliente, resultado,
código de erro, duração e ids afetados — **nunca argumentos, valores ou títulos**.
O conteúdo das mudanças fica no `auditlog` da entidade, com `origin="mcp:<cliente>"`.

## Verificação

- Mutações dos testes de segurança principais (token de outra concessão, papel
  viewer, conflito de idempotência, conjunto mudado, open redirect, participante
  de acerto) foram aplicadas e **mataram** os testes correspondentes.
- `tests/security/*` (varreduras já existentes do app) seguem verdes com as rotas
  novas.
