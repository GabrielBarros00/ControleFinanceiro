# Liquidação: o lançamento sai do caixa quando é pago, não quando é registrado

O ADR 0022 separou competência de caixa e listou seis fontes, cada uma com a sua
data efetiva. A fonte 1 — lançamento fora do cartão — usava `transaction_date`, e
com isso o app afirmava que **todo boleto, Pix, dinheiro e transferência saía do
bolso no instante em que a despesa era registrada**.

Três consequências, todas mudas:

1. **`payment_method` não entrava em consulta nenhuma.** `pix`, `cash`, `boleto`,
   `bank_transfer` e `other` eram rótulos sem efeito: só `credit_card` mudava algo,
   porque roteia para uma fatura. Perguntar "dinheiro desconta automaticamente? e
   Pix?" não tinha resposta no código — tudo descontava, sempre.
2. **A recorrência era o pior caso.** A materialização preguiçosa cria a conta de
   luz no dia 10 sozinha; ninguém a digitou, então ninguém afirmou ter pago nada. E
   mesmo assim o caixa a debitava no dia 10.
3. **Não havia como marcar uma conta como paga.** `TransactionStatus.paid` existe
   na máquina de estados desde o ADR 0003 e **nenhuma rota e nenhuma tela o
   define** — o frontend só tinha "Reabrir despesa", o caminho de volta de um
   estado inalcançável. E ainda que existisse não mudaria número nenhum:
   `confirmed` e `paid` estão os dois em `REALIZED_STATUSES`.

O resultado é que "quanto ainda vai sair este mês" não tinha resposta em lugar
nenhum do sistema.

## Decisões

**`Transaction.settled_at` é a data em que o dinheiro saiu.** `NULL` = ainda não
saiu. `CashFlowService._lancamentos` passa a filtrar `settled_at IS NOT NULL`, a
usar `settled_at` como data efetiva **e como janela do mês** — filtrar por uma data
e exibir outra produziria um extrato de agosto sem a linha e um de julho com uma
linha datada de agosto. Como `occurred_on` alimenta o `ConversorPorData`, a cotação
passa a ser a do dia do pagamento.

**Coluna própria, não o status `paid`.** O estado `paid` congela a despesa inteira
("Despesa paga não pode ser alterada: reabra antes"), trava que existe para
proteger o histórico de ACERTOS. Confirmar o pagamento de um boleto não pode
impedir a correção do valor ou da divisão — são fatos diferentes, e corrigir o
valor de uma conta paga é rotina. Competência (`status`) e caixa (`settled_at`)
ficam ortogonais.

**Quem decide é um ponto só: `app/domain/settlement.py::resolve_settled_at`.** O
modo de falha é silencioso nos dois sentidos — um caminho que esquece de liquidar
some com a despesa do caixa; um que liquida sempre reintroduz o defeito de origem —
e nenhum dos dois quebra um teste existente. `tests/test_liquidacao_ponto_unico.py`
varre o AST de `app/` e falha quando uma construção nova de `Transaction` não
decide. As regras, em ordem:

| Situação | Resultado |
|---|---|
| Espaço sem controle de pagamento | liquidado na data (comportamento anterior) |
| Compra no cartão | `NULL` — quem se paga é a FATURA |
| `explicit` informado | vence o palpite |
| Padrão | liquidado se a data já chegou, a pagar se está no futuro |

O palpite da última linha vale para o que uma PESSOA digitou: quem registra uma
despesa de ontem está anotando o que aconteceu; quem cadastra o boleto que vence
dia 30 está anotando o que ainda vai acontecer. Ele **não** vale para o que a
máquina gerou, e por isso a recorrência sempre informa `explicit`.

**A opção é do ESPAÇO (`Workspace.settlement_tracking`, ligada por padrão),** e não
da pessoa: a resposta muda com o combinado da casa. Quem lança tudo depois de pagar
não quer a etapa a mais; quem cadastra o boleto quando ele chega precisa dela. É
perguntada na criação do espaço e editável em Configurações, e vale só para o que
for lançado dali em diante — desligar não sai marcando como pago o que ninguém
pagou.

**`RecurringExpense.auto_settle` (desligado por padrão)** é a opção de "débito
automático / Pix automático" que os bancos oferecem: a ocorrência nasce liquidada e
nunca entra na fila. Desligado por padrão porque assumir o contrário
reintroduziria o defeito justamente onde ele mais aparecia.

**Contas a pagar é a fonte 1 do caixa com o filtro invertido.**
`PayablesService` usa os MESMOS quatro filtros de `CashFlowService._lancamentos`
com `settled_at IS NULL`: as duas consultas particionam o mesmo universo, então o
total daqui é exatamente o `cash_out` de amanhã. O recorte é o **pagador**
(`TransactionPayer`), não a divisão — num jantar rateado que eu paguei, a conta a
pagar é minha e inteira, e a parte do outro vira acerto.

**Item próprio na navegação, chamado "Contas a pagar",** em Pessoal e no espaço.
Não entram fatura de cartão nem parcela de financiamento: são outro prazo, têm
botão próprio em Compromissos, e repeti-las aqui pediria o mesmo dinheiro duas
vezes.

**A migração preenche `settled_at = transaction_date` em TODA linha existente.**
É o que torna o resto seguro: sem ela, o caixa de todo mês já fechado cairia a zero
na primeira leitura depois do deploy — meses já conferidos, exportados e usados
para acertar contas entre pessoas. O `WHERE settled_at IS NULL` a mantém repetível.

## Consequências

- Migração `a1c7e5b39d42`: as três colunas, o backfill e o índice parcial
  `ix_transaction_a_liquidar` (`settled_at IS NULL AND deleted_at IS NULL AND
  credit_card_id IS NULL`) — sem ele a tela varre a tabela de lançamentos inteira.
- `CashFlowService._parcelas` ganha `settled_at IS NOT NULL` na dedup: desmarcar o
  pagamento da despesa vinculada a tira da fonte 1, e sem o termo ela continuaria
  suprimindo a parcela — a saída sumiria dos dois lados, o mesmo defeito que o
  filtro de status já tinha corrigido uma vez.
- `/me/overview` ganha `payables_total`, `payables_count` e `payables_overdue`,
  calculados pelo MESMO serviço que desenha a lista.
- **A liquidação é da transação, não de cada `TransactionPayer`.** Uma despesa com
  dois pagadores é liquidada junto. Simplificação assumida: o caso comum é um
  pagador, e uma coluna por pagador exigiria que a tela perguntasse "quem já
  pagou a sua parte", que é outra pergunta — e ela já tem resposta no acerto.
- Editar um lançamento com `settled: true` no corpo só age quando o booleano MUDA
  o estado. Sem isso, corrigir o título de uma conta paga em 14/08 reescreveria a
  data do pagamento e moveria a saída de mês.
