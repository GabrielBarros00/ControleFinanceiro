# 08 — Roadmap & backlog de tarefas

Plano de execução em fases, do menor risco/maior retorno ao polish. Cada tarefa tem
checkbox e critérios de aceite. As fases são incrementais: o app permanece funcional ao
fim de cada uma (nada de _big bang_). Referências de doc entre parênteses.

**Como usar:** faça a Fase 0 e 1 na ordem (destravam o resto). Da Fase 3 em diante, as
telas podem ser paralelizadas por pessoa, pois todas dependem só de 1 e 2.

---

## Fase 0 — Correções de leitura (quick wins, sem redesign) 🔴

> Objetivo: parar de "contar a história errada". Baixo risco, alto impacto de confiança.
> Pode ir para produção imediatamente, antes de qualquer mudança visual.

- [ ] **F0.1 — Corrigir cor de despesa no extrato (B1).** Em `TransactionHistory.tsx`,
  não colorir por `value < 0`; despesa = vermelho, receita = verde, por **tipo** do
  lançamento. (Provisório até o `MoneyText` da Fase 1.)
  <br>_Aceite:_ no extrato semeado, todas as despesas aparecem em vermelho com `−`.
- [ ] **F0.2 — Padronizar formatação de moeda (B2).** Criar/usar `formatMoney` e trocar
  o `.toLocaleString` sobre string no card "Previsão" (`BentoDashboard.tsx`) e onde houver.
  <br>_Aceite:_ nenhum valor aparece como "R$ 5449.14"; tudo em "R$ 1.234,56".
- [ ] **F0.3 — Tema claro dos gráficos (B3).** Trocar `contentStyle` hardcoded e o grid
  branco por cores lidas de CSS var (mesmo que provisoriamente via helper simples) em
  `ReportsPage.tsx`.
  <br>_Aceite:_ no tema claro, tooltip legível (fundo claro) e grid visível.
- [ ] **F0.4 — Abas de Relatórios visíveis (B3).** Corrigir o layout/estilo da `TabsList`
  (container vazio + triggers sem realce).
  <br>_Aceite:_ as 4 abas aparecem como controle visível; aba ativa destacada.
- [ ] **F0.5 — Gráfico com pouca história (B4).** Mostrar estado "coletando dados" quando
  `< 2` meses; evitar barra de hover gigante em meses vazios.
  <br>_Aceite:_ usuário novo não vê 5 meses vazios com 1 barra perdida.

---

## Fase 1 — Fundação (design system + primitivos) 🧱

> Objetivo: colocar a base dos docs 03 e 05 no repo, sem redesenhar telas ainda.

- [ ] **F1.1 — Tokens de cor.** Reescrever `src/index.css` com `:root`/`.dark` do doc 03
  (neutros quentes, marca índigo, semânticas de dinheiro/feedback, chart-1..6) + mapa de
  compat com os nomes shadcn atuais.
  <br>_Aceite:_ app inteiro continua renderizando; `--primary` aponta para `--brand`.
- [ ] **F1.2 — Tailwind semântico.** Estender `tailwind.config.js` com `surface`, `text`,
  `text-muted`, `brand`, `income`, `expense`, `warning`, `chart-*`, raios e sombras.
- [ ] **F1.3 — Tipografia.** Classe `.tabular` (tabular-nums); escala de tipos (03 §2.2)
  como utilitários/config; remover `font-black` default (buscar e substituir por 600).
  <br>_Aceite:_ nenhum `font-black`/`uppercase tracking-widest` como rótulo padrão.
- [ ] **F1.4 — `formatMoney` + `MoneyText`.** Implementar (05 §0/§1) com testes unitários
  (positivo, negativo, string, sinal, hideCents).
  <br>_Aceite:_ `MoneyText kind="expense"` renderiza "−R$ 80,00" em `--expense`.
- [ ] **F1.5 — Estados padronizados.** `EmptyState`, `ErrorState`, `Skeleton` presets (05 §4).
- [ ] **F1.6 — Página de tokens (referência viva).** `tokens.md`/Storybook leve com paleta,
  tipos, componentes de dinheiro. (Opcional mas recomendado.)
- [ ] **F1.7 — Consolidar UI kit (decisão).** Migrar `Button`/`Select` de Base UI para a
  base Radix+Tailwind; `Select` único que funciona dentro de Dialog (05 §8).
  <br>_Aceite:_ some o padrão "`<select>` nativo dentro de modal"; um só `Select`.

---

## Fase 2 — App shell & navegação 🧭

> Objetivo: nova casca (doc 04) e navegação que funciona no mobile.

- [ ] **F2.1 — `AppShell`.** Extrair de `Layout.tsx`; `max-w-[1200px]`, `useWorkspaceEvents`.
- [ ] **F2.2 — `Sidebar` reagrupada.** 4 seções (04 §1); item ativo calmo (tint+barra);
  workspace switcher no **topo**; `UserMenu` no rodapé.
  <br>_Aceite:_ nav agrupada; ativo sem bloco preto/sombra colorida.
