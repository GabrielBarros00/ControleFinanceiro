# 04 — Arquitetura de informação & navegação

Como o app se organiza e como a pessoa se move nele. Aqui resolvemos H5 (navegação não
escala / sem mobile) e criamos os **padrões de página** reaproveitados por todas as telas.

> ⚠️ **Este mapa é histórico — a navegação de hoje é outra.** O documento foi escrito
> ANTES dos ADRs [0020](../adr/0020-visao-global-e-quatro-numeros.md) (camada global e o
> workspace na URL) e [0021](../adr/0021-recurso-pessoal-sem-workspace.md) (recurso pessoal
> sem workspace), e a seção "COMPARTILHADO" com Rendas e Dívidas que ele propõe abaixo
> **diz o oposto do que passou a valer**: renda é o dado mais privado do sistema.
>
> A fonte da verdade é `frontend/src/components/layout/nav-items.ts`. Em resumo, hoje são
> **duas camadas nomeadas pelo escopo** — e a palavra para o contêiner é **espaço**,
> em toda a interface (2026-08-17):
>
> ```
> [ Seletor de escopo: Pessoal · ou · o nome do espaço ]   ← ScopeSwitcher, topo
>
> PESSOAL · Só você vê
>   Seu mês · Rendas · Cartões · Financiamentos · Compromissos
>   Seus acertos · Seus relatórios · Extrato · Suas configurações
>
> COMPARTILHADO · <nome do espaço> · N pessoas
>   Painel · Lançamentos · Recorrência · Relatórios · Acertos · Importar · Configurações
>
> SITE (só para quem tem o papel — ADR 0026)
>   Administração
> ```
>
> O que continua valendo deste documento: o `AppShell`, o `PageHeader`, o `PeriodPicker`,
> os estados padronizados e as regras de responsividade da §6 — essas foram entregues e
> seguem em uso. O que mudou de vez é o §1 (o mapa) e parte do §2.3 (o mobile).

---

## 1. Mapa atual → proposto  *(histórico — ver a nota acima)*

Hoje: 9 itens planos na sidebar, sem hierarquia, switcher de workspace no rodapé.

Proposto: **mesmos destinos**, agrupados em 4 seções com rótulo, para dar hierarquia sem
esconder nada. Alguns itens migram para _sub-navegação_ dentro de uma tela (ver notas).

```
┌ Workspace switcher (TOPO da sidebar, não rodapé) ┐

DIA A DIA
  ● Início            /                (era "Dashboard")
  ● Lançamentos       /transactions    (extrato — hoje mora dentro do dashboard)
  ● Relatórios        /reports

CRÉDITO & METAS
  ● Cartões           /cards
  ● Financiamentos    /financing
  ● Orçamento         /budget          (hoje é uma aba escondida em Relatórios)

COMPARTILHADO
  ● Rendas            /income
  ● Dívidas & Acertos /debts

SISTEMA
  ● Importar          /import
  ● Configurações     /settings        (Categorias, Contas, Membros, Aparência… já são abas)

[ Recorrência ] → deixa de ser item de topo; vira aba dentro de Lançamentos e de Rendas
                  (recorrência de despesa vs. de renda), onde o contexto já existe.
```

**Racional:**
- **Início vs. Lançamentos**: hoje o dashboard mistura KPIs + o extrato inteiro. Separar
  dá ao Início o papel de _resumo_ (a dobra responde "como estou") e a Lançamentos o papel
  de _extrato completo_ (busca, filtros, paginação, export). Menos rolagem no Início.
- **Orçamento** promovido de aba-escondida a destino: é uma meta central de finanças
  pessoais e hoje está enterrado na 4ª aba de Relatórios.
- **Recorrência** vira contexto, não seção: "gastos fixos" fazem mais sentido como uma
  visão dentro de Lançamentos; "rendas recorrentes" já vivem em Rendas.
- **Configurações** já é um hub de abas (Perfil/Segurança/Membros/Categorias/Contas/
  Aparência) — mantido.

