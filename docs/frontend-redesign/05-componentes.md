# 05 — Biblioteca de componentes-base

Os primitivos reutilizáveis que sustentam o redesign. Construir **estes** primeiro (Fase 1
e 2) e as telas (06/07) viram composição. Props em TypeScript; comportamento descrito.
Todos consomem os tokens do doc 03 — zero cor hardcoded.

Convenção: componentes de UI genérica em `src/components/ui/*` (evoluindo os atuais);
componentes de domínio financeiro em `src/components/money/*` e `src/components/app/*`.

---

## 0. Helper de formatação (base de tudo)

`src/lib/money.ts` — **uma** fonte de verdade para moeda. Resolve B2 (formatação
inconsistente).

```ts
export type Money = number | string;               // aceita string do back (Decimal)
const toNumber = (v: Money) => typeof v === 'string' ? parseFloat(v) : v;

export function formatMoney(v: Money, opts?: { sign?: boolean; hideСents?: boolean }): string;
//  formatMoney(1234.5)            -> "R$ 1.234,50"
//  formatMoney(-80, {sign:true})  -> "−R$ 80,00"   (usa o menos tipográfico U+2212)
//  formatMoney(1234.5,{hideCents:true}) -> "R$ 1.235"  (para heróis/gráficos)

export function formatCompact(v: Money): string;    // "R$ 1,2 mil" p/ eixos de gráfico
```
Regra: **nenhuma tela** chama `toLocaleString` direto. Tudo passa por aqui ou por `MoneyText`.

---

## 1. `MoneyText` — o componente que conserta o "tudo verde" (B1)

`src/components/money/MoneyText.tsx`. Centraliza formatação **e** semântica de cor.

```ts
type MoneyKind = 'expense' | 'income' | 'transfer' | 'neutral';

interface MoneyTextProps {
  value: Money;                 // valor absoluto ou com sinal
  kind?: MoneyKind;             // decide a COR e o SINAL — default 'neutral'
  size?: 'sm' | 'md' | 'lg' | 'hero';
  showSign?: boolean;           // força +/−; default: derivado do kind
  colorize?: boolean;           // default true; false = sempre --text (ex.: tabelas neutras)
  className?: string;
}
```

**Comportamento (a regra P1 encapsulada):**
- `kind='expense'` → cor `--expense`, prefixo `−`. (uma despesa de R$ 80 → **−R$ 80,00** em vermelho)
- `kind='income'`  → cor `--income`, prefixo `+`.
- `kind='transfer'`/`neutral` → cor `--text`, sem sinal.
- Sempre `tabular-nums`, alinhável à direita.
- **Nunca** decide cor por `value < 0`. Quem sabe o tipo é o chamador (a transação tem
  natureza de despesa/receita). Isso mata o bug na raiz e vale para todo o app.

> Migração: trocar todo `text-emerald-500 / text-destructive` de valores por `<MoneyText>`.
> No extrato, `kind` vem do tipo do lançamento (despesa) — então despesa fica vermelha, como
> deve ser; estorno/cashback (`amount < 0` numa despesa) pode virar `income`/`transfer`.

---

## 2. Shell & navegação

### `AppShell`
Embrulha rotas autenticadas. Renderiza `Sidebar` (desktop) ou `BottomNav` (mobile),
`Topbar` opcional e o slot de conteúdo com `max-w-[1200px] mx-auto`. Cuida do
`useWorkspaceEvents()` (hoje no `Layout`).

### `Sidebar`
```ts
interface NavSection { label: string; items: NavItem[]; }
interface NavItem { icon: LucideIcon; label: string; to: string; badge?: number; }
```
- Recebe as seções do doc 04. Item ativo: `--brand-subtle` + barra 3px + ícone/texto marca.
- Topo: `<WorkspaceSwitcher/>`. Rodapé: `<UserMenu/>`.
- Suporta `collapsed` (64px, tooltips).

### `BottomNav` (mobile) + `MoreSheet`
5 slots com FAB central "+ Novo". "Mais" abre `MoreSheet` (bottom sheet) com o restante e a
troca de workspace.

### `WorkspaceSwitcher`
Evolui o atual: botão com nome + dot de status + chevron; dropdown com lista, dica
"compartilhado por X" e "Criar workspace". Acessível (Radix `DropdownMenu`, não `div`+
click-outside manual como hoje).

### `PageHeader`
```ts
interface PageHeaderProps {
  title: string; subtitle?: string;
  period?: React.ReactNode;         // slot p/ <PeriodPicker/>
  action?: React.ReactNode;         // 1 ação primária
  backTo?: string;                  // seta de voltar (telas de detalhe)
}
```
Anatomia fixa do doc 04. `h1` calmo (28px/600), subtítulo `--text-muted`.

