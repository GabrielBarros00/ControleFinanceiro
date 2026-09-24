# ADR 0036 — Desfazer importação, e uma linha é "já importada" enquanto o lançamento dela existe

**Status:** aceito (2026-09-24)
**Relacionado:** [0008](0008-importacao-em-lote-auditavel.md) (importação em lote auditável),
[0010](0010-commit-unico-por-request.md) (commit único), [0035](0035-integracao-com-agentes-de-ia-mcp.md) (MCP)

## Contexto

Importar um extrato cria dezenas de lançamentos de uma vez. Com o espaço errado, a
coluna de valor trocada ou o formato de data invertido, o único caminho de volta era
excluir um a um. O lote já era auditável (ADR 0008: `ImportBatch` e `ImportRow`
guardam o desfecho de cada linha), mas não havia tela para ver os lotes nem para
desfazer um.

E mesmo excluindo tudo à mão, o arquivo corrigido não entrava de novo. A
idempotência do ADR 0008 contava como "já importada" toda linha com status
`imported`, viva ou não. A prévia (`/parse`) só marcava como duplicata o que tinha
lançamento vivo, então mostrava as linhas como novas; o `/commit` as recusava como
"já importado anteriormente". A tela e o servidor discordavam, e ganhava o servidor,
em silêncio.

## Decisão

1. **Uma linha conta como já importada enquanto o lançamento que ela criou existe.**
   O conjunto de impressões digitais do `/commit` agora só inclui linhas `imported`
   cujo lançamento não foi excluído. Reimportar com o lançamento vivo continua sem
   duplicar (a garantia do ADR 0008, que existe contra duplo clique e reenvio). O que
   foi desfeito, ou excluído, pode voltar, como a prévia já mostrava.
2. **Desfazer é exclusão, com as regras da exclusão.** `POST /{ws}/imports/{id}/undo`
   chama `delete_transaction` para cada lançamento vivo do lote: permissão, trava de
   paga, anexos. É **tudo ou nada**: um lançamento que não pode sair derruba o
   desfazer inteiro, e nada é gravado (ADR 0010).
3. **Anexo não tem desfazer**, porque o arquivo é apagado de verdade. Com anexo, o
   servidor só desfaz com `confirm_attachments: true`, e a tela mostra quantos recibos
   saem antes de pedir a confirmação.
4. **Só a própria importação.** `GET /{ws}/imports` e `GET /{ws}/imports/{id}` listam os
   lotes de quem pergunta; o de outra pessoa responde 404. Os lançamentos do lote são
   de quem importou, e desfazê-los seria excluir o que não é seu. É a mesma regra do
   `imports_list` no MCP.
5. **Idempotente.** Desfazer de novo não acha lançamento vivo e responde `deleted: 0`.
   O lote fica como "desfeita" (`imported > 0` e `live_transactions == 0`), sem coluna
   nova: o estado é derivado dos lançamentos.

## Consequências

- Tela: "Importações anteriores" na página de importar, com Desfazer e a contagem de
  recibos.
- MCP: sem tool nova. `imports_list` já mostrava os lotes e quanto deles ainda existe,
  e o desfazer pela IA é a prévia de massa com `filters.import_batch_id` e o token de
  confirmação. É a mesma exclusão por lançamento, com uma diferença de apresentação:
  a prévia mostra e deixa de fora o que não pode sair, e o app recusa o lote inteiro.
  As duas mostram o conjunto antes de agir.
- Restaurar um lançamento desfeito depois de reimportar o arquivo cria uma duplicata.
  A restauração é uma ação explícita, e a lista mostra os dois lançamentos.
- Fica de fora: desfazer parcialmente pela tela (escolher linhas). Para isso há a
  seleção em massa da lista de lançamentos.