> Nota de escopo: mover o extrato para `/transactions` e promover `/budget` são mudanças
> de rota. Se preferir migração mínima, o Início pode manter um _preview_ do extrato com
> link "ver todos" para `/transactions`. Ambos descritos em 06.

---

## 2. App Shell

Estrutura persistente que embrulha toda tela autenticada (componente `AppShell`, ver 05):

```
Desktop (≥ lg)                         Mobile (< md)
┌──────────┬───────────────────────┐   ┌───────────────────────┐
│ Sidebar  │ Topbar (contexto)     │   │ Topbar compacta       │
│ (240px)  ├───────────────────────┤   ├───────────────────────┤
│          │                       │   │                       │
│ Workspace│   PageHeader          │   │   PageHeader          │
│ ──────── │   ───────────         │   │   (título + ação)     │
│ seções   │   conteúdo            │   │   conteúdo            │
│ nav      │   (max-w 1200,        │   │   (full width)        │
│          │    centralizado)      │   │                       │
│          │                       │   ├───────────────────────┤
│ [perfil] │                       │   │ Bottom nav (5 itens)  │
└──────────┴───────────────────────┘   └───────────────────────┘
```

### 2.1 Sidebar (desktop)
- **240px**, fundo `--surface`, borda direita `--border`.
- Topo: **workspace switcher** (nome + avatar/dot + chevron) — sobe do rodapé para o topo,
  onde se espera "contexto atual".
- Seções com rótulo `label` discreto (não uppercase pesado).
- Item ativo: fundo `--brand-subtle` + texto/ícone `--brand` + barra de 3px à esquerda na
  cor da marca. **Não** o bloco preto/azul sólido com sombra colorida de hoje.
- Hover: fundo `--surface-2`.
- Rodapé: avatar + nome do usuário → menu (Perfil, Tema, Sair).
- **Colapsável** para 64px (só ícones) com tooltip — opcional, bom para telas menores.

### 2.2 Topbar (desktop)
Fina, opcional por página. Carrega: breadcrumb/título curto à esquerda; à direita, o
**seletor de período global** (quando a página é temporal), busca rápida (⌘K, futuro) e
ações globais. Pode ser fundida ao `PageHeader` em páginas simples.

### 2.3 Mobile
- Sidebar some; vira **bottom-nav de 5 itens** (Seu mês, Lançamentos, +Novo (FAB central),
  Cartões, Mais). "Mais" abre um sheet com o resto.
- O **FAB central "+ Novo"** abre o modal de Nova Despesa — a ação mais frequente, sempre
  ao alcance do polegar. **Só dentro de um espaço**: fora de `/w/:id` ele lançava no último
  espaço visitado sem dizer qual, e a camada global é somente leitura (ADR 0020).
- Topbar mobile: **seletor de escopo** à esquerda, avisos à direita.

