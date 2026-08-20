# Editar recorrência é planejar, revisar e aplicar — e a série pode ter fim

Três queixas de uso, uma raiz: **o modelo de recorrência mudava e os lançamentos
já criados não acompanhavam** — nem a data, nem a existência.

**Alterar não movia nada.** `sync_unpaid_instances` reaplicava título, valor,
moeda, forma de pagamento, cartão, fatura, pagador, divisão e categoria. Não
reaplicava `transaction_date`, `occurrence_date`, `billing_month` nem `status`.
Mudar "todo dia 5" para "todo dia 20" deixava os lançamentos já criados no dia 5,
para sempre.

**Excluir e desativar não tocavam em nada.** `DELETE` apenas desvinculava as
instâncias (`recurring_expense_id = None`) e apagava o template; `is_active=False`
só parava a geração futura. A conta do mês corrente continuava lá, confirmada e
contando. A confirmação de exclusão dizia isso numa linha em cinza, sem oferecer
alternativa.

**A opção existia e era invisível.** O `<select>` "Aplicar alterações a" só
aparecia na edição, no rodapé de um modal longo, sem dizer quantos nem quais
lançamentos seriam atingidos.

Somado a `/me/overview` **não materializar recorrência** (só `/transactions`,
`/analytics/*` e `/me/income` chamavam `ensure_and_commit`), a leitura de que
"alterar a recorrência não muda nada no Geral" estava correta pelo que a tela
mostrava.

E uma quarta, de outra natureza: **a recorrência não tinha fim.** Uma mensalidade
de faculdade paga por doze anos virava uma série infinita — sem "faltam 87 de
144", com a previsão projetando para sempre.

## Decisões

**Um planejador puro, e a escrita executa o plano dele.** `RecurringService.plan`
recebe o template, as mudanças pretendidas e um "a partir de", e devolve, por
lançamento, o que vai acontecer: `update`, `move`, `cancel`, `create` ou `none`
(com o motivo do congelamento). Não escreve nada. `apply_plan` executa **só** os
itens escolhidos. `POST .../recurring/{id}/preview` e o `PUT` chamam a MESMA
função — é isso que impede a tela de prometer uma coisa e o servidor fazer outra.

**A reconciliação do mês, e por que `move` existe.** Para cada mês do escopo,
compara-se o conjunto ESPERADO (`occurrences_in_month` do template futuro) com o
EXISTENTE. Uma esperada contra uma existente com datas diferentes vira `move`, não
"cancela e recria": mover preserva anexos, tags e a identidade do lançamento. Fora
desse caso o pareamento não é óbvio (semanal virando diário) e o diff de conjunto
é a leitura honesta. `billing_month` não muda — a data nova vem do mesmo mês, por
construção.

**Criar só do mês corrente em diante.** Preencher mês fechado é materialização
retroativa, e ela já tem pergunta própria no formulário (`materialize=past`); as
duas na mesma tela deixariam a pessoa sem saber qual respondeu.

**Nada é aplicado sem estar na lista.** `apply_to` (ids) e `create_occurrences`
(datas, para o que ainda não tem id) são obrigatórios para agir. Um default
"aplica tudo" traria de volta a ação invisível que a revisão veio remover. Sem
eles, o `PUT` cai no `scope` legado — compatibilidade para quem chama a API sem
revisão, e lá a data continua congelada.

**As travas correm DE NOVO no apply, contra o banco.** A lista da tela pode ter
sido aberta há dez minutos; se alguém pagou a conta nesse meio-tempo, o id ainda
está marcado e o servidor precisa recusar. Cada instância é tocada num savepoint:
mover `occurrence_date` pode colidir com `uq_recurring_occurrence` (instância
excluída deixa tombstone e ocupa a vaga), e quem colide desiste sozinho.

**Cancelar, não excluir.** O que a revisão dispensa vira `status=cancelled`:
estado terminal, fora de toda agregação, com rastro do que já esteve no mês — e,
por conservar a linha, segurando a vaga na unique, então reativar o template não
recria o que a pessoa acabou de dispensar. Mesma decisão do cancelamento de
parcelas futuras de uma compra parcelada.

**`/me/overview` e `/me/payables` materializam.** Varrendo os espaços da pessoa
(`workspaces_do_usuario`) e passando o PAPEL — um `viewer` não provoca escrita, e
sem isso estas rotas seriam a porta dos fundos dessa regra.

**A série pode ter fim: `end_date`.** Teto espelhado no piso de `start_date`, e
aplicado nos DOIS caminhos de `occurrences_in_month` (o preset e o "a cada N", que
retorna antes) — aplicá-lo só num daria uma mensalidade que respeita o fim quando
é mensal e o ignora quando é bimestral. A entrada aceita `end_date` **ou**
`end_after_occurrences` ("por 144 vezes"), e só a primeira é persistida: guardar as
duas criaria duas verdades sobre quando a série acaba, que divergiriam na primeira
edição de frequência. A conversão roda no servidor, com a MESMA aritmética que
materializa.

**Parcelamento sem juros no financiamento.** `calculate_amortization_schedule` já
tratava taxa zero; faltava a porta de entrada. Um seletor "Financiamento (com
juros) | Parcelamento sem juros" esconde taxa e sistema de amortização e troca o
vocabulário — "Tabela PRICE" numa mensalidade é linguagem de empréstimo para o que
não é um.

## Consequências

- Migração `b3d9f21c74e8`: `end_date` em `recurringexpense` e `recurringincome`,
  `NULL` em toda linha existente (= "sem fim", o comportamento de sempre).
- `RecurringRead` (novo schema) expõe `occurrences_total` e
  `occurrences_remaining`, DERIVADOS e não colunas — armazená-los exigiria
  recalcular a cada edição, e a cópia ficaria errada na primeira que alguém
  esquecesse. Herda de `RecurringExpenseBase`, **não** de `RecurringExpense`: o
  model de tabela carrega o `Relationship` `transactions`, e o Pydantic não gera
  schema para `Mapped[List[Transaction]]` — o app nem sobe.
- `_tem_template_ativo` ignora série encerrada: uma mensalidade que terminou
  continua com `is_active=True` (ninguém volta para desligá-la) e pagaria as
  consultas de dedup e um commit por requisição, para sempre.
- `sync_unpaid_instances` continua existindo, agora sobre `_reaplica` — o corpo
  compartilhado com o `apply_plan`. Duas reaplicações diferentes produziriam
  estados diferentes a partir do mesmo template.
- O `preview` é `POST` porque leva corpo, não porque muda estado; está declarado
  em `SEM_EVENTO_ESPERADO` no contrato de eventos, ao lado de
  `preview_transaction`.
- O diff da revisão mostra só título, valor e data — o que se reconhece na linha.
  Divisão, categoria e forma de pagamento acompanham sempre; listá-las campo a
  campo transformaria a revisão numa tabela de diferenças em vez de uma lista de
  lançamentos.