### `PeriodPicker`
```ts
interface PeriodPickerProps {
  value: string;                    // "YYYY-MM"
  onChange: (m: string) => void;
  min?: string; max?: string;       // limites
}
```
`‹ Julho 2026 ›` com setas + menu de meses recentes. Sincroniza com `?month=` (search param).

---

## 3. Superfícies & dados

### `Card` (evolução do atual)
Manter API (`Card/Header/Title/Content/Footer`), mas: borda `--border` (sem ring
colorido), `--radius-lg`, `p-5`, `font-heading`→Semibold, **sem** sombra estática. Variante
`interactive` (hover `--surface-2`) para cartões clicáveis.

### `StatTile` — substitui os "8 cartões" do dashboard
```ts
interface StatTileProps {
  label: string;                    // "Sobra do mês" (sentence case)
  value: Money; kind?: MoneyKind;   // usa MoneyText
  hint?: string;                    // "de R$ 9.050 de renda"
  trend?: { dir: 'up'|'down'|'flat'; text: string; good?: boolean };
  spark?: number[];                 // mini-sparkline opcional
  icon?: LucideIcon;                // discreto, --text-subtle
}
```
Calmo por padrão: label pequeno em cima, valor grande (`MoneyText size="lg"`), hint/trend
embaixo. Sem borda colorida, sem uppercase. Usado em linhas de 3–4.

### `HeroBalance` — o número protagonista do Início
Um bloco maior (não um "card" entre iguais): enunciado + valor `hero` + barra de
progresso gasto/orçamento + micro-tendência. Ver 06 (Início).

### `DataTable`
Wrapper sobre `<table>` com:
```ts
interface Column<T> { key; header; align?: 'left'|'right'|'center'; render?; width?; hideBelow?: 'md' }
interface DataTableProps<T> { columns; rows; density?: 'comfortable'|'compact'; onRowClick?; empty?; loading? }
```
- Cabeçalho `--surface-2`, linhas com divisor `--border`, hover `--surface-2`.
- `density` (03 §5). `hideBelow` colapsa colunas no mobile.
- **Responsivo**: abaixo de `md`, renderiza `rows` como `CardList` (cada linha → card) via
  render prop `renderCard`. Elimina tabelas horizontais no celular.
- Estados `loading`/`empty` embutidos (skeleton de linhas / `EmptyState`).

### `TransactionItem` / `TransactionLedger` — o coração (P4)
Substitui a `<Table>` densa atual do extrato.
```ts
interface TransactionItemProps {
  tx: TransactionRead;
  onEdit?; onDelete?; canWrite?: boolean;
}
```
Layout de linha (desktop):
```
[glifo categoria]  Título                         −R$ 148,50
                   Categoria · Cartão · (avatares se dividido)     14:32? (só se relevante)
```
- **Glifo de categoria** à esquerda: chip redondo `--surface-2` com ícone lucide na cor da
  categoria. Dá escaneabilidade imediata (hoje a categoria é texto uppercase 10px).
- Valor à direita via `MoneyText kind={tipo}` — sinal e cor corretos.
- Data/hora: agrupar por **dia** (cabeçalho "Hoje", "Ontem", "20 jul") no `Ledger`; a hora
  só aparece quando informativa (some o "15:00" repetido).
- Divisão: avatares empilhados só se `splits > 1` (mantém o toque bom que já existe).
- Ações (editar/excluir): visíveis no hover **e** acessíveis por foco/teclado; no mobile,
  swipe ou menu `⋯` (não depender de hover). Respeita `canWrite` (RBAC).
- `TransactionLedger` = lista agrupada por dia + cabeçalhos de dia + subtotal do dia (opc.).

### `CategoryChip` / `CategoryGlyph`
Pílula/glifo reutilizável: mapeia `category.icon` (string do back) → lucide, usa
`category.color` como tint. Usado no ledger, filtros, relatórios, form.

### `Badge` / `StatusPill`
Padronizar status (Confirmada/Paga/Cancelada, Ativa/Inativa, Paga/Pendente/Vencida) num
`StatusPill` com mapa `status → {label, tone}` (`tone`: neutral/success/warning/danger).
Hoje cada tela repinta badges na mão.

---

## 4. Estados

### `EmptyState`
```ts
interface EmptyStateProps { icon?: LucideIcon; title: string; description?: string; action?: React.ReactNode; }
```
Ícone/ilustração leve (marca 15%), título `h3`, descrição `--text-muted`, 1 ação primária.

