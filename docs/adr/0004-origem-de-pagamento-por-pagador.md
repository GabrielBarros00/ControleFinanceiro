# Origem do pagamento é por pagador, não global por despesa

`Transaction.payment_method` (enum) e `TransactionPayer.payment_method` (string legada sem UI) coexistiam como fontes concorrentes, e Pix/dinheiro/débito eram apenas rótulos sem origem financeira. Decidimos que a fonte de verdade é o pagamento POR PAGADOR: pagador × valor × método × conta (`PaymentAccount`), permitindo dois pagadores com meios diferentes. O método global da transação vira resumo/filtro.

**Implementação (Onda 2):** em vez de criar uma tabela paralela `TransactionPayment` (duas fontes para "quem pagou"), evoluímos a própria `TransactionPayer`: `payment_method` passou a enum validado e ganhou `account_id` (FK para `paymentaccount`); o backfill copiou o método global da transação para os payers antigos. Invariantes: conta pertence ao workspace e está ativa; método `credit_card` exige o cartão da transação e não usa conta.
