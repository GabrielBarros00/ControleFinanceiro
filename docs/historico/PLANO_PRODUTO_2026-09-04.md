# Plano de execução — reorganização do produto

**Data:** 2026-09-04 · **Base:** `fix/auditoria-ux` (PR #80) · **Origem:** `ANALISE_PRODUTO_2026-09-04.md`

Este é o documento de trabalho: tarefas, arquivos, portões, critérios de aceitação,
validação e auditoria pós-implementação. Cada tarefa tem um id estável (`O0-1`, `O1-3`…)
para ser citada em commit, PR e checklist.

## Como ler

- **Portão** = um teste automatizado que **falha antes** e passa depois. Toda tarefa que
  muda comportamento tem um; onde não tem, está dito por quê.
- **Validação** = o que conferir com o produto rodando, além do portão.
- **Risco** = o que pode quebrar em silêncio, e como perceber.
- **Depende de** = ordem obrigatória.

## Regras que valem para o plano inteiro

1. **O portão vem primeiro e tem de falhar.** Escrever o teste, ver vermelho, corrigir, ver
   verde. Um teste que nasce verde não provou nada — foi assim que a auditoria descobriu
   que o gate de truncamento passava numa tela quebrada.
2. **Uma onda por PR.** Ondas 0 e 1 podem ir juntas; da 2 em diante, um PR cada.
3. **Nenhuma onda fecha com portão vermelho ou pulado.**
4. **Toda mudança de resposta da API exige `npm run typegen`** e o `api.gen.ts` commitado —
   o job `typegen` do CI reprova o diff.
5. **Auditoria pós-implementação por onda** (seção 10), não só no fim.

---

# Onda 0 — Confiança: a projeção precisa dizer a verdade

**Objetivo:** a primeira tela parar de mentir sobre o futuro.
**Por que primeiro:** enquanto a projeção somar 12 parcelas onde vence 1, todo trabalho de
layout naquela tela é polir o número errado.
**Esforço:** 1–2 dias · **Risco:** baixo · **PR:** um, junto com a Onda 1.

## O que está errado, em uma frase

Três consultas somam tudo o que vence **até** o fim do mês, sem piso inferior — e "não
paga" é o estado padrão de toda parcela que o app gera sozinho.

| Fonte | Arquivo | Sintoma |
|---|---|---|
| Parcelas de financiamento | `backend/app/services/projection_service.py:209` | `due_date <= fim_do_mes`, sem piso |
| Faturas de cartão | `backend/app/services/projection_service.py:168` | `due_date <= fim_do_mes`, sem piso |
| Contas a pagar | `projection_service.py:79` usa `payables_total` | esse total **inclui** o atrasado |

Medido: conta com R$ 10.000, **um** financiamento começado há 12 meses, nada marcado como
pago → "A pagar −R$ 43.140,00" e "Saldo projetado −R$ 33.140,00". O certo seria uma parcela
(~R$ 3.595) e ~+R$ 6.400.

## A decisão de produto (precisa da sua palavra antes de codar)

O que "Até o fim do mês" deve significar?

- **(A) Recomendada — separar.** A projeção olha **de hoje até o fim do mês**. O que venceu
  antes vira uma linha própria, "Vencido", como a tela **Contas a pagar já faz**
  (`payables_service.py` já calcula `overdue_total` e `due_this_month_total` separados —
  é copiar o padrão da casa, não inventar).
  *Consequência:* o saldo projetado passa a responder "se eu pagar o que vence este mês,
  quanto sobra" — e o atraso aparece como dívida, não como previsão.
- **(B) Somar tudo, avisando.** Mantém o número atual e acrescenta "inclui R$ X vencido".
  Mais barato, mas continua entregando um saldo projetado que não descreve o mês.
- **(C) Só o mês corrente, ignorando o atraso.** Simples e **errado**: esconder dívida
  vencida num app de finanças é pior que exagerá-la.

> **Escolha padrão deste plano: (A).** Se você preferir (B), as tarefas O0-2 e O0-3 mudam;
> O0-1 e O0-4 valem igual.

## Tarefas

### `O0-1` — Portão: a projeção não conta o passado

- **Arquivo:** `backend/tests/api/test_projecao_horizonte.py` (novo)
- **Casos:**
  1. financiamento iniciado há 12 meses, nada pago → `breakdown` de financiamento tem
     `count == 1` e `amount` = uma parcela;
  2. fatura fechada e não paga com vencimento no mês passado → não entra em `payable_total`;
  3. conta a pagar vencida → não entra em `payable_total`;
  4. **controle positivo:** parcela que vence **neste mês** continua entrando (senão a
     correção vira "sumiu tudo" e o teste não perceberia).
- **Aceite:** falha hoje nos casos 1–3 e passa no 4.
- **Risco:** o caso 4 é o que impede a correção de virar exclusão cega.

### `O0-2` — Piso inferior nas três fontes

- **Arquivos:** `backend/app/services/projection_service.py` (`_parcelas`, `_faturas`, e a
  linha de `payables`)
- **Como:** usar `hoje` como piso; para contas a pagar, trocar `payables_total` por
  `due_this_month_total` (já existe).
- **Depende de:** O0-1 vermelho.

### `O0-3` — "Vencido" como linha própria da projeção

- **Arquivos:** `backend/app/schemas/balance.py` (`ProjectionRead` ganha `overdue_total`;
  `ProjectionLine.kind` ganha `overdue`), `projection_service.py`,
  `frontend/src/components/dashboard/SaldoEProjecao.tsx`
- **Regra de UI:** o atrasado **não** entra em "Saldo projetado"; aparece como aviso
  acionável acima dos KPIs, com link para Contas a pagar.
- **Obrigatório:** `npm run typegen` + `api.gen.ts` commitado.
- **Portão:** `O0-1` estendido — `overdue_total` reflete o que ficou de fora.

### `O0-4` — "Marcar parcelas anteriores como pagas"

- **Por que:** sem isto o dado nasce errado em todo contrato antigo, e a pessoa não tem como
  saber por quê. É a correção da **causa**; O0-2 corrige o **efeito**.
- **Arquivos:** `backend/app/api/routes/me_financing.py` (rota de quitação em lote),
  `backend/app/services/financing_service.py`,
  `frontend/src/components/financing/AmortizationTable.tsx`
- **UX:** ao cadastrar um financiamento com `start_date` no passado, o diálogo de sucesso
  pergunta: *"Este contrato começou em <mês>. As <N> parcelas até hoje já foram pagas?"* —
  com "Sim, marcar como pagas" e "Não, estão em aberto".
- **Portão:** `backend/tests/api/test_financing_quitacao_em_lote.py` — marca N parcelas,
  confere idempotência (chamar duas vezes não muda nada) e que parcelas futuras não são
  tocadas.
- **Risco:** ação em massa e irreversível pela interface. Mitigação: confirmação nomeando o
  período e a quantidade; a operação **não** cria movimento de caixa retroativo (senão
  reescreve o passado do extrato — ADR 0023 proíbe).

### `O0-5` — Compromissos: mostrar a próxima parcela **de verdade**

- **Arquivos:** `backend/app/services/overview_service.py:603` (`next_due_date` pega
  `em_aberto[0]`, que pode ser de um ano atrás), `frontend/src/pages/CommitmentsPage.tsx`
- **Mudança:** `next_due_date` passa a ser a próxima **a partir de hoje**; quando há
  atraso, a linha diz "N parcelas vencidas" com destaque.
- **Bônus da mesma tela:** o valor à direita hoje é o saldo devedor do contrato inteiro
  (R$ 1.250.000 numa tela chamada "a vencer"). Passa a ser **a próxima parcela**, com o
  saldo devedor como linha de apoio.
- **Portão:** `backend/tests/api/test_compromissos_proxima_parcela.py`.

## Validação da onda 0

1. Reproduzir o cenário medido (conta R$ 10.000 + financiamento de 12 meses atrás) e
   conferir: "A pagar" ≈ uma parcela, "Saldo projetado" positivo, aviso de vencido visível.
2. Conferir a conta semeada por `npm run shots`: "Vencido −R$ 423.052,57" sai da projeção e
   aparece como atraso.
3. `pytest` completo (SQLite **e** PostgreSQL — o leg `backend-postgres` do CI).
4. `npm run typegen` sem diff.

---

# Onda 1 — Ruído: o que dá para consertar sem decidir nada

**Objetivo:** tirar da frente tudo que é claramente errado e não exige decisão de produto.
**Esforço:** 1–2 dias · **Risco:** baixo · **PR:** junto com a Onda 0.

| id | O quê | Arquivo | Portão |
|---|---|---|---|
| `O1-1` | O "×" do diálogo **cobre o valor** (medido: × em 870–910, valor em 806–898, desktop e celular) | `components/ui/dialog.tsx`, `TransactionDetailDialog.tsx` | `e2e/larguras.spec.ts` ganha "nenhum controle sobrepõe texto no diálogo" |
| `O1-2` | Recorrência **não soma os fixos** — é a pergunta da tela | `pages/RecurringTransactionsPage.tsx` | vitest: com 3 recorrências, o total aparece |
| `O1-3` | Coluna "Ações" com cabeçalho e nenhuma ação visível; coluna "ATIVO" com valor sempre igual | idem | vitest |
| `O1-4` | `"(ADR 0022)"` **no subtítulo, para o usuário** | `pages/MyReportsPage.tsx` | grep no lint: proibir `ADR ` em string de UI |
| `O1-5` | Datas ISO cruas ("desde 2026-07-06") | `pages/AccountsPage.tsx` | vitest |
| `O1-6` | "Abrir a **casa**" — vocabulário fora do padrão "espaço" | `pages/MySettlementsPage.tsx` | grep no lint (junto com o de "workspace") |
| `O1-7` | Cores do gráfico contradizem a semântica (consumo roxo, renda verde) e a legenda inverte a ordem do título | `pages/MyReportsPage.tsx`, `Reports/ReportsPage.tsx` | inspeção visual (`npm run shots`) |
| `O1-8` | "Maior categoria: **Sem categoria**" sem convite a categorizar | `Reports/ReportsPage.tsx` | vitest |
| `O1-9` | Chips de origem do Extrato **não mostram estado** | `pages/GlobalLedgerPage.tsx` | vitest: chip ativo tem `aria-pressed` |
| `O1-10` | KPIs de Financiamentos com estilo próprio (caixa alta) em vez de `StatTile` | `financing/AmortizationTable.tsx` | inspeção visual |
| `O1-11` | "Excluir" colado em "+ Novo Financiamento" | idem | inspeção visual |
| `O1-12` | Seletor de financiamento = 330px de chips no celular | idem | `larguras.spec.ts` (altura da tela) |

**Validação:** `npm run shots` + conferência a olho das 6 telas tocadas, nos dois temas.

---

# Onda 2 — A primeira tela vira "Hoje"

**Objetivo:** responder *quanto tenho · o que resolver · como está o mês* sem rolagem, com
uma ação.
**Esforço:** 4–6 dias · **Risco:** médio · **Depende de:** Onda 0 (senão o número mentiroso
vira o destaque da tela nova).

## Estado atual, medido

Seis blocos, ~14 números, **2.475px** (conta vazia) a **3.064px** (dados reais) de altura no
celular. O saldo aparece **três vezes**. "Saldo projetado" é a aritmética dos outros três
KPIs. Nenhum botão.

## Alvo

```
Hoje
├── Saldo .................. um número + link "ver contas"
├── Precisa de você ........ vencidos + o que vence em 7 dias, com "Pagar"
│                            (some quando está tudo em dia → "Tudo em dia ✓")
├── Este mês ............... uma linha: gastei X de Y previsto (barra)
└── Últimos movimentos ..... 5 linhas + "ver extrato"
```

## Tarefas

- `O2-1` **Portão de densidade**: `e2e/larguras.spec.ts` ganha teto de altura por rota —
  `/overview` ≤ **1.400px** a 390px. Falha hoje (2.475px).
- `O2-2` Extrair `SaldoEProjecao` para **um número + previsão em uma linha**; a lista de
  contas sai (já existe em `/me/accounts`).
- `O2-3` Novo bloco **"Precisa de você"**, alimentado por `payables` + `overdue` (a Onda 0
  já separou), com ação de liquidar em lote.
- `O2-4` "Resultado do mês" e "Caixa do mês" viram **uma linha** com link para Relatórios.
- `O2-5` "Por espaço" e "Onde você está envolvido" saem da primeira tela (viram seções do
  Extrato/Relatórios).
- `O2-6` Estado "tudo em dia": quando não há pendência, dizer isso — hoje a tela mostra
  zeros.

**Riscos:** (a) remover informação que alguém usa; mitigação: nada é apagado, tudo ganha
link. (b) o gate de altura pode virar camisa de força; por isso é **por rota** e com folga.

**Validação:** altura ≤ 1.400px; 1 ação primária visível sem rolar em 390×844 e 1366×768;
`npm run shots` conferido.

---

# Onda 3 — O formulário mais usado

**Objetivo:** lançar um café sem precisar ler catorze controles.
**Esforço:** 3–5 dias · **Risco:** médio (é o formulário com mais testes) · **Depende de:** —

**Medido, no celular:** o lançamento simples já custa **4 toques e nenhuma rolagem** — a
mecânica está resolvida. O que sobra é **volume**: 14 controles visíveis e 9 rótulos para
preencher dois campos. O alvo desta onda é o que a pessoa precisa ler, não quantas vezes
ela toca.

- `O3-1` **Portão**: `e2e/nova_despesa.spec.ts` (novo) — no modo simples, o formulário
  expõe **no máximo 5 controles visíveis**. Falha hoje (14).

  > **Cuidado com a métrica errada.** O primeiro portão que escrevi aqui era "lançar em ≤ 4
  > toques" — e ao medir, o app **já faz em 4 toques, sem rolagem** (o rodapé fixo do PR #80
  > resolveu o que faltava). O portão teria nascido verde, violando a regra 1 deste plano.
  >
  > O problema da tela não é quantos toques ela custa: é **quanto ela obriga a ler antes de
  > achar os dois campos que importam**. Por isso a régua é a quantidade de controles à
  > vista, que é o que de fato pesa em quem abre o formulário dez vezes por dia.
