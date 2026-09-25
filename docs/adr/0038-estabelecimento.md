# ADR 0038 — Estabelecimento: onde a despesa foi feita, como vocabulário do espaço

**Status:** aceito (2026-09-24)
**Relacionado:** [0008](0008-importacao-em-lote-auditavel.md) (importação), [0018](0018-privacidade-e-propriedade-pessoal.md)
(visibilidade), [0035](0035-integracao-com-agentes-de-ia-mcp.md) (MCP), [0036](0036-desfazer-importacao.md) e
[0037](0037-importacao-de-extrato-de-conta.md) (importação de extrato)

## Contexto

O título do lançamento é texto livre, e o extrato escreve o mesmo lugar de muitos
jeitos: "IFD*MC DONALDS 0231", "MCDONALDS", "McDonald's". Para responder "quanto
gastei no McDonald's" o app (e o agente) só tinham o agrupamento por título
normalizado, que junta grafias parecidas por acaso e separa as diferentes.

## Decisão

1. **Estabelecimento é vocabulário do espaço**, como categoria e tag
   (`Merchant`): nome único no espaço, exclusão lógica, reativação pelo nome. Um
   lançamento e uma recorrência podem apontar para um (`merchant_id`, anulável). A
   ocorrência da recorrência herda o da recorrência.
2. **Apelidos** são as grafias do extrato, guardadas já normalizadas: sem acento,
   caixa, dígitos, pontuação e letras soltas (`normaliza_estabelecimento`). Dígito
   sai porque o extrato o acrescenta à toa (loja, terminal, parcela). Um apelido é
   de UM estabelecimento do espaço (409 com o nome do dono), senão o vínculo
   automático teria dois candidatos.
3. **Vínculo automático só por igualdade.** Um lançamento NOVO sem estabelecimento
   escolhido se liga ao de nome ou apelido IGUAL ao título normalizado; a
   importação faz o mesmo em cada linha. Parecido não liga. Editar o título não
   revincula, porque a pessoa pode ter tirado o vínculo de propósito.
4. **Pelo nome, acha ou cria.** A tela e a API aceitam `merchant_name`: o de nome
   igual (sem caixa) ou de apelido igual; sem nenhum, um novo. O nome igual vem
   antes do apelido porque um nome sem letras ("7-11") não tem chave de apelido e
   seria recriado a cada uso.
5. **Categoria padrão**, opcional: o lançamento avulso novo ligado a ele que chega
   SEM categoria ganha a dele, no item único (o mesmo upsert da edição
   simplificada). Não vale para a parcelada, cujos itens são fatiados por parcela.
6. **Mesclar** junta dois cadastros do mesmo lugar: o de origem some, e os
   lançamentos, as recorrências, o nome e os apelidos dele passam ao que fica.
   **Excluir** tira o vínculo de todos os lançamentos (como a tag), para ninguém
   apontar para um estabelecimento que não aparece em lugar nenhum.
7. **Compra parcelada inteira:** o corpo da edição é o do create, em que ausente e
   nulo se confundem. O estabelecimento só muda quando o campo vem; sem ele, fica o
   da compra, e quem não conhece o campo não o apaga. Com parcelas pagas, as
   pagas congelam (como o resto delas) e as em aberto recebem o novo.
8. **Gasto por estabelecimento** (`GET …/merchants/spending?month=`): a soma do
   agrupamento do agente (`transaction_query.breakdown`), com status realizados,
   por moeda e só o que a pessoa vê. Traz o valor cheio e a sua parte, e o que não
   tem estabelecimento vira uma linha só. A contagem de lançamentos na lista também
   conta só o que a pessoa vê.
9. **Esquema:** tabela `merchant` (índice único `workspace_id, name`), `aliases`
   em JSON, e `merchant_id` com FK nomeada em `transaction` e `recurringexpense`.

## MCP

Sem tool nova, pelo teto do catálogo (ADR 0035): o estabelecimento entrou nas tools
de vocabulário e de lançamento.

- `categories_list` traz os estabelecimentos com apelidos e categoria padrão.
- `categories_create` e `categories_update` com `kind=merchant`: criar com
  `aliases` e `default_category`; renomear, trocar apelidos, tirar a categoria
  padrão (`""`), mesclar (`merge_into`, o nome do que fica) e excluir.
- `transactions_create`/`_update` com `merchant` (nome ou apelido; na edição, `""`
  desvincula). Na IA, **parecido vira pergunta**: se o nome não é igual a nenhum
  mas lembra um cadastrado ("Mc Donalds" com "McDonald's"), a tool devolve
  AMBIGUOUS com os candidatos em vez de criar um segundo cadastro do mesmo lugar.
  Sem nada parecido, cria.
- `transactions_get`/`_search` mostram o estabelecimento, e a busca (e com ela a
  prévia de massa e o `reports_breakdown`) filtra por `merchant`.
- `reports_breakdown` ganha `group_by=merchant`. O `title` continua, para o que
  ainda não tem estabelecimento.
- O componente mostra o estabelecimento no lançamento e na lista, e o editor tem o
  campo, com os do espaço como sugestão.

## Consequências

- O vínculo automático não alcança o passado: lançamentos antigos ficam sem
  estabelecimento até alguém escolher. Não há "sugerir" no servidor; a tela sugere
  pela lista, e o agente pergunta.
- A recorrência guarda o estabelecimento, mas a tela de recorrências ainda não o
  mostra nem edita. A assinatura (ADR seguinte) é quem vai usá-lo como provedor.
