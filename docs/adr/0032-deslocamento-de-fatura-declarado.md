# A compra pode entrar noutra fatura, e quem diz isso é o usuário

Status: aceito, 2026-08-28. Relacionados: 0002 (fatura derivada no servidor),
0011 (ciclo da fatura), 0024 (perna de fatura), 0029 (competência × caixa).

## Contexto

A fatura de um cartão **não é composta pela data da compra**. Ela é composta pela
data em que o EMISSOR processa (captura) a compra, e o atraso entre as duas é do
estabelecimento: restaurante, hotel e companhia aérea capturam com um a três dias
de atraso; mercado captura na hora. Nem o cartão nem o app têm como prever qual
será.

Perto do fechamento isso decide em qual fatura a compra cai. Uma compra de 27/07
num cartão que fecha dia 28, capturada em 30/07, entra na fatura de **agosto** — e
o app, que roteia por `transaction_date`, a colocava em julho. O sintoma para
quem usa não é acadêmico: a fatura da tela não bate com a que chegou, o limite
comprometido fica errado, e o mês em que o dinheiro sai do caixa (que, para
cartão, é o `StatementPayment`) sai errado junto.

O ADR 0002 fechou o `statement_id` para o cliente — com razão: era IDOR e
corrupção cruzada de fatura. Mas fechou junto **qualquer** influência sobre o
destino. Sobrava uma única alavanca: mentir na `transaction_date`. E mexer nela
arrasta três coisas que não têm nada a ver com o pedido:

- a **competência** (`billing_month`), que manda em dívidas, relatórios e rateio;
- a **data da cotação** numa compra estrangeira — `_full_edit` reconverte pela
  `transaction_date`, então a compra ganharia a PTAX do dia errado;
- a data exibida no extrato e na própria fatura.

Ou seja: para corrigir a fatura era preciso corromper a contabilidade.

## Decisão

### 1. `Transaction.statement_shift`: um deslocamento DECLARADO, relativo e estreito

Uma coluna inteira, `NOT NULL DEFAULT 0`, dizendo **quantas faturas à frente (ou
atrás)** a compra entrou em relação ao que a regra do ciclo diz. `0` — o valor de
toda linha existente — é o comportamento de sempre.

**Relativo, não um mês absoluto.** Guardar "a fatura de setembro" não atenderia a
compra parcelada (o deslocamento vale para as N parcelas, cada uma no seu ciclo)
nem a recorrência (vale para ocorrências que ainda não têm mês), e morreria na
primeira edição de data. Sendo relativo, ele **sobrevive** a ela: o alvo natural é
recalculado da data nova e a correção se reaplica sozinha.

**Estreito: `-1..+2`.** Atraso de captura é de um a três dias e nunca atravessa
mais de um ciclo; `-1` existe para o caso oposto (o emissor manteve a compra na
fatura que fechou no dia). Um campo livre transformaria um ajuste de borda numa
forma de jogar despesa para qualquer mês do futuro — contabilidade criativa, não
correção de processamento.

**O ADR 0002 continua valendo.** O cliente nunca manda `statement_id`: manda "uma
para frente", e é o servidor que resolve qual fatura é. Não há como apontar para
a fatura de outro cartão ou de outra pessoa.

### 2. A ordem do roteamento é: regra → deslocamento → rolagem

```
1. natural  = regra do dia de fechamento sobre local_day(transaction_date)
2. desejada = avança(natural, statement_shift)
3. destino  = rola desejada para frente enquanto estiver fechada/paga
```

A ordem entre 2 e 3 importa: o deslocamento parte do alvo **natural**, não do já
rolado. Invertê-la faria "+1" a partir de uma fatura que rolou dois meses cair
três meses à frente do que se pediu.

### 3. Deslocamento inalcançável falha ALTO; a rolagem implícita continua calada

Pedir uma fatura já fechada responde **409**, com o mês e o motivo. Sem essa
guarda o pedido cairia na rolagem para frente e a compra voltaria, em silêncio,
para o alvo natural: o app diria "ok" e faria outra coisa.

A guarda vale só para `shift != 0`. Com deslocamento zero, rolar continua sendo o
comportamento correto — ali não há pedido do usuário, é a imutabilidade da fatura
fechada (ADR 0011) fazendo o seu trabalho.

Ela vive dentro de `get_or_create_statement`, e não em cada rota, para que o
próximo caminho de escrita não possa esquecê-la. A materialização preguiçosa da
recorrência é a única que a desliga (`strict_shift=False`): ela roda dentro de
rotas de **leitura**, e um deslocamento inalcançável não pode derrubar um GET de
extrato com 409 — a ocorrência cai no alvo natural, mesmo tratamento que o cartão
apagado já recebia.