- `O3-2` Modo simples: **título + valor + salvar**. Pagador (você), data (hoje), espaço (o
  atual) e "já foi paga" ficam implícitos e aparecem em "detalhar".
- `O3-3` "Detalhar" abre o formulário atual **inteiro**, sem perder o que foi digitado.
- `O3-4` **"Salvar e lançar outro"** — mantém o modal aberto, limpa os campos, foca o
  título.
- `O3-5` **"Duplicar"** no detalhe do lançamento.
- **Não mexer:** validação inline, erro do servidor inline, trava de duplo clique, rodapé
  fixo. Estão certos (auditoria) e têm teste.

**Risco alto de regressão:** `SplitEntryForm`, `ItemsEditor`, `PayersEditor` e
`NewTransactionAttachments` têm ~40 testes. Rodar `npx vitest run src/components/dashboard`
a cada passo.

---

# Onda 4 — Busca, desfazer e lote

**Objetivo:** as três capacidades que faltam e que nenhum layout substitui.
**Esforço:** 5–7 dias · **Risco:** baixo–médio

- `O4-1` **Busca global** — backend: rota que varre lançamentos, rendas, acertos e faturas
  do usuário, respeitando `access_policy` (⚠️ **é aqui que se vaza dado**: a busca tem de
  passar pelo mesmo filtro de visibilidade das listas; o portão é obrigatório).
  **Portão:** `backend/tests/security/test_busca_respeita_visibilidade.py` — não-membro e
  `viewer` não veem o que não podem ver. Sem esse teste, a tarefa não entra.
