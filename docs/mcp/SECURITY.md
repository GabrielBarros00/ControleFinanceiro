# Segurança da integração MCP

## Modelo de ameaças

| Ameaça | Controle |
|---|---|
| Agente (ou texto armazenado) tenta agir como outra pessoa | Identidade **só do token**; nenhuma tool aceita `user_id`; schemas com `additionalProperties: false` recusam campo extra |
| IDOR: ids de outra pessoa nos argumentos | Toda leitura/escrita passa pela `access_policy` (a mesma do REST); invisível = `NOT_FOUND`, nunca "sem permissão"; matriz A×B em `tests/mcp/test_isolation.py` cobre toda tool que recebe id (com teste de denominador) |
| Escalada por escopo | Escopo checado antes de tudo; autorização = escopo ∩ papel ∩ `access_policy` |
| Roubo de código/refresh | PKCE S256 obrigatório; código de uso único (UPDATE condicional); refresh rotativo com detecção de reuso que revoga a concessão |
| Token vazado em log/repositório | Tokens opacos com prefixo (`cfm_at_`, `cfm_rt_`, `cfm_up_`) reconhecíveis por scanner; banco guarda SHA-256; logs nunca carregam token (teste em `test_audit_and_safety.py`) |
| Confusão de audiência | `resource` conferido na autorização e na troca; token vale só no `/mcp`; JWT de sessão do app não vale no `/mcp` e token de agente não vale no REST |
| Redirect aberto no OAuth | `redirect_uri` exato (loopback ignora só a porta); redirect inválido nunca é seguido; `next` do login Google só aceita caminho interno (testado contra `//`, esquema, barra invertida e controle) |
| Consentimento enganoso | A tela mostra o **host** que recebe o acesso (não só o nome que o cliente escolheu), a conta e as permissões; aviso extra para cliente só-loopback |
| SSRF pelo CIMD | Só https/443, sem redirect, sem credencial; nome resolvido UMA vez, todo IP tem de ser global e a conexão vai para esse IP (nome no `Host` e no SNI, certificado conferido contra o nome) — um DNS rebinding não tem segunda resolução para explorar; IP do par conferido de novo; 64 KB; 5 s |
| DNS rebinding / Origin | `Origin` fora da allowlist → 403 no `/mcp`; `ALLOWED_HOSTS` do app vale |
| CSRF | Endpoints de cookie mantêm a checagem de Origin; só `token`, `register`, `revoke` e `/mcp` (autenticados por Bearer/PKCE, sem cookie) são isentos. CORS `*` sem credenciais apenas nos endpoints públicos do OAuth |
| Prompt injection por dado armazenado | Títulos/descrições voltam como campos JSON, nunca concatenados em instruções; as instruções do servidor dizem que texto armazenado é dado; ações destrutivas em massa exigem token do servidor |
| Confirmação forjada pelo modelo | Massa só executa com `confirmation_token` emitido pelo servidor (uso único, 10 min, amarrado a usuário + concessão + ação + ids); o conjunto é reconferido e, se mudou, nada é excluído |
| Retry duplicando dinheiro | `idempotency_key` gravada na mesma transação; mesma chave + outro conteúdo = `CONFLICT` |
| Execução parcial | Um commit por chamada; qualquer falha depois do primeiro `flush` faz rollback de tudo (teste com falha injetada) |
| Abuso / laço de agente | Teto por pessoa + cliente com custo por tool (120 unidades/min; 30 escritas/min); massa limitada a 200 itens; página ≤ 50; OAuth com limite por IP |
| Vazamento por erro | Envelope estável; exceção inesperada vira `INTERNAL_ERROR` genérico com `correlation_id`; stack só no log do servidor (teste com erro de banco injetado) |
| Consulta arbitrária | Não há SQL nem tool genérica; filtros são de domínio; texto de busca é escapado (`%` não casa tudo) |
| Link de envio de anexo vazado ou reaproveitado | `cfm_up_` de uso único, 10 min, amarrado a usuário + concessão + UM lançamento; só o SHA-256 no banco; vai no cabeçalho `Authorization`, nunca na URL (que acaba em log de app, nginx e proxy). Na hora do envio tudo é conferido de novo: concessão revogada, conta inativa ou papel rebaixado a viewer recusam; o uso é marcado por UPDATE condicional (dois envios simultâneos não anexam duas vezes) e o reenvio devolve o resultado anterior |
| Arquivo malicioso pelo terminal | O envio pelo link passa pelo MESMO comando da tela: só JPG/PNG/WebP/PDF, conteúdo conferido pelos bytes (PDF disfarçado de PNG é recusado), teto por arquivo e cota do espaço com trava; o agente não lê nem apaga anexos |
| Anexo apagado sem aviso | Exclusão de lançamento com anexo exige o fluxo de prévia, que mostra quantos recibos serão apagados |
| Conteúdo de anexo alheio lido pelo agente | `attachments_get` só entrega o anexo se o LANÇAMENTO é visível (`access_policy`, a mesma do download pela tela); id de outra pessoa = `NOT_FOUND`; teto de tamanho; matriz A×B cobre |
| SSRF pelo arquivo da conversa (`attachments_add`) | A URL vem do modelo: só https/443, host numa lista de sufixos (`MCP_FILE_URL_HOSTS`, vazio desliga), nome resolvido uma vez com todo IP público e a conexão indo para esse IP (defesas do CIMD), sem redirect, teto de `upload_max_bytes`; o conteúdo passa pela mesma conferência de tipo do envio pela tela |
| Histórico vazando o que a pessoa não vê | `transactions_history` exige ver o lançamento; só campos de uma lista permitida; sem IP/user-agent; lançamento invisível = `NOT_FOUND` (testado com membro sem visão total e com terceiro) |
| Edição concorrente sobrescrevendo outra pessoa | `version` (hash do estado) na leitura; `expected_version` na escrita trava a linha e responde `CONFLICT` com a versão atual |
| Retry que anda um passo a mais | `statements_reopen` só age com pagamento vivo; exclusões e restaurações são idempotentes por estado; massa pelo token de uso único |
| Importação desfeita sem a pessoa ver o que sai | `imports_undo` em duas etapas: a prévia mostra o que sai por tipo e os recibos apagados; só o token (uso único, 10 min, amarrado ao conjunto) executa, e o conjunto é reconferido — mudou, nada é desfeito. Extrato de conta exige os escopos de conta e de renda, como as tools que registram esses movimentos |
| Alteração em massa fora do que foi mostrado | `transactions_bulk_update` só aceita o token da prévia e reconfere a elegibilidade de cada item (pago, cancelado, excluído, fora do espaço); qualquer mudança = nada é alterado |
| Botão do componente fazendo o que o app não deixa | O componente chama as MESMAS tools, pela mesma conexão; o servidor reaplica escopo, papel, `access_policy`, trava de paga e versão no clique. O "desfazer" do `_meta` é só um convite: executado depois de outra mudança, a versão recusa (`CONFLICT`). O editor só aparece com o escopo de escrita, mas quem decide é o servidor |
| Clique duplo registrando duas vezes | Acerto, pagamento de fatura e ajuste de saldo pelo componente levam uma `idempotency_key` gerada no clique; exclusão pede o segundo clique no próprio componente; massa só pelo token da prévia |
| Estabelecimento duplicado ou ligado errado pela IA | O vínculo automático é só por nome ou apelido IGUAL (normalizado); na escrita pela IA, nome só PARECIDO volta `AMBIGUOUS` com os candidatos em vez de criar outro cadastro. Criar, mesclar e excluir pedem papel de escrita no espaço (`planning.write`); estabelecimento de outro espaço = `NOT_FOUND` (matriz A×B) |
| Gasto por estabelecimento somando o que a pessoa não vê | `GET …/merchants/spending` e o `group_by=merchant` usam a mesma consulta da busca (`transaction_scope`); a contagem de lançamentos da lista também. Testado com membro que só vê o que o envolve |
| Vocabulário de um espaço vazando para outro | O `form` do `_meta` é montado só para o espaço do lançamento (ou os espaços da página), com as mesmas consultas de visibilidade das tools; o modelo não o lê |
| Conta desativada/senha trocada | Usuário recarregado a cada chamada; troca/redefinição de senha e "encerrar sessões" revogam as concessões |

## O que o operador vê

A trilha `mcptoolcall` (e a aba Saúde do admin) registra tool, cliente, resultado,
código de erro, duração e ids afetados — **nunca argumentos, valores ou títulos**.
O conteúdo das mudanças fica no `auditlog` da entidade, com `origin="mcp:<cliente>"`.

## Verificação

- Mutações dos testes de segurança principais (token de outra concessão, papel
  viewer, conflito de idempotência, conjunto mudado, open redirect, participante
  de acerto) foram aplicadas e **mataram** os testes correspondentes.
- No link de envio de anexo, sete mutações — aceitar papel viewer, concessão
  revogada, link expirado e registro de outra ação; anexar de novo no reenvio;
  marcar o uso antes de o arquivo passar pelas regras; perder a origem "via IA" —
  **mataram** `test_anexo_pelo_terminal.py`. A de "outra ação" sobreviveu na
  primeira rodada e ganhou teste próprio.
- `tests/security/*` (varreduras já existentes do app) seguem verdes com as rotas
  novas.