### 4. Mover a fatura NUNCA move a competência

É o invariante central, e o que separa esta feature do defeito que ela corrige.
`billing_month`, divisão entre pessoas, dívidas, relatórios, PTAX/IOF e a data
exibida da compra ficam todos onde estavam. Limite comprometido e mês de saída de
caixa acertam sozinhos, porque ambos derivam da fatura.

### 5. O aviso da janela de fechamento, e onde a correção realmente mora

`GET /me/credit-cards/{id}/statement-for` passa a devolver `days_to_closing` e
`options` — as faturas vizinhas alcançáveis, cada uma com o `shift` que a
alcança. A tela escolhe um **mês** e devolve o número que veio junto dele;
nenhuma aritmética de ciclo acontece no cliente.

Nos **três dias** que antecedem o fechamento, o formulário avisa que o
processamento pode jogar a compra para a fatura seguinte. Três e não cinco: num
ciclo de ~30 dias, cinco fariam o aviso aparecer em uma de cada seis compras no
cartão, e um aviso quase sempre falso fica invisível em duas semanas — aí falha
justamente na compra em que importava. Sem cor de alerta, pelo mesmo motivo: o
que se diz ali é uma probabilidade, não um erro.

O atalho que acompanha o aviso ("esta loja costuma demorar") é conveniência para
quem **sabe** — restaurante, hotel, companhia aérea. Ele não é o conserto: na
hora de lançar, marcar que a compra vai escorregar é palpite. O conserto é o
seletor **"em qual fatura esta compra entrou?"** no detalhe do lançamento, porque
é lá que a dúvida já virou fato — a fatura real chegou e não bateu com a da tela.

`days_to_closing` vem `null` quando o destino não é o ciclo natural da compra (já
deslocada, ou rolada por fatura fechada): ali o número compararia a data da
compra com o fechamento de um ciclo a que ela não pertence.

## Consequências

- Migração `c4f8b12e7a09`: `statement_shift` em `transaction` e em
  `recurringexpense`, `NOT NULL DEFAULT 0`. Nada retroativo — nenhum lançamento
  existente muda de fatura.
- O template de recorrência carrega o seu próprio deslocamento: uma assinatura
  cobrada perto do fechamento cai na fatura seguinte todo mês, e declarar isso
  uma vez evita corrigir cada ocorrência à mão. A instância materializada o
  herda na própria linha, para que editar a data dela não desfaça a correção.
- Deslocamento sem cartão é **400**, e sair do cartão **zera** o valor: um
  deslocamento órfão acordaria ao vincular um cartão depois, mandando a compra
  para uma fatura que ninguém pediu naquele momento.
- Contrato: `TransactionCreate`/`Update`/`Read` e os schemas de recorrência
  ganham `statement_shift`; `StatementTargetRead` ganha `shift`,
  `days_to_closing` e `options`.
- Sem rota de escrita nova. Mover uma compra é um `PUT` parcial com
  `statement_shift` — o mesmo caminho que já rerroteava a fatura por data e
  cartão.

## O que fica de fora

**A janela para corrigir é até a fatura de destino fechar.** A divergência
costuma ser descoberta quando a fatura real chega, e nessa hora o ciclo anterior
já pode estar fechado — `shift = -1` cai na guarda e sobra reabrir a fatura, que
estorna os pagamentos. Duas saídas foram estudadas e ficam para depois: um
**ritual de conferência no fechamento** (listar as compras dos últimos dias do
ciclo e perguntar "estas entraram nesta fatura?", que é quando a fatura real está
na mão e o ajuste ainda é barato) e um **furo controlado no ADR 0011** (permitir
o deslocamento para fatura `closed` sem pagamentos, recalculando o total
congelado). A segunda é decisão de dono, não técnica.

**A reconciliação com a fatura real (import OFX/CSV do emissor)** continua fora.
É a resposta definitiva — o arquivo do banco tem a data de processamento e a
fatura de verdade, então não se adivinha nada —, e resolve junto compra esquecida
e valor divergente. `imports.py` hoje não toca em cartão.

**A heurística por cartão (`posting_lag_days`)** foi descartada: o atraso é do
estabelecimento, não do cartão. Ela deslocaria a maioria das compras para acertar
a minoria da borda.

**O `>=` do dia de fechamento não foi mexido.** `resolve_statement_target` manda a
compra do PRÓPRIO dia de fechamento para a fatura seguinte. Se o emissor do
cartão inclui o dia do fechamento na fatura que fecha nele, isso é erro
sistemático de regra — e tapá-lo com ajuste manual por lançamento seria trocar um
caractere por trabalho recorrente. Medir contra uma fatura real antes de mudar.