- `O4-2` Busca na interface: campo no cabeçalho, `⌘K`/`/` no desktop, resultados agrupados.
- `O4-3` **"Desfazer" nos toasts** de exclusão (o backend já tem soft-delete). 5s, um clique.
  **Portão:** e2e — excluir, desfazer, a linha volta.
- `O4-4` **Categorizar em lote** no Extrato/Lançamentos (seleção múltipla + aplicar
  categoria). Ataca o "Maior categoria: Sem categoria".

---

# Onda 5 — A arquitetura (escopo vira filtro)

**Objetivo:** de 20 itens de menu para 9, eliminando os quatro pares homônimos.
**Esforço:** 8–12 dias · **Risco: ALTO** · **Depende de:** Ondas 0–4 estáveis

> **Esta onda não começa sem um ADR aprovado.** Ela contradiz a estrutura do ADR 0020, que
> foi decidida com motivo. O ADR novo (**0035 — escopo como filtro, não como rota**) precisa
> dizer: por que o eixo pessoal × compartilhado continua existindo, por que ele sai da
> navegação, e o que acontece com os links salvos.

- `O5-1` **ADR 0035** escrito e aprovado. *Nada mais desta onda começa antes.*
- `O5-2` Portão de compatibilidade: **toda rota antiga responde** — `/w/:id/debts` →
  `/acertos?espaco=:id` etc. Um teste que percorre a lista de rotas legadas e afirma que
  nenhuma dá 404 nem tela em branco. (O app já tem precedente: os aliases de `/transactions`.)