### `ErrorState`
Mensagem (via `getApiErrorMessage`) + "Tentar novamente" (`onRetry`). Nunca vira "zeros".

### `LoadingState` / `Skeleton`
Skeletons que espelham o layout (linhas de extrato, card de métrica, card de cartão). Um
`Skeleton` base (já existe) + presets por contexto.

---

## 5. Dinheiro & cartões

### `CreditCardVisual` — resolve H6
Um cartão com **identidade de cartão**, não uma caixa:
```ts
interface CreditCardVisualProps {
  name: string; brandColor?: string;      // tint por bandeira/apelido
  limit: Money; available: Money; committed: Money;
  closingDay: number; dueDay: number;
  selected?: boolean; onClick?;
}
```
- Proporção de cartão (~1.586:1), gradiente sutil na cor do cartão, chip/decoração discreta,
  nome em destaque, "disponível" grande, limite/comprometido secundários, mini-barra de uso
  do limite. Selecionado = anel de marca. Auto-seleciona o 1º (mata o "selecione um cartão").

### `BudgetBar` / `ProgressMeter`
Barra de progresso semântica: verde < 80%, âmbar 80–100%, vermelho > 100% do orçamento.
Usada no Início, Orçamento e por categoria.

### `AmountInput` (evolui `MoneyInput`)
Manter o bom `MoneyInput` atual; padronizar aparência (prefixo `R$`, tabular, foco marca).

---

## 6. Gráficos (wrappers temáticos sobre Recharts) — resolve B3

Nunca usar Recharts "cru" na tela (é onde entram as cores hardcoded). Criar wrappers que
leem tokens via CSS vars:

### `ChartTheme` (util)
Helper que lê `--chart-1..6`, `--chart-grid`, `--text-muted` de `getComputedStyle` (ou
expõe via classe) e monta `contentStyle`/cores para tooltip, grid e eixos — **do tema
atual**, claro ou escuro. Fim do tooltip preto no claro.

### `TrendChart`
Linha/área de receita × despesa × "minha parte" ao longo dos meses. Trata "pouca história":
se < 2 meses, mostra estado "coletando dados" em vez de eixo vazio (B4).

### `CategoryBreakdown`
Distribuição por categoria. Preferir **barras horizontais ordenadas** (mais legíveis que
pizza para comparar) + opção de donut. Usa `CategoryGlyph`/cores das categorias.

### `Sparkline`
Mini-gráfico inline para `StatTile`/`HeroBalance` (sem eixos, sem tooltip).

### `TooltipCard`
Tooltip custom única para todos os gráficos: `--surface`, borda `--border`, `--radius-md`,
sombra `--shadow-md`, valores via `formatMoney`. Substitui os `contentStyle` inline.

---

## 7. Overlays
- `Dialog` (Radix) padronizado: `--radius-lg`, `--shadow-lg`, header/footer consistentes,
  vira **bottom sheet** abaixo de `md`.
- `Sheet` (drawer lateral/inferior) para "Mais" no mobile e filtros.
- `Toast` (já existe) e `ConfirmDialog` (`useConfirm`, já existe) — só realinhar ao token set.
- `DropdownMenu` (Radix) para menus de ação (⋯) e workspace/perfil — trocar os
  `div`+click-outside manuais.

---

## 8. Consolidação de UI kit (dívida do 01)
- **Decisão**: padronizar em **Radix + wrappers Tailwind** (shadcn-style) como base única e
  migrar os poucos usos de **Base UI** (`Button`, `Select`) para essa base. Remove as regras
  de contorno de focus-trap e a segunda árvore de componentes.
- `Select`: um só componente (Radix Select) que funciona dentro e fora de Dialog — elimina o
  "use `<select>` nativo dentro de modal" espalhado hoje.

---

## 9. Ordem sugerida de construção
1. `formatMoney` + `MoneyText` + `.tabular` → destrava B1/B2 e o extrato.
2. `EmptyState`/`ErrorState`/`Skeleton` → destrava consistência de estados.
3. `PageHeader` + `PeriodPicker` → destrava o padrão de página.
4. `AppShell` + `Sidebar`/`BottomNav` + `WorkspaceSwitcher` → destrava a navegação.
5. `TransactionItem`/`Ledger` + `DataTable` + `CategoryGlyph` + `StatusPill` → destrava as listas.
6. `StatTile`/`HeroBalance`/`BudgetBar` + `CreditCardVisual` → destrava Início e Cartões.
7. Wrappers de gráfico (`ChartTheme`, `TrendChart`, `CategoryBreakdown`, `TooltipCard`) →
   destrava Relatórios.
