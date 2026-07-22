# 06 — Redesign das telas principais

Especificação "como deve ficar" das telas de maior uso: **Início**, **Lançamentos**,
**Nova Despesa**, **Cartões/Faturas** e **Relatórios**. Wireframes em ASCII (proporção
ilustrativa), o que muda vs. hoje, e estados. Componentes referenciados vêm do doc 05.

Legenda: `▮` número-herói · `▭` StatTile · `◔` mini-gráfico · `≣` lista/ledger.

---

## 1. Início (`/`) — de "8 cartões" a "resumo que responde"

**Objetivo:** passar no teste dos 2 segundos — _quanto sobra, como estou vs. orçamento,
o que aconteceu por último_. Hoje: 8 cartões redundantes + extrato inteiro (H1). Alvo:

```
┌ PageHeader ──────────────────────────────────────────────────────────┐
│ Início                                   [ ‹ Julho 2026 › ]  [+ Nova despesa] │
│ Olá, Ana — aqui está seu mês.                                          │
└───────────────────────────────────────────────────────────────────────┘

┌ HeroBalance (largura total ou 2/3) ─────────────┐  ┌ Ações rápidas ──┐
│ Sobra do mês                                     │  │  + Despesa       │
│ ▮ R$ 2.104,58        ◔ sparkline dos últimos meses│ │  ↑ Renda         │
│ Você gastou R$ 4.895 de R$ 7.000 previstos       │  │  ⇄ Importar CSV  │
│ [██████████░░░░] 70% do orçamento · 10 dias rest.│  │  ✓ Acertar dívida│
└──────────────────────────────────────────────────┘  └──────────────────┘

┌ Linha de métricas (3–4 StatTiles, calmas) ───────────────────────────┐
│ ▭ Receita do mês   ▭ Despesa do mês   ▭ A receber/pagar  ▭ Fatura aberta│
│   +R$ 9.050          −R$ 4.895           você deve R$ 80    R$ 1.028 · vence 7 │
└───────────────────────────────────────────────────────────────────────┘

┌ Últimos lançamentos (preview do ledger, 5–6) ────────────────────────┐
│ ≣ Hoje                                                                 │
│   🥖 Padaria           Alimentação · dinheiro          −R$ 28,40       │
│   🚗 Uber              Transporte                       −R$ 32,80       │
│ ≣ 20 jul                                                               │
│   🛒 Supermercado      Mercado · cartão                 −R$ 435,90      │
│                                             [ Ver todos os lançamentos →]│
└───────────────────────────────────────────────────────────────────────┘

┌ Para onde foi (mini CategoryBreakdown do mês) ──── opcional, 1/2 ─────┐
│ Moradia    ██████████ R$ 2.287                                         │
│ Mercado    ████ R$ 435   Alimentação ███ R$ 176  …   [Ver relatório →] │
└───────────────────────────────────────────────────────────────────────┘
```

**O que muda:**
- **HeroBalance** substitui "Previsão/Gasto/Saldo/Orçamento". Mostra a **resposta**
  ("sobra R$ 2.104") + progresso de orçamento + sparkline. É o único elemento "grande".
- Some o cartão **"Membro / Ana"** e o **"Novo Registro"** (duplicava o botão). "+ Nova
  despesa" vive no header; ações extras num bloco discreto de _quick actions_.
- **Métricas calmas** (StatTile): receita, despesa, saldo a acertar, fatura aberta — cada
  uma com `MoneyText` correto (despesa **vermelha** com `−`, receita verde com `+`).
- Extrato completo **sai** do Início (vai para `/transactions`); aqui fica só um **preview**
  de 5–6 com "Ver todos". Início deixa de ser uma página infinita.
- **"Minha parte vs. casa"** (bom conceito atual) aparece como _hint_ do StatTile de
  despesa ("sua parte · casa R$ X"), não como dois cartões.
- Sem bordas coloridas, sem `font-black`, sem uppercase. Um número grita; o resto sussurra.

