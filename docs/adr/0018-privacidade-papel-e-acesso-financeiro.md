# ADR 0018 — Papel diz o que eu faço; acesso financeiro diz o que eu vejo

**Status:** aceito (2026-07-30)
**Relacionado:** [0003](0003-politica-de-status-financeiros.md) (política de status),
[0009](0009-acertos-sem-sobrepagamento.md) (acertos),
[0017](0017-orcamento-com-escopo-casa-ou-pessoal.md) (orçamento com escopo)

## Contexto

`app/api/deps.py` tinha 39 linhas e duas funções — era **toda** a superfície de
autorização do sistema. `get_workspace_membership` é satisfeito por qualquer
papel, inclusive `viewer`, e era o gate de praticamente todo `GET`;
`require_role(...)` protegia as mutações.

O efeito é que **o papel controlava a escrita e não protegia a leitura**. Toda
listagem filtrava `workspace_id + deleted_at` e mais nada
(`transactions.py`, `income.py`, `credit_cards.py`, `financing.py`,
`payment_accounts.py`, `settlements.py`, `recurring*.py`). Em termos concretos,
quem entrava num workspace por convite passava a ler:

- o **salário** de todos os outros membros (`GET /income`);
- os **lançamentos individuais** de quem não o envolveu em nada;
- os **anexos** desses lançamentos — o arquivo, não só o metadado, bastando o id;
- os **cartões** alheios, com nome do banco e limite;
- os **totais da casa**, o ledger de dívidas com a quebra por pessoa e o
  endividamento de cada um.

Esse não foi um descuido pontual: eram ~15 rotas escritas em momentos
diferentes, cada uma copiando o filtro da vizinha. `viewer` acabou significando
"lê tudo, não escreve nada", e `member` "lê tudo, escreve o que é seu".

Havia ainda um problema de forma. As travas de autoria em mutações existiam em
**quatro formatos** espalhados por sete arquivos, apoiadas em quatro colunas
diferentes (`user_id`, `created_by_user_id`, `uploaded_by_user_id`,
`from_user_id`). Em seis lugares a condição era
`created_by_user_id not in (None, membership.user_id)`, o que fazia de **todo
registro sem autoria gravada um registro de todo mundo** — editável e apagável
por qualquer member. E `CreditCard` era a única entidade financeira sem coluna de
usuário nenhuma, logo sem trava alguma: qualquer member mudava o limite do cartão
de outro.

`app/domain/query_policy.py` centraliza status e moeda (ADR 0003/0006), mas não
tem nada de acesso — não havia camada de política para estender.

## Decisão

Separar dois conceitos que estavam colapsados num só:

- **Papel** (`WorkspaceRole`): o que eu posso **fazer** — `viewer < member <
  admin < owner`.
- **Acesso financeiro** (`FinancialAccess`, em `WorkspaceMembership`): o que eu
  posso **ver** — `involved_only` ou `full_workspace`.

São eixos independentes, e é isso que dá o valor: um `member` que só lança as
próprias despesas não precisa do extrato da casa; um `viewer` contratado para
conferir as contas precisa. Nenhuma das duas dimensões se deriva da outra.

Toda a regra passa a viver em **`app/domain/access_policy.py`**, irmão de
`query_policy.py`. Pontos do desenho:

1. **`admin` e `owner` têm acesso completo pelo CARGO**, sobrepondo a coluna
   (`effective_access`). Quem administra membros, cadastros e auditoria precisa
   dos números da casa para fazer o trabalho, e o dono não pode se trancar fora
   do próprio workspace.

2. **"Envolvido" é um predicado SQL**, não um filtro em Python
   (`involvement_filter`): criou **ou** pagou **ou** tem divisão direta **ou**
   participa da divisão de um item. É `or_` de **subqueries**, nunca `join` —
   join com as tabelas de participação multiplicaria a linha, e a contagem e a
   soma da listagem derivam da mesma statement. Assim lista, contagem, soma e
   paginação usam uma regra só, de graça.