> **Corrigido em 2026-08-17.** Duas coisas previstas aqui não tinham sido feitas, e a falta
> das duas era a queixa de quem usava:
>
> - **"trocar workspace" no sheet "Mais"** nunca existiu. O seletor morava só na sidebar
>   (`hidden md:flex`), então no celular simplesmente **não havia como trocar de espaço**.
>   Hoje isso é o `ScopeSwitcher`, e ele fica na topbar — não no sheet: a pergunta "onde eu
>   estou?" precisa de resposta permanente, não a dois toques;
> - o sheet chamava `navFlat()`, que **descarta os rótulos de seção**, e virava uma grade
>   de quinze tiles sem hierarquia. A topbar prevista ("título da página + ação
>   contextual") também não existia: era uma faixa de 40px com um sino solitário.

---

## 3. Padrão de página (`PageHeader` + corpo)

Toda página segue a mesma anatomia — consistência que hoje falta (cada tela tem seu
cabeçalho ad-hoc):

```
PageHeader
  ├─ Título (h1)              ex.: "Lançamentos"
  ├─ Subtítulo (opcional)     ex.: "Tudo que entrou e saiu"
  ├─ Slot de contexto         ex.: seletor de mês  →  [ ‹ Julho 2026 › ]
  └─ Ação primária (à direita) ex.: [ + Nova despesa ]

Corpo
  ├─ (filtros/segment, se houver) — barra única, não espalhados
  ├─ conteúdo
  └─ estados: loading / empty / error padronizados
```

Regras:
- **Uma** ação primária por página (botão de marca). Ações secundárias como `ghost`/`outline`.
- O **seletor de período** é o mesmo componente em Início, Lançamentos, Relatórios,
  Dívidas e Faturas (P5). Fica no `PageHeader`, não perdido numa toolbar de tabela.
- Título de página não repete o nome do item de nav em negrito gigante; é `h1` (28px, 600),
  calmo.

---

## 4. Seletor de período (global, temporal)

Componente único `PeriodPicker`:
- Formato compacto: `‹ Julho 2026 ›` com setas prev/next e clique para abrir um mini-menu
  (meses recentes + "mês atual" + range custom, futuro).
- Estado guardado por página no React Query key / URL search param (`?month=2026-07`), para
  ser _linkável_ e sobreviver a reload.
- Substitui o `<Select>` de meses embutido na tabela de transações e a lógica duplicada em
  Dívidas/Relatórios.

---

## 5. Estados padronizados (loading / empty / error)

Hoje cada tela inventa o seu. Padronizar em 3 componentes (ver 05) com uso consistente:

- **Loading**: skeletons que _espelham o layout_ (não spinner central genérico), exceto
  ações rápidas. Ex.: extrato mostra 6 linhas skeleton; cartões mostram 2 card-skeletons.
- **Empty**: `EmptyState` = ícone/ilustração leve + título + 1 frase + **ação primária**.
  Ex.: "Nenhum lançamento em julho" · "Registre seu primeiro gasto" · [ + Nova despesa ].
- **Error**: `ErrorState` = mensagem honesta (usa `getApiErrorMessage`) + botão "Tentar
  novamente". Nunca deixar erro parecer "tudo zero" (regra ERR-001 já existente).

Matriz de estados que **toda** tela de dados deve cobrir: `loading · empty · error ·
partial (pouca história) · sem-permissão (viewer)`.

---

## 6. Responsividade — regras gerais

| Elemento | ≥ lg | md | < md |
|----------|------|----|----|
| Navegação | sidebar 240px | sidebar colapsada (64px) ou topbar+drawer | bottom-nav + sheet |
| Grid de métricas | 3–4 col | 2 col | 2 col (ou 1 no herói) |
| Tabelas densas (extrato, faturas, parcelas) | tabela | tabela com colunas reduzidas | **lista de cards** empilhados |
| Dialogs | modal centralizado | modal | **bottom sheet** (sobe de baixo) |
| PageHeader | título+ação lado a lado | idem | título em cima, ação vira FAB/линha |

O "tabela → cards no mobile" é chave para o extrato/faturas ficarem usáveis no celular
(cada transação vira um card com título, categoria, valor e data).

---

## 7. Navegação por teclado & rotas
- Rotas mantêm React Router 7 e o code-splitting atual.
- Adicionar (futuro, não bloqueante): paleta de comandos ⌘K para pular entre telas e criar
  lançamento. Fica registrado como _nice-to-have_ da Fase 5.
- Preservar o guard `ProtectedRoute`, o redirect de convite e o loading de sessão atuais.
- `?month=` e `?tab=` como search params para deep-link de período e aba.

---

## 8. Resumo do que muda de estrutura

| Mudança | Tipo | Fase |
|---------|------|------|
| Workspace switcher topo da sidebar | UI | 2 |
| Sidebar agrupada em 4 seções + item ativo calmo | UI | 2 |
| Bottom-nav + FAB no mobile | novo | 2 |
| `PageHeader` + `PeriodPicker` padrão | novo | 2–3 |
| Extrato promovido a `/transactions` | rota | 3 |
| Orçamento promovido a `/budget` | rota | 4 |
| Recorrência vira aba (Lançamentos/Rendas) | rota | 4 |
| Estados loading/empty/error padronizados | novo | 1–3 |