- `O5-3` Fundir **Acertos** (a tela pessoal absorve a do espaço, com filtro).
- `O5-4` Fundir **Relatórios**.
- `O5-5` Fundir **Contas a pagar** (e absorver **Compromissos** como filtro).
- `O5-6` **Extrato absorve Lançamentos** — filtro de regime (caixa × competência) em vez de
  duas telas.
- `O5-7` Reescrever `nav-items.ts` e a gaveta "Mais".
- `O5-8` **Painel do espaço**: decidir remover ou renomear para o nome do espaço.

**Riscos e mitigação**
- *Link salvo quebrado* → O5-2 é pré-requisito, não acabamento.
- *Perda de significado* (competência × caixa vira um `select` que ninguém entende) → o
  filtro precisa de rótulo em português ("o que aconteceu" × "o que saiu da conta"), não
  do jargão contábil.
- *Regressão silenciosa de visibilidade* → cada tela fundida passa a receber dados de dois
  escopos; rodar `tests/security/test_varredura_de_vazamento.py` a cada fusão.

---

# Onda 6 — Onboarding

**Objetivo:** o primeiro minuto entregar valor em vez de pedir dados.
**Esforço:** 2–3 dias · **Risco:** médio · **Depende de:** Onda 2

- `O6-1` Passo único: **"Quanto você tem hoje, e onde?"** — cria a primeira conta com saldo
  de abertura. É o dado que a primeira tela precisa e o único que o onboarding não pedia.
