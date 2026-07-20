# Ciclo da fatura (open→closed→paid) e pagamento fora da Transaction

A fatura (`CardStatement`) só tinha `status` sem carimbos nem transições, e o `total_amount` armazenado (default 0) divergia do total calculado na rota. Não havia fechar/pagar/reabrir, nem limite comprometido/disponível. Precisávamos de um ciclo explícito sem reintroduzir contagem dobrada nos números (o defeito-classe que a auditoria combate).

## Decisões

**Máquina de estados com carimbos.** `open → closed → paid`, com reabertura passo a passo (`paid → closed → open`). `close` grava `closed_at`, `pay` grava `paid_at`, e reabrir os limpa. Transição inválida é `StatementStateError` → 409. A máquina vive no `CreditCardService` (serviços só `flush`; a rota comanda o commit — ADR 0010).

**Total congelado no fechamento.** Enquanto `open`, o total autoritativo é calculado no servidor (soma das transações realizadas em moeda-base — ADR 0003/0006). Ao **fechar**, esse valor é gravado em `total_amount`: editar/cancelar uma transação depois não muda o que foi faturado. `effective_total` devolve o calculado (aberta) ou o congelado (fechada/paga).

**Cobrança tardia não reabre mês faturado.** `get_or_create_statement` rola para frente: se a fatura-alvo do mês já está fechada/paga (imutável), avança para a próxima aberta. Fatura fechada nunca recebe transação nova.

**Pagamento NÃO é uma `Transaction`.** As compras do cartão já compõem o total da fatura e já entram em dívidas/relatórios. Registrar o pagamento como despesa faria contagem dobrada. Por isso criamos `StatementPayment` (fatura × conta × valor × data), que apenas registra **de qual conta** (`PaymentAccount`, ADR 0004) saiu o dinheiro e libera o limite. Reabrir uma fatura paga faz soft-delete do pagamento. Quando um ledger de verdade existir (oportunidade da seção G do plano), o pagamento vira uma transferência conta→cartão — não uma despesa.

**Limite comprometido/disponível.** `committed` = soma do total efetivo das faturas **ainda não pagas** (aberta usa o calculado; fechada usa o congelado). `available = limit − committed`. Fatura paga libera o limite. Exposto nos reads de cartão.

**Vencida é derivada.** `is_overdue` = não paga e passou do vencimento; calculado na leitura, não persistido — evita depender de um job para carimbar `overdue`.

**Grupo de parcelamento coeso.** Cancelar/excluir opera sobre todas as irmãs vivas do `installment_group_id` atomicamente; parcelas já pagas são preservadas (não corrompem acertos feitos).

## Consequências

- Migração `d1f6b083a2c4` (idempotente): `cardstatement.closed_at/paid_at` + tabela `statementpayment`.
- Endpoints novos: `POST .../statements/{id}/close|pay|reopen`; `POST/DELETE .../transactions/{id}/installment-group[/cancel]`.
- Números permanecem em fonte única: o pagamento de fatura não aparece como despesa em nenhum relatório.