**Estados:** usuário novo → HeroBalance vira _onboarding card_ ("Registre renda e o
primeiro gasto para ver seu resumo") com CTA; extrato vazio → `EmptyState`.

---

## 2. Lançamentos (`/transactions`) — o ledger completo (P4)

Promovido do interior do dashboard a página própria. É o extrato de verdade: busca,
filtros, período, paginação, export — tudo o que hoje está espremido no header da tabela.

```
┌ PageHeader ──────────────────────────────────────────────────────────┐
│ Lançamentos                              [ ‹ Julho 2026 › ]  [+ Nova despesa] │
│ Tudo que entrou e saiu.                                                │
└───────────────────────────────────────────────────────────────────────┘

┌ Barra de filtros (única, calma) ─────────────────────────────────────┐
│ 🔎 Buscar…      [Categoria ▾] [Pagamento ▾] [Tag ▾]   ⌗ Fixos  ⤓ Export │
└───────────────────────────────────────────────────────────────────────┘

┌ Resumo do filtro ────────────────────────────────────────────────────┐
│ 17 lançamentos · saídas −R$ 4.895 · entradas +R$ 9.050                 │
└───────────────────────────────────────────────────────────────────────┘

≣ TransactionLedger (agrupado por dia)
  Hoje ─────────────────────────────────────────── subtotal −R$ 61,20
    🥖 Padaria            Alimentação · dinheiro              −R$ 28,40  ⋯
    🚗 Uber para o trabalho  Transporte                        −R$ 32,80  ⋯
  20 jul ────────────────────────────────────────── subtotal −R$ 435,90
    🛒 Supermercado Pão de Açúcar  Mercado · cartão · 👥        −R$ 435,90  ⋯
  …
                                             ‹ 1 2 3 ›  ·  10 por página
```

**O que muda vs. `TransactionHistory` atual:**
- Vira **ledger agrupado por dia** com subtotal por dia — muito mais escaneável que a
  tabela plana com "15:00" repetido.
- **Glifo de categoria** à esquerda (cor da categoria) no lugar do texto uppercase 10px.
- Valores com **cor/sinal corretos** (`MoneyText`) — fim do "tudo verde".
- Ações `⋯` (menu) por linha, acessível por foco/teclado e no mobile — não só hover.
- **Fixos/recorrentes**: um toggle/aba "Fixos" mostra os templates de recorrência aqui
  (contexto certo), com "lançar pendentes".
- Filtros numa barra única; período no header (`PeriodPicker` global).
- Mobile: cada lançamento vira **card** (via `DataTable`/`CardList`); filtros num sheet.

**Editar/excluir:** mantêm `TransactionDialog` atual (reusa `TransactionForm`), só
reestilizado. RBAC preservado (viewer não vê `⋯`).

---

## 3. Nova Despesa (modal) — refinar o que já é bom

Já é o melhor fluxo do app (`nova-despesa-modal-light.png`). **Não reinventar** — só
alinhar ao sistema e melhorar detalhes.

```
┌ Dialog · "Nova despesa" ─────────────────────────────── ✕ ┐
│ Título / Descrição            Valor total                  │
│ [ Ex: Mercado            ]    [ R$ 0,00        ]           │
│                                                            │
│ Quem pagou?          Data                                  │
│ [ Ana Martins ▾ ]    [ 22/07/2026 ]                        │
│                                                            │
│ Forma de pagamento                                         │
│ [ Não informado ▾ ]                                        │
│                                                            │
│ Dividir com   ● Ana Martins   ○ + adicionar                │
│                                                            │
│ ▸ Opções avançadas (categoria · % / fixo · por item · tags · parcelas) │
│ ─────────────────────────────────────────────────────────  │
│                                    [ Cancelar ] [ Salvar ] │
└────────────────────────────────────────────────────────────┘
```

**Ajustes:**
- Estilo alinhado ao sistema (tipografia calma, `--radius-lg`, foco de marca). Botão
  "Salvar despesa" primário de marca (hoje já é sólido — só trocar o preto/azul pela marca).
- **Tags** e **Categoria** movidas para dentro de "Opções avançadas" para o caso simples
  ficar ainda mais curto (categoria pode subir se dados mostrarem que é muito usada).
- Selects (pagamento/categoria) via **Radix Select** único (05 §8) — remove o `<select>`
  nativo de contorno.
- Mobile: vira **bottom sheet** com o mesmo conteúdo; teclado numérico no valor.
- Feedback de erro/sucesso já existe (banner + check) — manter, realinhar cor.
- Micro-melhoria: ao escolher "Cartão de crédito", mostrar de qual cartão/fatura vai cair
  (usa a derivação server-side que já existe).

---

## 4. Cartões & Faturas (`/cards`) — dar cara de cartão (H6)

Hoje: caixa com borda + faturas exigem clique ("Selecione um cartão"). Alvo:

```
┌ PageHeader · Cartões                              [+ Novo cartão] ─────┐

┌ CreditCardVisual ─────────────┐  ┌ CreditCardVisual (+) ─────────────┐
│  NUBANK ULTRAVIOLETA          │  │        + Adicionar cartão         │
│                               │  │   Acompanhe limite e faturas      │
│  Disponível                   │  └───────────────────────────────────┘
│  ▮ R$ 10.971,70               │
│  [████░░░░░░] 9% do limite    │      (cartão selecionado = anel marca)
│  Limite R$ 12.000 · fecha 28 · vence 7 │
└───────────────────────────────┘

┌ Fatura de Julho · Nubank ────────────────── [Aberta] ── total R$ 1.028,30 ┐
│ Fecha em 28 jul · vence em 7 ago                    [ Fechar fatura ]  │
│ ≣ lançamentos da fatura (ledger compacto)                              │
│   iFood            Alimentação                        −R$ 68,50        │
│   Amazon.com.br    Geral                              −R$ 239,90       │
│   Posto Shell      Transporte                         −R$ 300,00       │
│   Zara             Geral                              −R$ 419,90       │
│ ── faturas anteriores ───────────────  [ Julho ] [ Junho ] [ Maio ] … │
└───────────────────────────────────────────────────────────────────────┘
```

**O que muda:**
- **`CreditCardVisual`**: proporção de cartão, gradiente na cor do cartão, "disponível"
  como herói, barra de uso do limite, datas como metadado. Vira um objeto reconhecível.
- **Auto-seleção do 1º cartão** → a fatura já aparece (mata "Selecione um cartão acima").
- Fatura como **ledger compacto** + cabeçalho com status (`StatusPill`: Aberta/Fechada/
  Paga/Vencida) e ação contextual (Fechar/Pagar/Reabrir — endpoints já existem).
- Navegação entre meses de fatura por chips/`PeriodPicker`.
- Mobile: cartões em carrossel horizontal; fatura empilhada.

---

## 5. Relatórios (`/reports`) — consertar e focar (B3/B4/H1)

Hoje: 4 métricas (repetem o Início) + 4 abas, com **tooltip preto no claro** e **abas
quebradas** (`relatorios-light.png`). Alvo: menos repetição, gráficos temáticos, foco em
_insight_.

```
┌ PageHeader · Relatórios                 [ ‹ Julho 2026 › ] ───────────┐
│ Para onde vai seu dinheiro.                                            │

┌ Segmented control (abas de verdade, visíveis) ───────────────────────┐
│ [ Visão geral ] [ Categorias ] [ Fluxo ] │  (Orçamento vira /budget) │
└───────────────────────────────────────────────────────────────────────┘

VISÃO GERAL
┌ TrendChart · Receitas × Despesas (6 meses) ──────────────────────────┐
│   (área/linha, cores de --chart-*, tooltip TooltipCard temático)      │
│   < 2 meses de dados → "Coletando dados: volte mês que vem" (B4)      │
└───────────────────────────────────────────────────────────────────────┘
┌ 3 destaques do mês ──────────────────────────────────────────────────┐
│ Maior categoria: Moradia R$ 2.287 · Dia mais caro: 20 jul · Ticket médio R$ 288 │
└───────────────────────────────────────────────────────────────────────┘

CATEGORIAS
┌ CategoryBreakdown (barras horizontais ordenadas) ── + tabela detalhe ─┐
│ Moradia     ██████████████ R$ 2.287  (47%)                            │
│ Mercado     ████ R$ 435 (9%) …        [donut opcional]                │
└───────────────────────────────────────────────────────────────────────┘

FLUXO
┌ Fluxo de caixa acumulado (linha) ────────────────────────────────────┐
```

**O que muda:**
- **Gráficos via wrappers temáticos** (`TrendChart`, `CategoryBreakdown`, `TooltipCard`,
  `ChartTheme`) que leem tokens → **funcionam no claro e no escuro** (fim do tooltip preto,
  grid visível).
- **Abas viram segmented control visível** (corrige o layout quebrado das abas).
- **Orçamento** sai daqui e vira `/budget` (04). Remove a 4ª aba escondida.
- Métricas do topo deixam de repetir o Início; viram **destaques de insight** ("maior
  categoria", "dia mais caro", "ticket médio").
- Barras horizontais no lugar da pizza para comparar categorias (mais legível); pizza/donut
  como opção.
- Estado "pouca história" tratado (não mais 1 barra perdida em 6 meses vazios).

---

### Resumo do impacto (telas principais)

| Tela | Mudança-chave | Resolve |
|------|---------------|---------|
| Início | HeroBalance + métricas calmas; extrato vira preview | H1, H2, B1, B2 |
| Lançamentos | Página própria; ledger por dia; ações acessíveis | H4, P4, B1 |
| Nova Despesa | Refino (já bom); Select unificado; sheet no mobile | H5, dívida UI |
| Cartões | `CreditCardVisual` + auto-seleção + fatura-ledger | H6 |
| Relatórios | Gráficos temáticos + abas visíveis + foco insight | B3, B4, H1 |
