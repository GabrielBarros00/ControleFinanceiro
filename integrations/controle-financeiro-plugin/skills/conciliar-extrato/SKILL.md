---
name: conciliar-extrato
description: Concilia um extrato bancário ou de cartão (PDF, foto ou texto colado) com o que já está lançado no app — encontra o que falta, o que já foi importado e o que parece repetido, e importa só o que o usuário confirmar.
---

Use quando o usuário enviar ou colar um extrato e pedir para conferir, conciliar
ou importar.

1. Extraia do extrato as linhas de **saída** (data `YYYY-MM-DD`, descrição como
   está, valor positivo). Entradas (salário, estornos) não entram aqui — pergunte
   se o usuário quer registrá-las como renda (`income_create`).
2. Pergunte (ou confirme) o espaço onde os lançamentos entram, se houver mais de
   um.
3. Chame `imports_preview` com as linhas. Mostre ao usuário três grupos:
   - **já importadas** (`already_imported`) — serão puladas de qualquer forma;
   - **parecidas com lançamentos existentes** (`possible_duplicate`) — pergunte
     se são a mesma compra;
   - **novas**.
4. Com a resposta do usuário, chame `imports_commit` UMA vez, com uma
   `idempotency_key` nova, marcando `decision: ignore` no que ele descartou.
   Se a chamada falhar por rede, repita com a MESMA chave.
5. Informe quantas linhas foram importadas, ignoradas e puladas.

Lançamentos importados nascem pagos pelo usuário e 100% dele. Para compras
divididas com outras pessoas ou no cartão, use `transactions_create` em vez da
importação. Se o extrato tiver o saldo final e ele não bater com o app, ofereça
`accounts_adjust_balance` — mostrando antes a diferença.
