# ADR 0017 — Orçamento tem escopo: meta da casa ou meta pessoal

**Status:** aceito (2026-07-29)
**Relacionado:** [0003](0003-politica-de-status-financeiros.md) (política de status),
[0014](0014-consultas-moeda-e-experiencia.md) (consultas e experiência)

## Contexto

`MonthlyEstimate` era sempre do workspace: a soma das metas do mês virava o
`total_budget`, comparado com o gasto total. Só que o app tem **duas noções de
gasto** desde que "minha parte" existe (ver `ReportService.get_summary`):

- **da casa** — `total_expenses`, o valor cheio das despesas do workspace;
- **minha** — `my_expenses`, a soma dos `TransactionSplit` do usuário.

O Início misturava as duas: `HeroBalance` recebia `spent = my_expenses` e
`budget = total_budget`. Num workspace de duas pessoas com rateio igual, a barra
marcava ~50% quando a casa já tinha consumido 100% do orçamento — e a tela de
Relatórios, que compara casa com casa, mostrava **outro percentual para o mesmo
orçamento**, na mesma sessão. Não era um bug de arredondamento: eram duas
perguntas diferentes disputando um único número.

Alinhar o Início à visão da casa resolveria a contradição, mas apagaria a
pergunta que o card faz ("quanto EU já gastei do que planejei"), que é o motivo
de "minha parte" existir.

## Decisão

O orçamento ganha **escopo**, materializado em `MonthlyEstimate.owner_user_id`:

- `NULL` → meta da **casa**, comparada com o gasto total do workspace;
- preenchido → meta **pessoal** daquele membro, comparada com a parte dele.

Consequências do desenho:

1. **O dono entra na chave de unicidade**
   (`uq_estimate_workspace_owner_category_month`): a meta da casa e a meta
   pessoal de cada membro convivem na mesma categoria e no mesmo mês. A
   idempotência da rota passa a chavear por `(workspace, dono, categoria, mês)`.
2. **Meta pessoal é privada.** `GET /estimates` devolve as metas da casa mais as
   do próprio solicitante, nunca a de outro membro; alterar ou remover uma meta
   pessoal exige ser o dono — **inclusive para admin/owner**. Papel manda no
   orçamento da casa; no gasto que outra pessoa planeja para si, não. É a mesma
   linha do e-mail mascarado em `members.list_members`.
3. **A Previsão continua sendo visão da casa.** `total_budget` soma apenas
   `owner_user_id IS NULL`, porque a previsão é projeção de **caixa** (quem paga)
   e não de consumo (quem deve) — a mesma razão registrada em
   `gasto-real-minha-parte`. O endpoint passa a devolver também `my_budget`, que
   é o número do Início.
4. **`my_categories` no resumo.** A meta pessoal por categoria precisa da fatia
   do usuário por categoria, que não existia. Ela é derivada assim:
   - `split_mode='item'` → a share do usuário na linha
     (`TransactionItemShare.computed_amount`) já é exata;
   - `split_mode='transaction'` → a parte do usuário
     (`TransactionSplit.computed_amount`) é rateada entre os itens da despesa em
     **centavos exatos** (`_allocate_proportional`, ADR 0001), então nenhum
     centavo se perde nem se inventa. Na prática também é exato: nesse modo
     existe no máximo o item-categoria único, cujo valor é o total.
5. **`scope` é derivado, não persistido.** Uma coluna ao lado de `owner_user_id`
   seriam duas fontes para o mesmo fato, com chance de discordarem.

## Consequências

- Migração `a3e7b2c94f18` adiciona a coluna e recria o índice. **Sem backfill**:
  todo orçamento existente é da casa, que é o `NULL` que a coluna nova ganha.
- O `downgrade` **apaga** as metas pessoais — sem o dono na chave elas
  colidiriam com a meta da casa da mesma categoria/mês. É perda de dado
  assumida: voltar atrás significa que o escopo deixou de existir.
- Como `owner_user_id` é nullable e NULLs são distintos numa unique, o banco não
  impede duas metas "da casa" para a mesma categoria/mês — a idempotência
  continua sendo da rota, exatamente como já era para `category_id` nulo.
- Fica de fora, conscientemente: **meta pessoal não entra na Previsão**. Somar
  metas de pessoas diferentes ao caixa da casa produziria um orçamento sem
  significado (as partes já estão dentro do total).