- `O6-2` Renda e cartão saem do onboarding e viram **convite em contexto** (ao abrir Rendas
  ou Cartões vazios pela primeira vez).
- `O6-3` Portão: conta nova → `/overview` mostra saldo de verdade, sem "Saldo ainda não
  configurado".
- **Cuidado:** `e2e/full_flow.spec.ts` e `split_by_item.spec.ts` usam o onboarding para
  semear. Vão precisar de ajuste — **no mesmo PR**.

---

# 7. Portões novos por onda (resumo)

| Onda | Portão | Arquivo | Falha antes? |
|---|---|---|---|
| 0 | Projeção não conta o passado | `tests/api/test_projecao_horizonte.py` | **sim** |
| 0 | Quitação em lote idempotente | `tests/api/test_financing_quitacao_em_lote.py` | sim (rota nova) |
| 0 | Próxima parcela é futura | `tests/api/test_compromissos_proxima_parcela.py` | **sim** |
| 1 | Nada sobrepõe texto no diálogo | `e2e/larguras.spec.ts` | **sim** |
| 1 | Sem "ADR"/"casa" em string de UI | `eslint.config.js` | **sim** |
| 2 | Teto de altura por rota | `e2e/larguras.spec.ts` | **sim** (2.475 > 1.400) |
| 3 | Formulário simples com ≤ 5 controles à vista | `e2e/nova_despesa.spec.ts` | **sim** (14 hoje) |
| 4 | Busca respeita visibilidade | `tests/security/test_busca_respeita_visibilidade.py` | sim (rota nova) |
| 4 | Desfazer devolve a linha | `e2e/desfazer.spec.ts` | sim |
| 5 | Toda rota antiga responde | `e2e/rotas_legadas.spec.ts` | sim |

