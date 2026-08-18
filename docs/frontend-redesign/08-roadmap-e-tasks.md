# 08 — Roadmap & backlog de tarefas

Plano de execução em fases, do menor risco/maior retorno ao polish. Cada tarefa tem
checkbox e critérios de aceite. As fases são incrementais: o app permanece funcional ao
fim de cada uma (nada de _big bang_). Referências de doc entre parênteses.

**Como usar:** faça a Fase 0 e 1 na ordem (destravam o resto). Da Fase 3 em diante, as
telas podem ser paralelizadas por pessoa, pois todas dependem só de 1 e 2.

> **Status (2026-07-29): Fases 0–5 implementadas e em produção.** As caixas marcadas
> abaixo estão entregues e verificadas (tsc + vitest + screenshots). As sete caixas ainda
> vazias **não são backlog esquecido** — são diferimentos conscientes, com o motivo em
> [Diferido conscientemente](#diferido-conscientemente) no fim do documento. Este bloco
> existe porque o roadmap ficou com 100% desmarcado por semanas depois da entrega, e um
> documento que não distingue "não feito" de "decidido não fazer" não serve para planejar.

> **Rodada de mobile (2026-08-17).** O critério 4 da [Definição de pronto](#definição-de-pronto-por-tela)
> — *"funciona em 375px"* — estava marcado como atendido por inspeção, e não era: quatro
> telas estouravam a largura e **nenhum teste media isso** (um `grep` por `scrollWidth` no
> repositório voltava vazio). O catálogo de capturas cobria cinco rotas no celular, nenhuma
> delas entre as quebradas — um catálogo que fotografa só o que já se sabe estar bom não
> descobre nada.
>
> O que essa rodada fechou, e o que ela deixa como regra daqui para frente:
>
> - o critério 4 passa a ter **portão**: `frontend/e2e/mobile_layout.mobile.spec.ts` mede
>   `document.documentElement.scrollWidth` em TODAS as rotas a **360px** (e não 375: 360 é
>   a largura do Galaxy A e do Moto G, a mais estreita que ainda importa), e nomeia o
>   elemento culpado quando falha;
> - `npm run shots` fotografa **22 telas** no celular, não 5, mais a gaveta "Mais", o
>   seletor de escopo e o formulário de despesa;
> - o **F1.7** (duas libs de UI) segue aberto, mas encolheu: as treze cópias de
>   `selectClass` viraram um `ui/native-select.tsx` só. O padrão "`<select>` nativo dentro
>   de modal" continua vivo, agora num arquivo com o motivo escrito;
> - a navegação foi reescrita — o mapa do doc [04](04-arquitetura-e-navegacao.md) já não
>   descreve o que existe. Ver a nota no topo dele.

---

## Fase 0 — Correções de leitura (quick wins, sem redesign) 🔴

> Objetivo: parar de "contar a história errada". Baixo risco, alto impacto de confiança.
> Pode ir para produção imediatamente, antes de qualquer mudança visual.

- [x] **F0.1 — Corrigir cor de despesa no extrato (B1).** Em `TransactionHistory.tsx`,
  não colorir por `value < 0`; despesa = vermelho, receita = verde, por **tipo** do
  lançamento. (Provisório até o `MoneyText` da Fase 1.)
  <br>_Aceite:_ no extrato semeado, todas as despesas aparecem em vermelho com `−`.
- [x] **F0.2 — Padronizar formatação de moeda (B2).** Criar/usar `formatMoney` e trocar
  o `.toLocaleString` sobre string no card "Previsão" (`BentoDashboard.tsx`) e onde houver.
  <br>_Aceite:_ nenhum valor aparece como "R$ 5449.14"; tudo em "R$ 1.234,56".
- [x] **F0.3 — Tema claro dos gráficos (B3).** Trocar `contentStyle` hardcoded e o grid
  branco por cores lidas de CSS var (mesmo que provisoriamente via helper simples) em
  `ReportsPage.tsx`.
  <br>_Aceite:_ no tema claro, tooltip legível (fundo claro) e grid visível.
- [x] **F0.4 — Abas de Relatórios visíveis (B3).** Corrigir o layout/estilo da `TabsList`
  (container vazio + triggers sem realce).
  <br>_Aceite:_ as 4 abas aparecem como controle visível; aba ativa destacada.
- [x] **F0.5 — Gráfico com pouca história (B4).** Mostrar estado "coletando dados" quando
  `< 2` meses; evitar barra de hover gigante em meses vazios.
  <br>_Aceite:_ usuário novo não vê 5 meses vazios com 1 barra perdida.

---

## Fase 1 — Fundação (design system + primitivos) 🧱

> Objetivo: colocar a base dos docs 03 e 05 no repo, sem redesenhar telas ainda.

- [x] **F1.1 — Tokens de cor.** Reescrever `src/index.css` com `:root`/`.dark` do doc 03
  (neutros quentes, marca índigo, semânticas de dinheiro/feedback, chart-1..6) + mapa de
  compat com os nomes shadcn atuais.
  <br>_Aceite:_ app inteiro continua renderizando; `--primary` aponta para `--brand`.
- [x] **F1.2 — Tailwind semântico.** Estender `tailwind.config.js` com `surface`, `text`,
  `text-muted`, `brand`, `income`, `expense`, `warning`, `chart-*`, raios e sombras.
- [x] **F1.3 — Tipografia.** Classe `.tabular` (tabular-nums); escala de tipos (03 §2.2)
  como utilitários/config; remover `font-black` default (buscar e substituir por 600).
  <br>_Aceite:_ nenhum `font-black`/`uppercase tracking-widest` como rótulo padrão.
  <br>_Corrigido em 2026-07-30:_ o item estava marcado como concluído, mas 24
  ocorrências de `font-black` sobreviveram em Acertos, Compromissos, Importar,
  Recorrência, Financiamentos e no centro de notificações — as telas que não
  foram migradas junto com o `PageHeader`. Agora são `font-semibold`, e o
  aceite vale de verdade.
- [x] **F1.4 — `formatMoney` + `MoneyText`.** Implementar (05 §0/§1) com testes unitários
  (positivo, negativo, string, sinal, hideCents).
  <br>_Aceite:_ `MoneyText kind="expense"` renderiza "−R$ 80,00" em `--expense`.
- [x] **F1.5 — Estados padronizados.** `EmptyState`, `ErrorState`, `Skeleton` presets (05 §4).
- [ ] **F1.6 — Página de tokens (referência viva).** `tokens.md`/Storybook leve com paleta,
  tipos, componentes de dinheiro. (Opcional mas recomendado.)
- [ ] **F1.7 — Consolidar UI kit (decisão).** Migrar `Button`/`Select` de Base UI para a
  base Radix+Tailwind; `Select` único que funciona dentro de Dialog (05 §8).
  <br>_Aceite:_ some o padrão "`<select>` nativo dentro de modal"; um só `Select`.

---

## Fase 2 — App shell & navegação 🧭

> Objetivo: nova casca (doc 04) e navegação que funciona no mobile.

- [x] **F2.1 — `AppShell`.** Extrair de `Layout.tsx`; `max-w-[1200px]`, `useWorkspaceEvents`.
- [x] **F2.2 — `Sidebar` reagrupada.** 4 seções (04 §1); item ativo calmo (tint+barra);
  workspace switcher no **topo**; `UserMenu` no rodapé.
  <br>_Aceite:_ nav agrupada; ativo sem bloco preto/sombra colorida.
- [x] **F2.3 — `WorkspaceSwitcher` acessível.** Radix `DropdownMenu` (remove click-outside
  manual do `Sidebar.tsx`).
- [x] **F2.4 — Mobile: `BottomNav` + FAB + `MoreSheet`.** 5 slots, FAB "+ Novo" abre Nova
  Despesa; "Mais" abre sheet com o resto + troca de workspace.
  <br>_Aceite:_ em 375px de largura, dá para navegar e abrir Nova Despesa pelo polegar.
- [x] **F2.5 — `PageHeader` + `PeriodPicker`.** Padrão único (04 §3/§4); `?month=` na URL.
  <br>_Aceite:_ trocar o mês no header reflete no conteúdo e sobrevive a reload.
- [x] **F2.6 — `Dialog`/`Sheet` responsivos.** Dialog vira bottom sheet abaixo de `md`.

---

## Fase 3 — Telas core 🎯

> Objetivo: as telas de maior uso no novo padrão (doc 06). Dependem só de 1 e 2.

- [x] **F3.1 — `TransactionItem` + `TransactionLedger`.** Agrupado por dia, glifo de
  categoria, `MoneyText`, ações `⋯` acessíveis, avatares de divisão, RBAC. (06 §2)
  <br>_Aceite:_ extrato escaneável; despesa vermelha; ações por teclado e no mobile.
- [x] **F3.2 — `DataTable` + `CategoryGlyph` + `StatusPill`.** Base reusável, com
  `CardList` responsivo. (05 §3)
- [x] **F3.3 — Página `Lançamentos` (`/transactions`).** Mover o extrato do dashboard;
  filtros em barra única; período no header; export; "Fixos" (recorrência de despesa). (06 §2)
- [x] **F3.4 — `StatTile` + `HeroBalance` + `BudgetBar`.** (05 §3, 06 §1)
- [x] **F3.5 — Novo `Início` (`/`).** HeroBalance + linha de métricas + preview de extrato +
  mini-breakdown; remover os 8 cartões e o "Membro/Novo Registro". (06 §1)
  <br>_Aceite:_ passa no "teste dos 2 segundos"; sem valores redundantes; 1 número-herói.
- [x] **F3.6 — Refino do modal Nova Despesa.** Alinhar ao sistema; `Select` único; sheet no
  mobile; mover Tags/Categoria p/ avançado; mostrar fatura de destino ao usar cartão. (06 §3)

---

## Fase 4 — Telas restantes 🗂️

> Objetivo: aplicar o padrão a todo o resto (docs 06 §4-5 e 07). Paralelizável.

- [x] **F4.1 — Cartões/Faturas.** `CreditCardVisual`, auto-seleção do 1º, fatura como
  ledger + `StatusPill` + ações (fechar/pagar/reabrir). (06 §4)
- [x] **F4.2 — Gráficos temáticos.** `ChartTheme`, `TrendChart`, `CategoryBreakdown`,
  `Sparkline`, `TooltipCard` (05 §6) e reconstruir `Relatórios` com abas visíveis. (06 §5)
- [ ] **F4.3 — Orçamento (`/budget`).** Promover de aba a página; `BudgetBar` por categoria. (04)
- [x] **F4.4 — Dívidas & Acertos.** "Seu balanço" no topo; dívidas como linha de pessoa;
  manter `MonthlyDebtsSection` e histórico. (07 §2)
- [x] **F4.5 — Rendas + recorrência como aba.** `MoneyText income`, total no header,
  "lançar pendentes" com badge. (07 §1)
- [x] **F4.6 — Financiamentos.** StatTiles + destaque "economia se quitar hoje"; tabela
  compacta + `CardList` mobile. (07 §3)
- [ ] **F4.7 — Importar (wizard).** Stepper 3 passos + presets de banco + drop zone. (07 §4)
- [x] **F4.8 — Configurações.** Alinhar; ícone/cor de categoria; abas mobile via sheet;
  membros/contas no padrão pessoa. (07 §5)
- [x] **F4.9 — Auth (split layout).** Painel de marca + card; consistência entre telas. (07 §6)
- [x] **F4.10 — Onboarding.** Alinhar + preview do `CreditCardVisual`; sheet no mobile. (07 §7)

---

## Fase 5 — Polish & qualidade ✨

- [x] **F5.1 — Motion.** Aplicar durações/easings do doc 03 §4; `prefers-reduced-motion`;
  remover "pulos" de hover.
- [x] **F5.2 — QA de temas.** Varrer todas as telas em claro e escuro (script de screenshots
  deste estudo serve de baseline) — zero cor hardcoded, zero contraste ruim.
- [x] **F5.3 — Acessibilidade.** Foco visível em tudo; alvos ≥40px no mobile; auditar com
  axe; navegação por teclado no ledger/tabelas.
  <br>_Feito:_ `frontend/e2e/a11y.spec.ts` roda no gate de e2e sobre onboarding,
  Início global, painel do workspace, o formulário de Nova Despesa (com as opções
  avançadas abertas) e Relatórios. _Aceite:_ zero violações WCAG 2 A/AA nessas telas.
- [ ] **F5.4 — Densidade compacta** (opcional) em tabelas longas (faturas/parcelas).
- [ ] **F5.5 — ⌘K command palette** (nice-to-have): navegar + "nova despesa".
- [x] **F5.6 — Microcópia.** Revisar textos (sentence case, tom calmo, empty states que
  ensinam).

---

## Diferido conscientemente

Decidido **não** fazer nesta rodada — não é backlog perdido. Cada item tem o motivo e o
custo de mudar de ideia depois.

| Item | Por que ficou de fora | O que isso custa hoje |
|---|---|---|
| **F1.6** — página de tokens / Storybook | Marcado como opcional já no plano original; o design system cabe nos docs 03/05 e o app é de uma pessoa só | Nenhum enquanto o time for pequeno |
| **F1.7** — consolidar UI kit (Base UI → Radix) | Rework grande e transversal, com risco de regressão em toda tela, para ganho estético | **É o custo mais real da lista.** Sobrevive o padrão "`<select>` nativo dentro de modal" (o popup do Base UI Select escapa do focus-trap do Radix Dialog), e as variantes `data-*` precisam da forma com colchete no Tailwind v3. Duas convenções a lembrar em cada componente novo |
| **F4.3** — Orçamento como rota `/budget` | Redundante com a aba de Relatórios, que já mostra meta × gasto por categoria | Um clique a mais para chegar ao orçamento |
| **F4.7** — wizard de importação em 3 passos | O formulário atual de Importar funciona ponta a ponta (mapeia colunas, marca duplicata, decide por linha) | Primeira importação é mais árida que poderia ser |
| **F5.4** — densidade compacta | Só compensa em tabelas muito longas (faturas/parcelas), que hoje cabem na tela | Nenhum |
| **F5.5** — ⌘K command palette | Nice-to-have declarado no próprio plano | Nenhum |

## Riscos & mitigação

| Risco | Mitigação |
|-------|-----------|
| Regressão visual durante migração de tokens | Mapa de compat (F1.1) mantém nomes shadcn; migrar tela a tela |
| Mover extrato p/ `/transactions` quebra links/expectativa | Manter preview no Início com "ver todos"; redirect se necessário |
| Duas UI libs → bugs ao consolidar | F1.7 isolada e testada antes das telas |
| Recharts + temas | Encapsular em wrappers (F4.2); nunca Recharts cru na tela |
| Escopo grande | Fases independentes; Fase 0 já entrega valor sozinha |

## Definição de pronto (por tela)

Uma tela está "redesenhada" quando:
1. Usa `PageHeader` + (se temporal) `PeriodPicker`.
2. Todo valor monetário passa por `MoneyText`/`formatMoney` (cor e sinal corretos).
3. Cobre os 5 estados (loading/empty/error/partial/sem-permissão).
4. Funciona em 375px (tabela→cards, dialog→sheet) e por teclado.
5. Zero cor hardcoded; só tokens. Claro e escuro validados.
6. Sem `font-black`/`uppercase` como rótulo; hierarquia calma.

## Métrica de acompanhamento (antes/depois)
Reusar o roteiro de captura deste estudo (`cd frontend && npm run shots`, fonte em
`frontend/e2e-shots/screenshots.spec.ts`) para gerar o comparativo visual a cada fase —
24 telas, claro+escuro, com dados semeados. O baseline "antes" está em
`docs/frontend-redesign/telas-atuais/`.