3. **Invisível responde 404, não 403.** 403 confirmaria que o registro existe
   naquele id, e a existência já é informação: quantos lançamentos o outro tem,
   se aquele cartão é dele. A exceção é o `viewer`, que leva 403 do
   `require_role` antes de o corpo da rota rodar — resposta honesta ("você não
   escreve nada aqui") que não diz nada sobre o registro específico.

4. **Número da casa suprimido vira `null`, nunca `0`.** Zero é uma mentira
   aritmética: o membro somaria "a casa gastou 0" com "eu gastei 300" e
   concluiria coisa errada. `null` diz "você não tem acesso a isto", e a tela sabe
   não desenhar o comparativo. Vale para `total_expenses`, `total_income`,
   `net_savings`, `categories`, as barras do histórico de 6 meses e a previsão
   inteira — que é projeção de **caixa da casa** e por isso sobra apenas
   `my_budget`.

5. **O ledger de dívidas é calculado INTEIRO e recortado na saída.** O
   pareamento em `DebtService._settle_balances` é guloso sobre o conjunto todo de
   saldos: remover membros antes de parear produziria outro emparelhamento e um
   valor devido **diferente do real**. Então calcula-se tudo e só depois se
   esconde o que não é meu. Quando o recorte acontece, `totals` passa a ser o
   total do que está listado — senão a tela mostraria "R$ 500" acima de uma lista
   que soma 300.

6. **O `None` do dono significa duas coisas diferentes, e agora isso é
   explícito** (`can_write(..., null_is_shared=...)`):
   - **autoria perdida** (`Transaction.created_by_user_id`, `Attachment`,
     `Settlement`) → registro pessoal sem autor gravado, exige `admin+`;
   - **recurso da casa** (`CreditCard.owner_user_id`, `PaymentAccount`,
     `RecurringExpense`) → o `None` é a modelagem dizendo "compartilhado", e
     qualquer member mexe, como sempre foi.

   A distinção é parâmetro justamente porque, implícita, ela era um bug.

7. **`CreditCard` ganha `owner_user_id`.** Sem dono não havia como esconder o
   cartão de quem não tem nada com ele nem impedir a escrita. A visibilidade tem
   três ramos: é meu, é da casa (dono `NULL`, cartão legado), ou eu tenho compra
   nele — o último atende o caso legítimo de achar em que fatura caiu a minha
   despesa.

8. **Convite carrega a decisão.** `WorkspaceInvite.financial_access` viaja no
   convite, porque quem convida é que decide o que o outro verá; resolver no
   aceite deixaria a escolha com o convidado. O default é `involved_only`, e o
   papel default continua `member` — `viewer` deixaria o convidado sem poder
   lançar a própria parte, inútil num app colaborativo. `max_uses` de convite por
   link passa de `None` (ilimitado durante 7 dias) para **1**.

9. **Uma exceção deliberada fica mais estrita que esta política.** `GET
   /analytics/estimates` filtra por dono **incondicionalmente**: nem owner nem
   admin veem a meta pessoal de outro membro (ADR 0017). Unificar aquilo com
   `shared_or_mine_scope` em nome da consistência abriria um vazamento — o código
   registra isso no lugar, para o próximo refactor não "arrumar".

## Consequências

- Migração `b9d2f47a1c83` adiciona `financial_access` com
  `server_default 'involved_only'` — linha nova nasce **fechada**, venha de
  convite, registro, aceite de link ou import. Backfill por decisão do dono:
  `owner` e `admin` → `full_workspace`; `member` e `viewer` → `involved_only`.
  Não é preservação do comportamento antigo; é a correção pedida, reversível na
  tela de membros. Mais três índices que o predicado de envolvimento exige
  (`transaction.created_by_user_id`, `transactionpayer.user_id`,
  `transactionsplit.user_id`).
- Migração `c5a8e31f7d94` adiciona `creditcard.owner_user_id` e atribui o dono
  **só onde o workspace tem um único membro**. Com vários membros fica `NULL` =
  "compartilhado legado": adivinhar o dono esconderia da pessoa o cartão que ela
  usa todo dia.
- Migração `d7f2b419ac36` adiciona `workspaceinvite.financial_access`. Convite
  antigo ainda pendente passa a conceder acesso restrito — o lado seguro.
- Respostas mudaram de forma: campos da casa viraram anuláveis no OpenAPI, e o
  frontend precisou parar de fazer `?? 0` (que renderizaria "Casa R$ 0,00").
- `member.updated` entra na lista de eventos de **resync completo** em
  `lib/ws-events.ts`: rebaixar o acesso de alguém tem de esvaziar a tela dele na
  hora, não no próximo F5.
- Testes: `tests/security/test_privacy_matrix.py` cobre
  `papel × acesso × envolvido/não-envolvido` em todas as leituras, e
  `test_read_policy_coverage.py` percorre o router e falha quando aparece um GET
  novo sem política — com uma lista de dispensas explícitas, cada uma com motivo,
  para que ignorar seja uma decisão e não um esquecimento.
- Fica de fora, conscientemente: quem tem compra num cartão alheio ainda vê o
  limite e o total comprometido dele. Separar "usar neste workspace" de "ver a
  fatura inteira" depende de `CardWorkspaceAccess`, da onda de propriedade
  pessoal.
