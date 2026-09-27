# ADR 0041 — A edição parcial que mexe no dinheiro é completada pelo comando, com a divisão gravada

**Status:** aceito (2026-09-27)
**Relacionado:** [0001](0001-alocacao-monetaria-em-centavos.md) (centavos),
[0004](0004-origem-de-pagamento-por-pagador.md) (origem por pagador),
[0010](0010-commit-unico-por-request.md) (commit único),
[0015](0015-conversao-na-entrada-e-taxa-cruzada.md) (conversão na entrada),
[0035](0035-integracao-com-agentes-de-ia-mcp.md) (MCP),
[0040](0040-item-da-nota-com-medida.md) (item com medida)

## Contexto

`PUT /transactions/{id}` tem dois caminhos. Com `payers` (ou `splits`, `items`,
`split_mode`, `adjustments`) é a **edição completa**: o cliente manda a divisão
inteira, o comando converte a moeda e recria os filhos. Sem eles era a **edição
parcial**, que só fazia `setattr` e, para o valor, reescalava um pagador e uma parte.

A auditoria de 2026-09-26 (A2) registrou que o caminho parcial era uma armadilha
contornada duas vezes:

- gravava `currency` **sem converter**, lia `total_amount` na moeda-base e apagava o
  original de uma compra convertida, e mantinha a cotação e o IOF antigos ao mudar a
  data ou o cartão;
- com duas pessoas na divisão, recusava o valor novo;
- ao mudar a forma de pagamento, deixava o pagador com `credit_card` numa compra sem
  cartão, e a edição seguinte dava 400.

A tela nunca usou esse caminho para dinheiro: o formulário manda a definição inteira.
O MCP, que edita campo a campo, montava a edição completa sozinho — as funções mais
ramificadas do backend (`_update_single` com 49 ramos). Eram três regras para a
mesma coisa, e a do MCP divergia da do app (recusava reconverter uma divisão fixa,
por exemplo).

## Decisão

1. **Valor e moeda da edição são os DA COMPRA**, nos dois caminhos: a moeda original
   numa compra convertida, a moeda do lançamento nas demais. Sem `currency`, vale a
   moeda da compra; sem `total_amount`, o total nela. É o par que o formulário mostra.
2. **Edição parcial que mexe no dinheiro vira edição completa dentro do comando.**
   Mexe no dinheiro quem muda o total, a moeda, a forma de pagamento, o cartão ou a
   conta — e, numa compra convertida, a data (a cotação é a do dia). O comando lê a
   divisão gravada, aplica o que veio e a passa pela mesma conversão e pelo mesmo
   cálculo da edição completa (`_redefine_pela_edicao_parcial` → `_grava_definicao`).
3. **A divisão é reescalada na proporção do que está gravado.**
   - Na **reconversão** (a mesma compra com cotação, IOF ou moeda novos), a proporção
     é exata em qualquer estrutura: vários pagadores, valores fixos, itens, ajustes.
   - No **total novo**, só quando há um jeito de repartir: um pagador e divisão por
     igual ou por percentual, com no máximo um item e sem ajustes. Com vários
     pagadores, valores fixos, itens detalhados, ajustes ou divisão por item, o
     comando recusa (`ReescalaAmbigua`, 400) em vez de adivinhar quem pagou a
     diferença ou em que item ela está.
4. **A origem do pagador segue a do lançamento quando ele é o único pagador**: mudar a
   forma de pagamento limpa o método próprio dele, e ir para o cartão limpa a conta.
   Com dois ou mais, a origem de cada um é dado explícito (ADR 0004) e é validada.
5. **Conta na edição parcial** (`account_id`), para a despesa de um pagador só, com as
   regras do ADR 0004 (a conta é de quem pagou, e não existe no cartão). Não combina
   com `payers`.
6. **O que está gravado não é revalidado.** Pessoas, contas e categorias vêm da linha
   (`referencias_gravadas`); só os valores mudam. Revalidar faria a correção de um
   valor falhar por um fato posterior — a pessoa saiu do espaço, a conta foi
   desativada —, o que a edição parcial nunca barrou. O que a requisição traz de novo
   (categoria, conta) é validado.
7. **O MCP passa a mandar só o que mudou.** A regra é do comando; a tool traduz o
   `motivo` da `ReescalaAmbigua` para o parâmetro que completa a edição (`items`,
   `split`, `paid_by`). Ela só monta a edição completa quando a pessoa pede uma
   divisão nova ou manda os itens da nota.

## Consequências

- Uma regra em vez de três. `PUT {"total_amount": 60}` numa compra de US$ 50 grava
  US$ 60 convertidos, e o MCP reconverte uma divisão fixa na mudança de data em vez
  de pedi-la de novo.
- Mudança de contrato para clientes externos da API: `total_amount` sem `currency`
  numa compra convertida passou a estar na moeda original. Para voltar à moeda-base,
  mande `currency` explícita. Os dois clientes do projeto já trabalhavam assim.
- `null` explícito em coluna obrigatória (`title`, `total_amount`, `currency`,
  `transaction_date`, `status`) passou a ser "não mexe"; antes chegava ao banco e dava
  500.
- Total novo numa despesa com vários itens deixou de ser rateado entre eles: os
  valores vêm da nota, e ratear mudaria cada linha (e o unitário, ADR 0040) sem a
  pessoa saber.
- Fica de fora a edição da **compra parcelada inteira** (`PUT
  /installment-group`), que recebe a definição completa por desenho: o MCP ainda
  parte da compra agregada (`_aggregate_group_whole`) para montá-la. E o formulário
  da tela continua mandando a definição inteira, que é o que um formulário tem.
