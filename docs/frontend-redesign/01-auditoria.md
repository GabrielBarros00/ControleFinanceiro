# 01 — Auditoria do estado atual

Levantamento do frontend como ele está hoje, com base na leitura do código e nas
capturas em [`telas-atuais/`](telas-atuais/) (1440×900, tema claro e escuro, com dados
semeados: 2 rendas, 13 despesas categorizadas, 1 cartão com 4 lançamentos).

---

## 1. Stack e fundação atuais

| Camada | Hoje |
|--------|------|
| Base | React 19, Vite, TypeScript, React Router 7 |
| Estilo | Tailwind 3, tokens shadcn em `oklch` (`src/index.css`), fonte **Geist** |
| UI kit | Mistura de **Radix** (Dialog, Tabs, Select, Progress…) e **Base UI** (`Button`, `Select`) + wrappers em `src/components/ui/*` |
| Dados | React Query; Zustand (`auth`, `ui`/workspace) com persist |
| Gráficos | Recharts | 
| Animação | Framer Motion + `tw-animate-css` (utilitários `animate-in`) |
| Ícones | lucide-react |

**Observações de fundação:**

- Há **duas bibliotecas de componentes** convivendo (Radix + Base UI). Isso já gerou
  regras de contorno ("dentro de Dialog use `<select>` nativo porque o popup do Base UI
  foge do focus-trap" — ver `AmortizationTable.tsx`). É dívida de arquitetura de UI.
- O token `--primary` é **preto** no claro e **azul/roxo** (`oklch(0.488 0.243 264)`) no
  escuro. Ou seja, a "cor da marca" muda de identidade entre temas — no claro o app é
  preto-e-branco; no escuro é azul. Não há uma identidade única.
- Não há tokens semânticos para **dinheiro** (entrada/saída). Cada tela reinventa
  `text-emerald-500` / `text-destructive` na mão → inconsistência e o bug abaixo.
- `Card` usa `ring-1 ring-foreground/10` + `rounded-xl`; `CardTitle` referencia
  `font-heading` (fonte de heading que não está claramente configurada).

---

## 2. Inventário de telas

| Rota | Componente | Função | Captura |
|------|-----------|--------|---------|
| `/login`, `/register`, `/forgot-password`, `/reset-password` | `pages/Auth/*` | Autenticação | `auth-login.png`, `auth-register.png`, `auth-forgot-password.png` |
| (modal) | `OnboardingModal` | Boas-vindas em 3 passos (renda + cartão) | `onboarding-modal.png` |
| `/` | `BentoDashboard` + `BentoGrid` + `TransactionHistory` | Visão geral + extrato | `dashboard-light.png`, `dashboard-dark.png` |
| (modal) | `NewTransactionDialog` → `TransactionForm` | Nova despesa (slim + avançado) | `nova-despesa-modal-light.png`, `nova-despesa-modal-dark.png` |
| `/income` | `IncomePage` | Rendas + rendas recorrentes | `rendas-light.png`, `rendas-dark.png` |
| `/cards` | `CreditCardList` + `StatementView` | Cartões e faturas | `cartoes-light.png`, `cartoes-dark.png` |
| `/financing` | `AmortizationTable` | Financiamentos SAC/PRICE | `financiamentos-light.png`, `financiamentos-dark.png` |
| `/reports` | `ReportsPage` + `BudgetPanel` | Relatórios (4 abas) | `relatorios-light.png`, `relatorios-dark.png` |
| `/recurring` | `RecurringTransactionsPage` | Despesas recorrentes | `recorrencia-light.png`, `recorrencia-dark.png` |
| `/debts` | `DebtsPage` + `MonthlyDebtsSection` | Balanço e acertos entre membros | `dividas-light.png`, `dividas-dark.png` |
| `/import` | `ImportPage` | Importar CSV com mapeamento | `importar-light.png`, `importar-dark.png` |
| `/settings` | `SettingsPage` | Perfil, Segurança, Membros, Categorias, Contas, Aparência | `configuracoes-light.png`, `configuracoes-dark.png` |

Navegação: **sidebar fixa de 9 itens** + switcher de workspace no rodapé da sidebar.
Sem navegação mobile (a sidebar é `w-64` fixa).

---

## 3. Bugs de leitura (corrigir já — Fase 0)

Estes não são preferência estética; são erros que um app de **finanças** não pode ter.

### B1 — Toda despesa aparece VERDE 🔴 crítico
`TransactionHistory.tsx:322` colore por sinal:
```
parseFloat(tx.total_amount) < 0 ? 'text-destructive' : 'text-emerald-500'
```
Despesas são gravadas com valor **positivo** → caem sempre no verde. Resultado: no
extrato do dashboard, "Padaria R$ 28,40", "Uber R$ 32,80", "Aluguel"… tudo verde, como
se fosse receita. Verde = "entrou/positivo" no modelo mental do usuário. **A cor está
contando a história errada.** (evidência: `dashboard-light.png`, `dashboard-dark.png`)
→ Corrigido pelo componente `MoneyText` semântico (ver 05) que decide a cor por
**tipo de lançamento** (despesa/receita/estorno), não pelo sinal cru.

### B2 — Formatação de moeda inconsistente 🟠 alto
No painel "Previsão Fim do Mês" aparece **"R$ 5449.14"** (ponto, sem milhar) ao lado de
"R$ 4.895,42" (pt-BR correto). Causa: `forecast.projected_eom` chega como **string** e
`(<string>).toLocaleString('pt-BR', …)` é no-op. Há pelo menos 3 formatações de moeda
diferentes no código (`toLocaleString` inline, `formatCurrency` de `lib/money`, e
concatenação manual `R$ ${…}`). → Padronizar em **um** helper `formatMoney` e no
componente `MoneyText`.

### B3 — Relatórios quebram no tema claro 🟠 alto
Em `relatorios-light.png`:
- **Tooltip preto sobre fundo branco** — `contentStyle={{ backgroundColor: 'oklch(0.165 0 0)' }}`
  hardcoded para o escuro em `ReportsPage.tsx`.
- **Grid do gráfico invisível** — linhas `rgba(255,255,255,0.05)` (branco) somem no claro.
- **Abas quase invisíveis** — a `TabsList` renderiza como texto solto ("Visão Geral
  Categorias Fluxo Orçamento") sem o realce esperado; há um grande cartão branco vazio à
  esquerda. Layout do painel de abas parece desalinhado.
→ Tokenizar as cores do Recharts (ler de CSS vars) e revisar o layout das abas (ver 06).

### B4 — Gráfico "últimos 6 meses" mostra 1 mês 🟡 médio
Só há dados de julho; Fev–Jun aparecem vazios com uma barra de hover cinza gigante. O
gráfico não trata bem o caso "pouca história" (comum para usuário novo). → Estado
"coletando dados" + eixo/serial mais tolerante.

---

## 4. Problemas estruturais e de hierarquia (o redesign)

### H1 — Dashboard = 8 cartões, muita redundância 🟠 alto
`dashboard-light.png` empilha **duas fileiras de 4 cartões** antes do extrato:

- Fileira 1: Previsão Fim do Mês · Gasto Real Atual · Seu Saldo · Orçamento do Mês
- Fileira 2: Sua Receita · Sua Despesa · Membro · Novo Registro

Problemas: **"Gasto Real Atual" e "Sua Despesa" mostram o mesmo R$ 4.895,42**; "Seu
Saldo" é derivável de Receita − Despesa; o cartão **"Membro / Ana / Logado em Meu
Workspace"** gasta espaço nobre com quase nenhuma informação; **"Novo Registro"**
duplica o botão "Nova Despesa" do topo. Quatro bordas coloridas diferentes (roxo/preto/
verde/âmbar) competem por atenção. → Substituir por 1 herói + linha compacta de métricas
(ver 06).

### H2 — Estética "loud" por toda parte 🟠 alto
Uso pesado e onipresente de `font-black`, `uppercase`, `tracking-widest`, rótulos de
10px, sombras `shadow-lg shadow-primary/20`, cores neon. Tudo grita com o mesmo peso →
**nada tem prioridade**. Um app financeiro quer o oposto: poucos elementos gritam (o
número principal), o resto sussurra.

### H3 — Preto/branco duro no claro; identidade trocada no escuro 🟡 médio
O claro é estéril (branco puro + preto). O escuro é mais coeso, mas com identidade
diferente (azul). Falta uma paleta de marca única, com neutros levemente quentes e uma
cor de destaque estável entre temas.

### H4 — Duas famílias de listas/tabelas, sem densidade pensada 🟡 médio
`TransactionHistory` é uma `<Table>` densa com Data/Hora (mostra "15:00" em toda linha —
ruído), categoria em `UPPERCASE` 10px, ações que só aparecem no hover. Rendas, Dívidas,
Financiamento, Import cada um repete um padrão de tabela ligeiramente diferente. → Um
padrão de _ledger_/lista e um padrão de tabela de dados, reutilizados.

### H5 — Navegação não escala e não tem mobile 🟡 médio
9 itens planos na sidebar sem agrupamento; switcher de workspace escondido no rodapé.
`w-64` fixo, sem colapso, sem bottom-nav → **inutilizável no celular**, onde muita gente
registra gasto na hora.

### H6 — Cartões de crédito sem metáfora de cartão 🟢 baixo
`cartoes-light.png`: o cartão é uma caixa com borda, visualmente igual a qualquer outro
`Card`. Faturas exigem clique extra ("Selecione um cartão acima"). → Um componente de
cartão com identidade (gradiente/altura visual) e auto-seleção do primeiro cartão.

### H7 — Estados vazios/erro/carregando ad-hoc 🟢 baixo
Cada tela inventa seu spinner (`Loader2`, ou `div` girando) e seu texto vazio ("Nenhuma
transação encontrada.", "Selecione um cartão…"). Sem ilustração, sem ação primária. →
Componentes `EmptyState`, `ErrorState`, `LoadingState` padronizados.

---

## 5. O que está BOM (preservar)

Nem tudo precisa mudar — várias decisões são sólidas e devem ser mantidas/estendidas:

- **`NewTransactionDialog` / `TransactionForm`** — form _slim_ com "Opções avançadas"
  (progressive disclosure), chips de divisão, `MoneyInput`. É o melhor pedaço de UX do
  app. Serve de modelo para o resto. (`nova-despesa-modal-light.png`)
- **Recorrência unificada** (frequency + interval + editor compartilhado) e o conceito de
  "minha parte vs. casa" — informação genuinamente útil, só mal apresentada.
- **Riqueza de domínio**: faturas server-side, SAC/PRICE com "economia se quitar hoje",
  acertos por mês, import com detecção de duplicata. O redesign deve **valorizar** isso.
- **Toasts + `useConfirm`** no lugar de `alert/confirm` nativos; RBAC no front (viewer
  não edita). Manter.
- **Code-splitting por rota** e React Query já bem usados.

---

## 6. Heurística — nota rápida por dimensão

| Dimensão | Nota | Comentário |
|----------|:----:|-----------|
| Clareza da informação | ⚠️ 2/5 | Bug do verde + redundância + moeda inconsistente minam a confiança |
| Hierarquia visual | ⚠️ 2/5 | Tudo em negrito/uppercase; sem foco |
| Consistência | ⚠️ 2/5 | 2 UI kits, 3 formatações de moeda, N padrões de tabela |
| Identidade / "cara de finanças" | ⚠️ 2/5 | Template SaaS genérico; claro estéril, escuro azul |
| Densidade / uso do espaço | 3/5 | Ok, mas cartões redundantes desperdiçam a dobra |
| Responsivo / mobile | ❌ 1/5 | Sem navegação mobile |
| Acessibilidade | 3/5 | Foco/labels ok; contraste do neon e alvos de hover a revisar |
| Fluxo de tarefas (registrar/dividir) | ✅ 4/5 | O modal de despesa é bom |
| Riqueza funcional | ✅ 5/5 | Domínio muito completo |

O destino do redesign: levar as 5 primeiras linhas para 4/5 **sem** perder as duas
últimas. O "como" está nos documentos 02–08.