- [ ] **F2.3 — `WorkspaceSwitcher` acessível.** Radix `DropdownMenu` (remove click-outside
  manual do `Sidebar.tsx`).
- [ ] **F2.4 — Mobile: `BottomNav` + FAB + `MoreSheet`.** 5 slots, FAB "+ Novo" abre Nova
  Despesa; "Mais" abre sheet com o resto + troca de workspace.
  <br>_Aceite:_ em 375px de largura, dá para navegar e abrir Nova Despesa pelo polegar.
- [ ] **F2.5 — `PageHeader` + `PeriodPicker`.** Padrão único (04 §3/§4); `?month=` na URL.
  <br>_Aceite:_ trocar o mês no header reflete no conteúdo e sobrevive a reload.
- [ ] **F2.6 — `Dialog`/`Sheet` responsivos.** Dialog vira bottom sheet abaixo de `md`.

---

## Fase 3 — Telas core 🎯

> Objetivo: as telas de maior uso no novo padrão (doc 06). Dependem só de 1 e 2.

- [ ] **F3.1 — `TransactionItem` + `TransactionLedger`.** Agrupado por dia, glifo de
  categoria, `MoneyText`, ações `⋯` acessíveis, avatares de divisão, RBAC. (06 §2)
  <br>_Aceite:_ extrato escaneável; despesa vermelha; ações por teclado e no mobile.
- [ ] **F3.2 — `DataTable` + `CategoryGlyph` + `StatusPill`.** Base reusável, com
  `CardList` responsivo. (05 §3)
- [ ] **F3.3 — Página `Lançamentos` (`/transactions`).** Mover o extrato do dashboard;
  filtros em barra única; período no header; export; "Fixos" (recorrência de despesa). (06 §2)
- [ ] **F3.4 — `StatTile` + `HeroBalance` + `BudgetBar`.** (05 §3, 06 §1)
- [ ] **F3.5 — Novo `Início` (`/`).** HeroBalance + linha de métricas + preview de extrato +
  mini-breakdown; remover os 8 cartões e o "Membro/Novo Registro". (06 §1)
  <br>_Aceite:_ passa no "teste dos 2 segundos"; sem valores redundantes; 1 número-herói.
- [ ] **F3.6 — Refino do modal Nova Despesa.** Alinhar ao sistema; `Select` único; sheet no
  mobile; mover Tags/Categoria p/ avançado; mostrar fatura de destino ao usar cartão. (06 §3)

---

## Fase 4 — Telas restantes 🗂️

> Objetivo: aplicar o padrão a todo o resto (docs 06 §4-5 e 07). Paralelizável.

- [ ] **F4.1 — Cartões/Faturas.** `CreditCardVisual`, auto-seleção do 1º, fatura como
  ledger + `StatusPill` + ações (fechar/pagar/reabrir). (06 §4)
- [ ] **F4.2 — Gráficos temáticos.** `ChartTheme`, `TrendChart`, `CategoryBreakdown`,
  `Sparkline`, `TooltipCard` (05 §6) e reconstruir `Relatórios` com abas visíveis. (06 §5)
- [ ] **F4.3 — Orçamento (`/budget`).** Promover de aba a página; `BudgetBar` por categoria. (04)
- [ ] **F4.4 — Dívidas & Acertos.** "Seu balanço" no topo; dívidas como linha de pessoa;
  manter `MonthlyDebtsSection` e histórico. (07 §2)
- [ ] **F4.5 — Rendas + recorrência como aba.** `MoneyText income`, total no header,
  "lançar pendentes" com badge. (07 §1)
- [ ] **F4.6 — Financiamentos.** StatTiles + destaque "economia se quitar hoje"; tabela
  compacta + `CardList` mobile. (07 §3)
- [ ] **F4.7 — Importar (wizard).** Stepper 3 passos + presets de banco + drop zone. (07 §4)
- [ ] **F4.8 — Configurações.** Alinhar; ícone/cor de categoria; abas mobile via sheet;
  membros/contas no padrão pessoa. (07 §5)
- [ ] **F4.9 — Auth (split layout).** Painel de marca + card; consistência entre telas. (07 §6)
- [ ] **F4.10 — Onboarding.** Alinhar + preview do `CreditCardVisual`; sheet no mobile. (07 §7)

---

## Fase 5 — Polish & qualidade ✨

- [ ] **F5.1 — Motion.** Aplicar durações/easings do doc 03 §4; `prefers-reduced-motion`;
  remover "pulos" de hover.
- [ ] **F5.2 — QA de temas.** Varrer todas as telas em claro e escuro (script de screenshots
  deste estudo serve de baseline) — zero cor hardcoded, zero contraste ruim.
- [ ] **F5.3 — Acessibilidade.** Foco visível em tudo; alvos ≥40px no mobile; auditar com
  axe; navegação por teclado no ledger/tabelas.
- [ ] **F5.4 — Densidade compacta** (opcional) em tabelas longas (faturas/parcelas).
- [ ] **F5.5 — ⌘K command palette** (nice-to-have): navegar + "nova despesa".
- [ ] **F5.6 — Microcópia.** Revisar textos (sentence case, tom calmo, empty states que
  ensinam).

---

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