---

# 8. Checklist de execução

**Onda 0** — [ ] O0-1 · [ ] O0-2 · [ ] O0-3 · [ ] O0-4 · [ ] O0-5 · [ ] decisão (A/B/C) registrada
**Onda 1** — [ ] O1-1 … [ ] O1-12
**Onda 2** — [ ] O2-1 … [ ] O2-6
**Onda 3** — [ ] O3-1 … [ ] O3-5
**Onda 4** — [ ] O4-1 · [ ] O4-2 · [ ] O4-3 · [ ] O4-4
**Onda 5** — [ ] O5-1 (**ADR**) · [ ] O5-2 … [ ] O5-8
**Onda 6** — [ ] O6-1 · [ ] O6-2 · [ ] O6-3

---

# 9. Portões que já existem (rodar em toda onda)

| Comando | O que cobre | Onde roda |
|---|---|---|
| `pytest -q` | 3.099 testes | CI `backend` |
| `TEST_DATABASE_URL=postgres… pytest -q` | corridas e MVCC | CI `backend-postgres` |
| `npm test` | 523 testes | CI `frontend` |
| `npm run typecheck` · `lint` · `build` | tipos, cor crua, manifesto | CI `frontend` |
| `npm run test:e2e` | 59 testes, chromium + mobile | CI `e2e` e `e2e-windows` |
| `npm run typegen` | contrato tipado | CI `typegen` |
| `python scripts/smoke_prod.py` | stack do Compose | CI `prod-stack` |
| `npm run shots` | 129 capturas | manual — **conferir a olho** |

⚠️ **`npm run shots` não roda no CI.** É o único gate que depende de alguém executar — e o
projeto já registrou que "gates que não rodam apodrecem". Conferir a olho ao fim de cada
onda que mexa em tela.

---

# 10. Auditoria pós-implementação

## 10.1 — Por onda (obrigatório antes de fechar o PR)

1. Todos os portões da seção 9 verdes, **mais** os portões novos da onda.
2. `npm run shots` regenerado e **conferido a olho** — claro e escuro, desktop e celular.
   Apagar `backend/shots.db` antes: o catálogo fica verde com dados velhos.
3. Varredura de largura: 24 rotas × 8 larguras (320→1920) — zero rolagem horizontal, zero
   texto espremido, zero erro de console.
4. `axe` (wcag2a/aa + 2.1) em todas as rotas, a 1366 e 390px — **zero violações** (é o
   patamar atual; regressão é inaceitável).
5. Jornada de usuário novo: cadastro → onboarding → primeira despesa → pagar → acertar.
6. Estados: vazio (conta nova), carregando (latência de 3s), erro 500, 401, rede caída.
7. Teclado: Tab do topo até o conteúdo, focus trap, Escape, retorno de foco.
8. **Diário de regressões próprias**: toda vez que um portão pegar um defeito introduzido na
   própria onda, registrar no PR. Foi o que revelou, no PR #80, que o gate passava numa tela
   quebrada.

## 10.2 — Auditoria final (depois da Onda 6)

Repetir a **auditoria completa** com o método da FASE 1, do zero:

