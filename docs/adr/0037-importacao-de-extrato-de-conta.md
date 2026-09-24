# ADR 0037 — Extrato de conta: cada linha vira o que ela é (despesa, renda, transferência ou pagamento de fatura)

**Status:** aceito (2026-09-24)
**Relacionado:** [0008](0008-importacao-em-lote-auditavel.md) (importação em lote),
[0036](0036-desfazer-importacao.md) (desfazer importação), [0021](0021-recurso-pessoal-sem-workspace.md)
(conta é da pessoa), [0034](0034-saldo-caixa-e-previsao.md) (saldo e caixa), [0029](0029-liquidacao-competencia-e-caixa.md)
(liquidação), [0035](0035-integracao-com-agentes-de-ia-mcp.md) (MCP)

## Contexto

A importação do ADR 0008 é de despesas de UM espaço. O `invert_amount` tira o sinal
e toda linha vira lançamento. Um extrato de conta corrente não é isso. Ele tem:

- o salário e o Pix recebido, que viravam despesa;
- a transferência para a poupança, que virava despesa, e a mesma quantia sumia da
  conta e não aparecia em lugar nenhum;
- o pagamento da fatura, que virava despesa e somava de novo as compras do cartão.

A pessoa tinha de marcar "ignorar" linha a linha, e o que ela ignorava não entrava
no saldo da conta.

## Decisão

1. **Um segundo modo de importar, pessoal:** `/me/imports`, ligado a UMA conta da
   pessoa. O sinal do extrato é preservado: positivo entrou, negativo saiu
   (`direction`), e o valor vai em módulo. A importação de despesas de espaço segue
   igual.
2. **Cada linha tem uma classificação e vira o registro que o app já tem, pelo
   comando da tela:**

   | Classificação | Sentido | Vira | Comando |
   |---|---|---|---|
   | despesa | saiu | lançamento no espaço escolhido, pago pela conta, liquidado | `create_transaction` |
   | renda | entrou | renda na conta, recebida | `create_income` |
   | transferência | saiu ou entrou | transferência com outra conta da pessoa | `create_transfer` |
   | pagamento de fatura | saiu | pagamento da fatura que ele quita | `pay_statement` |

   Nada de regra nova de dinheiro: saldo, caixa, fatura e divisão vêm dos mesmos
   comandos. O teste confere que o saldo da conta conta cada movimento uma vez.
3. **O servidor sugere, a pessoa decide.** O palpite
   (`app/domain/classificacao_de_extrato.py`) é conservador de propósito:
   - "pagamento … fatura" que saiu vira pagamento de fatura, com o cartão citado no
     título ou o único cartão da pessoa;
   - transferência só com palavra de transferência entre contas E o nome de outra
     conta da pessoa ("PIX ENVIADO FULANO NUBANK" não é transferência para a conta
     Nubank dela);
   - o resto segue o sinal (saiu = despesa, entrou = renda).
4. **A fatura do pagamento** é a de fechamento mais recente até a data do pagamento
   que ainda tem saldo. Se ela ainda está aberta com o ciclo já encerrado, é fechada
   antes (o mesmo auxiliar que o `statements_pay` do MCP passou a usar). Valor maior
   que o saldo não entra: o app não inventa crédito (ADR 0009).
5. **Linha que não pode entrar não derruba o lote.** Sem espaço, sem a outra conta,
   sentido trocado, moedas diferentes, papel de leitura no espaço, fatura sem saldo:
   a linha fica `skipped` com o motivo, que volta em `problems` e aparece na tela. Um
   erro que o comando da tela levanta DEPOIS da validação derruba o lote inteiro, com
   o número da linha, e nada fica gravado pela metade.
6. **Já importada** (ADR 0036): o que a linha criou ainda existe. A chave é o
   `external_id` do banco, quando o CSV traz um (coluna opcional); senão, a
   impressão digital, que agora leva o sentido: `conta, dia, sentido, centavos,
   título`. O sentido entra porque a mesma quantia pode sair e voltar no mesmo dia,
   como numa compra estornada. A transferência tem uma chave a mais: ela aparece no
   extrato das DUAS contas. A linha espelhada (mesmas contas, valor e dia de uma
   transferência viva) entra como duplicata, com o motivo.
7. **Esquema:** `importbatch.kind` (`expenses`/`account`) e `account_id`. Na
   `importrow`: `direction`, `classification`, `external_id`, `account_id` e o que a
   linha criou (`income_id`, `transfer_id`, `statement_payment_id`). `workspace_id`
   passa a aceitar nulo, porque o lote de extrato é pessoal. Texto, não Enum do
   Postgres, para não depender de `ALTER TYPE` a cada valor novo.
8. **Desfazer** (ADR 0036) cobre o extrato inteiro, tudo ou nada: exclui despesa,
   renda e transferência e estorna o pagamento de fatura. O estorno é de UM
   pagamento (`estornar_pagamento`), não o "Reabrir" da tela, que estornaria também
   os pagamentos que não vieram do extrato. Fatura paga volta a fechada.

## MCP

- `imports_preview` e `imports_commit` ganham `account`. Com ele, as linhas levam
  `direction`, `external_id` e, na gravação, `classification`, `space`,
  `category`, `counterpart_account` e `card`, tudo por nome. Sem `account`, o fluxo
  de antes não muda.
- Renda, transferência e fatura pedem os escopos de conta e de renda, como as tools
  que já as registravam. Só despesas pedem só o de lançamentos.
- `imports_list` traz os lotes de extrato.
- **`imports_undo`** desfaz os dois tipos de lote pelo MESMO comando do app, em duas
  etapas: a prévia devolve o que sai (por tipo) e os recibos apagados, com um token
  de 10 minutos; só o token executa, e ele reconfere o conjunto. A prévia de massa
  com `import_batch_id` continua valendo para os lotes de despesa.
- A `imports_preview` de despesas passou a marcar "já importada" só com o lançamento
  vivo, a regra do ADR 0036 que o commit já seguia.

## Consequências

- Fica de fora a categoria de cada DESPESA na tela de extrato (o agente já a passa
  por linha). Pela tela, a despesa entra sem categoria, e a pessoa categoriza depois
  em massa.
- Transferência entre moedas diferentes não entra pelo extrato: exige os dois
  valores, e o extrato só tem um. Registre pela tela de contas.
- A transferência espelhada só é reconhecida quando o valor e o dia batem. Um TED
  que cai no dia seguinte na outra conta entra como segunda transferência, e a
  pessoa a ignora na prévia.
