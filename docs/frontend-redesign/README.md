# Estudo de Redesign — Frontend do Controle Financeiro V4

> Estudo completo de reestruturação do frontend: plano de design + engenharia com
> tarefas detalhadas, especificação de como cada tela deve ficar e a base (design
> system) sobre a qual construir.

> **⚠️ Status — leia antes de usar este estudo como plano de trabalho.**
>
> Esta linha dizia "**nada aqui foi implementado**" por muito tempo depois de as
> fases terem sido entregues. Quem lia o índice primeiro concluía que o frontend
> inteiro estava por fazer, e o risco concreto era reimplementar o que já existe.
> O estado real, por camada:
>
> | Camada | Estado | Onde conferir |
> |---|---|---|
> | **Fases 0–5 do roadmap** | **Implementadas e em produção** (29 de 36 caixas) | [`08-roadmap-e-tasks.md`](08-roadmap-e-tasks.md) — é a **fonte da verdade** do que está feito |
> | **7 caixas vazias** | **Diferidas conscientemente**, não esquecidas | seção "Diferido conscientemente" do doc 08 |
> | **Docs 02, 03, 05, 06, 07** | Proposta original; a base (tokens, primitivos, telas) foi construída a partir deles, com desvios registrados no doc 08 | — |
> | **Doc 01 (auditoria)** | **Histórico.** Os bugs de Fase 0 que ele cataloga estão corrigidos | — |
> | **Doc 04 (arquitetura/navegação)** | **Defasado.** A navegação foi reescrita na rodada de mobile (2026-08-17) e o mapa dele já não descreve o que existe | nota no topo do doc 04 |
>
> Regra para as próximas rodadas: uma tarefa entregue vira `[x]` no doc 08 **na
> mesma mudança** que a entrega. Um documento que não distingue "não feito" de
> "decidido não fazer" não serve para planejar.

---

## Em uma frase

Trocar o visual atual — "dashboard SaaS barulhento" (tudo em `font-black`, rótulos
`UPPERCASE`, 8 cartões coloridos redundantes, verde/vermelho neon) — por uma
interface **calma, editorial e centrada no dinheiro**: números como protagonistas,
cor com significado semântico consistente, menos superfícies e mais hierarquia. Algo
que _pareça_ cuidar de finanças (confiável, claro, um toque premium) sem virar mais
um template genérico e sem aumentar a complexidade.

## O problema, resumido

O produto por baixo é rico (divisão por item, faturas, financiamento SAC/PRICE,
acertos multi-membro, recorrência). A casca visual não faz jus a isso e, pior, tem
**bugs de leitura que quebram a confiança** num app de finanças:

- **Toda despesa aparece verde.** A lista colore por sinal (`valor < 0 ? vermelho : verde`),
  mas despesas são gravadas positivas → dinheiro _saindo_ parece dinheiro _entrando_.
  (ver `telas-atuais/dashboard-light.png`)
- **Números formatados de forma inconsistente:** "R$ 5449.14" ao lado de "R$ 4.895,42"
  no mesmo painel (`.toLocaleString` aplicado sobre string vira no-op).
- **Relatórios quebram no tema claro:** abas quase invisíveis e tooltip preto sobre
  fundo branco (cores hardcoded `oklch(0.165 0 0)`). (ver `telas-atuais/relatorios-light.png`)
- **Redundância:** "Gasto Real Atual" = "Sua Despesa" = mesmo valor em 2 cartões;
  cartão "Membro / Ana" ocupa espaço nobre com quase nenhuma informação.

A auditoria completa (com severidade e evidência) está em
[`01-auditoria.md`](01-auditoria.md).

## A proposta, resumida

**Conceito: "Calm Finance / Ledger".** Ver [`02-visao-de-design.md`](02-visao-de-design.md).

1. **O dinheiro é o herói.** Tipografia tabular, uma escala de tipos clara, fim do
   `font-black`/`UPPERCASE` onipresente. Cada valor tem sinal e cor semântica corretos.
2. **Cor com significado, não decoração.** Paleta disciplinada: entrada / saída /
   neutro + uma cor de marca usada com parcimônia. Neutros levemente quentes no lugar
   do preto/branco duro.
3. **Menos superfícies, mais significado.** No lugar de 8 cartões, um "herói" de saldo/
   sobra do mês + uma linha compacta de métricas + gasto vs. orçamento. Divulgação
   progressiva.
4. **Listas antes de widgets.** O extrato (transações) tratado como um _ledger_ bonito
   e escaneável, agrupado por dia, com glifos de categoria e valores tabulares alinhados.