- 24+ rotas × 10 larguras, dois temas;
- axe em todas as rotas;
- jornadas de ponta a ponta com três personas (novo, recorrente, desatento);
- estados de erro forçados;
- **em aparelho físico**: barra de status nas 4 combinações de tema, teclado virtual,
  gestos, e o app instalado (desinstalar/reinstalar antes — o WebAPK guarda o manifesto).

**Notas a comparar com a linha de base de hoje:**

| Dimensão | Hoje | Meta |
|---|:--:|:--:|
| UI | 8,0 | ≥ 8,5 |
| UX | 7,5 | **≥ 9,0** |
| Responsividade | 6,5 → (pós-PR #80) | ≥ 8,5 |
| Acessibilidade | 6,0 → 8,5 | ≥ 9,0 |
| Consistência | 6,5 | ≥ 8,5 |
| Clareza | 9,0 | manter |
| Eficiência | 7,0 | **≥ 9,0** |
| Mobile | 5,5 | ≥ 8,5 |
| Geral | 7,5 | **≥ 8,8** |

## 10.3 — Métricas objetivas (a régua que não depende de opinião)

| Métrica | Hoje (medido) | Meta |
|---|---:|---:|
| Itens de menu | 20 | ≤ 10 |
| Altura de `/overview` a 390px | 2.475–3.064px | ≤ 1.400px |
| Altura de `/me/payables` a 390px | 7.095px | ≤ 3.000px |
| Controles no formulário de despesa (simples) | 14 | ≤ 5 |
| Toques para lançar despesa simples | **4** (medido, já no alvo) | manter ≤ 4 |
| Telas que mostram o mesmo saldo | 3 | 1 |
| Violações axe | 0 | 0 |
| Rotas com rolagem horizontal (320–1920) | 0 | 0 |

---

# 11. Riscos do plano inteiro

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Onda 5 quebra links salvos | média | alto | `O5-2` é pré-requisito, não acabamento |
| Simplificar esconde função que alguém usa | média | médio | nada é apagado; tudo ganha link. Ondas 2 e 5 exigem conferir cada número removido |
| Onda 3 regride a divisão por item | média | **alto** (é dinheiro) | ~40 testes existentes; rodar a cada passo |
| Busca vaza dado entre espaços | baixa | **crítico** | `O4-1` não entra sem o teste de visibilidade |
| Quitação em lote reescreve o passado | baixa | alto | não gera movimento de caixa retroativo (ADR 0023) |
| O plano vira redesenho | média | médio | seção 9 da análise ("o que eu NÃO recomendo") é parte do plano |
| Perder o que já é bom | média | alto | seção 8 da análise é lista de bloqueio |

---

# 12. Ordem e paralelismo

```
Onda 0 ─┬─ Onda 1        (mesmo PR; 0 antes de 1 no mesmo branch)
        │
        ├─ Onda 3        (independente — pode ir em paralelo)
        │
        └─ Onda 2 ─┬─ Onda 6
                   │
        Onda 4 ────┘      (independente; entra quando houver espaço)

Onda 5 ──── depois de 0–4 estáveis, e só com o ADR 0035 aprovado
```

---

# 13. Decisões que dependem de você

1. **Onda 0:** a semântica de "Até o fim do mês" — **(A)** separar vencido (recomendada),
   (B) somar avisando, (C) ignorar o atraso.
2. **Onda 2:** "Resultado do mês" e "Caixa do mês" saem da primeira tela e viram link.
   Confirma?
3. **Onda 5:** vale escrever o ADR 0035 e encarar a fusão das telas? É a mudança de maior
   ganho e maior risco do plano.
4. **Onda 5, `O5-8`:** o Painel do espaço **some** ou vira "Meu espaço"?
5. **Onda 6:** tirar renda e cartão do onboarding — confirma?

Nenhuma linha de código das Ondas 2, 5 e 6 antes dessas respostas. As Ondas 0, 1, 3 e 4 já
podem começar com o que está aqui.