5. **Estrutura consistente.** App shell com header de página padrão, largura máxima,
   estados de loading/empty/error unificados e navegação que funciona no mobile.
6. **Moderno mas simples.** Profundidade suave (1 nível de elevação), 1 escala de raio,
   movimento curto e com propósito, gráficos que respeitam o tema.

## Como este estudo está organizado

Leia na ordem; cada documento assume o anterior.

| # | Documento | O que responde |
|---|-----------|----------------|
| 00 | **README.md** (este) | Visão executiva, índice, sumário do roadmap |
| 01 | [`01-auditoria.md`](01-auditoria.md) | O que existe hoje, tela a tela; catálogo de problemas e bugs com severidade |
| 02 | [`02-visao-de-design.md`](02-visao-de-design.md) | O conceito, a personalidade, princípios de UX financeiro, o que **não** fazer |
| 03 | [`03-design-system.md`](03-design-system.md) | **A base do frontend**: tokens de cor, tipografia, espaçamento, raio, elevação, motion, dark mode |
| 04 | [`04-arquitetura-e-navegacao.md`](04-arquitetura-e-navegacao.md) | Arquitetura de informação, navegação, padrões de página, responsividade, estados |
| 05 | [`05-componentes.md`](05-componentes.md) | Biblioteca de componentes-base a construir/refatorar, com props e comportamento |
| 06 | [`06-telas-principais.md`](06-telas-principais.md) | Redesign detalhado: Início, Lançamentos, Nova Despesa, Cartões, Relatórios |
| 07 | [`07-telas-secundarias.md`](07-telas-secundarias.md) | Redesign detalhado: Rendas/Recorrência, Dívidas/Acertos, Financiamentos, Importar, Configurações, Auth/Onboarding |
| 08 | [`08-roadmap-e-tasks.md`](08-roadmap-e-tasks.md) | Fases de execução, backlog de tarefas com checkboxes e critérios de aceite |

Capturas do estado atual (claro e escuro, 1440×900) em [`telas-atuais/`](telas-atuais/).
Para regenerá-las com dados semeados: `cd frontend && npm run shots` (roteiro em
`frontend/e2e-shots/screenshots.spec.ts`).

## Sumário do roadmap (detalhe e estado caixa a caixa em 08)

Todas as fases abaixo estão **entregues**. O que sobrou de cada uma está no doc 08,
com o motivo do diferimento.

- **Fase 0 — Correções de leitura** ✅: bug do verde, formatação de moeda, tooltip/
  abas do tema claro. (5/5)
- **Fase 1 — Fundação** ✅: tokens e tipografia do design system; primitivos `MoneyText`,
  `PageHeader`, `StatTile`, estados vazios. (5/7 — falta a página de tokens e a
  consolidação do UI kit, ambas diferidas)
- **Fase 2 — App shell & navegação** ✅: nova casca, sidebar reagrupada, header padrão,
  responsivo/mobile. (6/6, mais a rodada de mobile de 2026-08-17)
- **Fase 3 — Telas core** ✅: Início (dashboard), Lançamentos (extrato) e Nova Despesa. (6/6)
- **Fase 4 — Telas restantes** ✅: Cartões/Faturas, Relatórios, Dívidas, Rendas/Recorrência,
  Financiamentos, Importar, Configurações, Auth/Onboarding. (8/10)
- **Fase 5 — Polish** ✅: motion, microinterações, gráficos, acessibilidade, QA de temas. (4/6)

## Princípios que guiam tudo (o "norte")

1. **Clareza acima de densidade acima de beleza** — mas as três importam.
2. **Um número, um significado, uma cor** — consistente em todo o app.
3. **Progressive disclosure** — o simples é padrão; o poderoso fica a um clique.
4. **O tema claro é cidadão de primeira classe** (é onde finanças passam confiança).
5. **Acessível por padrão** — contraste AA, foco visível, alvos ≥ 40px, `prefers-reduced-motion`.
6. **Não reinventar o back-end** — este redesign é de UI/UX; contratos de API permanecem.

## Escopo & premissas

- Stack mantida: React 19 + Vite + TS + Tailwind + Radix/Base UI + React Query +
  Recharts + Framer Motion. O redesign é viável **sem trocar dependências**
  (ver [`03-design-system.md`](03-design-system.md) sobre por que não precisamos de biblioteca nova).
- Sem mudanças de back-end obrigatórias. Onde o design pede um dado novo (ex.: "sobra
  segura do mês"), isso é sinalizado como _opcional / fase futura_.
- Português (pt-BR) como idioma da interface, como hoje.
