# 03 — Design system (a base do frontend)

Esta é a **fundação** sobre a qual todas as telas são construídas. Tudo aqui é
implementável na stack atual (Tailwind 3 + CSS vars em `oklch`, como já existe em
`src/index.css`) — **não trocamos bibliotecas**. A ideia é _substituir e ampliar_ os
tokens atuais, adicionando a camada **semântica** que falta (dinheiro, superfícies,
feedback) e uma identidade de marca estável entre temas.

> Por que não uma UI lib nova? Porque o que falta não é componente, é **sistema**:
> tokens coesos + primitivos semânticos. Radix (acessibilidade) + Tailwind (estilo) já
> entregam isso. Introduzir outra lib só adiciona a terceira família de componentes.

---

## 1. Cor

### 1.1 Filosofia de cor

Três "famílias" independentes, que **nunca** se misturam de papel:

| Família | Papel | Onde aparece |
|---------|-------|--------------|
| **Neutros** | Estrutura: fundo, superfície, texto, borda | 90% da tela |
| **Marca** | Identidade e ação: nav ativo, botão primário, links, foco | com parcimônia |
| **Dinheiro / feedback** | Semântica: entrada, saída, sucesso, alerta, erro | só em valores e status |

A marca é **distinta** das cores de dinheiro para nunca confundir "ação da marca" com
"entrou/saiu dinheiro". Default: marca **índigo sóbrio**; dinheiro em **verde/vermelho**
puros. (Alternativa quente: marca teal — ver 1.5.)

### 1.2 Tokens — tema claro (`:root`)

Neutros levemente quentes (sensação de "papel", não laboratório).

```css
:root {
  /* ---- Neutros (superfícies & texto) ---- */
  --bg:            oklch(0.988 0.003 95);   /* fundo da app (off-white quente) */
  --surface:       oklch(1     0     0);    /* cartões, painéis */
  --surface-2:     oklch(0.965 0.004 95);   /* zebra, hover sutil, headers de tabela */
  --surface-sunken:oklch(0.945 0.005 95);   /* áreas "afundadas" (inputs em cartão) */
  --text:          oklch(0.24  0.012 75);   /* texto principal (quase preto, quente) */
  --text-muted:    oklch(0.55  0.012 75);   /* secundário */
  --text-subtle:   oklch(0.66  0.010 75);   /* terciário, placeholders */
  --border:        oklch(0.912 0.005 90);   /* bordas/divisores */
  --border-strong: oklch(0.855 0.006 90);   /* bordas de destaque, foco não-marca */

  /* ---- Marca (índigo) ---- */
  --brand:         oklch(0.50  0.16  275);  /* ação primária, nav ativo */
  --brand-hover:   oklch(0.45  0.16  275);
  --brand-fg:      oklch(0.99  0     0);     /* texto sobre a marca */
  --brand-subtle:  oklch(0.955 0.03  275);  /* fundo tint (chips, seleção) */
  --brand-border:  oklch(0.88  0.06  275);
  --ring:          oklch(0.55  0.16  275);   /* anel de foco */

  /* ---- Dinheiro (semântico) ---- */
  --income:        oklch(0.58  0.15  152);  /* entrada — verde */
  --income-subtle: oklch(0.955 0.04  152);
  --expense:       oklch(0.56  0.19  27);   /* saída — vermelho calmo */
  --expense-subtle:oklch(0.955 0.05  27);
  --money-neutral: var(--text);             /* valores informativos (não +/-) */

  /* ---- Feedback / status ---- */
  --success:       oklch(0.58  0.15  152);
  --warning:       oklch(0.72  0.15  75);   /* âmbar (orçamento estourando, duplicata) */
  --warning-subtle:oklch(0.96  0.05  85);
  --danger:        oklch(0.56  0.19  27);
  --danger-subtle: oklch(0.955 0.05  27);
  --info:          var(--brand);

  /* ---- Dados / gráficos (categorias) ---- */
  --chart-1: oklch(0.55 0.16 275);  /* marca */
  --chart-2: oklch(0.62 0.15 152);  /* verde */
  --chart-3: oklch(0.70 0.15 75);   /* âmbar */
  --chart-4: oklch(0.62 0.16 320);  /* magenta */
  --chart-5: oklch(0.60 0.13 220);  /* azul */
  --chart-6: oklch(0.58 0.14 30);   /* coral */
  --chart-grid: oklch(0.90 0.004 90);
}
```

### 1.3 Tokens — tema escuro (`.dark`)

Escuro "carvão quente", não preto puro; a marca continua índigo (identidade estável).

```css
.dark {
  --bg:            oklch(0.185 0.006 285);
  --surface:       oklch(0.225 0.007 285);
  --surface-2:     oklch(0.262 0.008 285);
  --surface-sunken:oklch(0.165 0.006 285);
  --text:          oklch(0.96  0.004 285);
  --text-muted:    oklch(0.72  0.008 285);
  --text-subtle:   oklch(0.60  0.008 285);
  --border:        oklch(0.30  0.008 285);
  --border-strong: oklch(0.38  0.010 285);

  --brand:         oklch(0.68  0.16  275);  /* mais claro p/ contraste no escuro */
  --brand-hover:   oklch(0.74  0.16  275);
  --brand-fg:      oklch(0.16  0.02  275);
  --brand-subtle:  oklch(0.30  0.06  275);
  --brand-border:  oklch(0.40  0.08  275);
  --ring:          oklch(0.68  0.16  275);

  --income:        oklch(0.72  0.16  152);
  --income-subtle: oklch(0.30  0.06  152);
  --expense:       oklch(0.70  0.17  27);
  --expense-subtle:oklch(0.32  0.07  27);

  --success:       oklch(0.72  0.16  152);
  --warning:       oklch(0.80  0.14  80);
  --warning-subtle:oklch(0.34  0.06  85);
  --danger:        oklch(0.70  0.17  27);
  --danger-subtle: oklch(0.32  0.07  27);

  --chart-1: oklch(0.70 0.15 275);
  --chart-2: oklch(0.74 0.15 152);
  --chart-3: oklch(0.80 0.14 80);
  --chart-4: oklch(0.72 0.15 320);
  --chart-5: oklch(0.72 0.13 220);
  --chart-6: oklch(0.72 0.14 30);
  --chart-grid: oklch(0.30 0.008 285);
}
```

### 1.4 Mapa de compatibilidade com os tokens shadcn atuais

Para migração incremental, manter os nomes atuais **apontando** para os novos, e ir
trocando componente a componente:

```css
:root {
  --background: var(--bg);
  --foreground: var(--text);
  --card: var(--surface);
  --card-foreground: var(--text);
  --primary: var(--brand);
  --primary-foreground: var(--brand-fg);
  --muted: var(--surface-2);
  --muted-foreground: var(--text-muted);
  --accent: var(--surface-2);
  --destructive: var(--danger);
  --border: var(--border);
  --input: var(--border);
  --radius: 0.75rem;
}
```
Assim nada quebra no dia 1; o redesign avança sem _big bang_.

### 1.5 Alternativa de marca (teal quente)
Se preferirem uma identidade mais "verde/dinheiro/quente" (e aceitarem calibrar o verde
de _income_ para outro tom, evitando verde-com-verde):
`--brand: oklch(0.55 0.10 190)` (teal), `--income` desloca para `oklch(0.60 0.16 145)`.
Decisão a bater na Fase 1; o resto do sistema não muda.

### 1.6 Regras de uso de cor (não-negociáveis)

- **Nunca** hardcode de cor de moeda em componente de tela — usar `MoneyText` (05).
- Marca **não** vai em borda de cartão estático (era o vício do "loud"). Cartão usa
  `--border` neutro.
- Contraste mínimo AA: texto normal ≥ 4.5:1, texto grande/números-herói ≥ 3:1. Validar
  `--text-muted` sobre `--surface-2`.
- Cor **nunca** é o único portador de significado: entrada/saída também têm sinal (`+`/`−`)
  e, quando útil, ícone.

---

## 2. Tipografia

Manter **Geist Variable** (já instalada) — é excelente. O que muda é a **disciplina**.

### 2.1 Fontes
- **Sans / UI**: `Geist Variable` (texto, labels, botões).
- **Números / dinheiro**: Geist com `font-variant-numeric: tabular-nums` (colunas de
  valores alinham). Encapsular numa classe `.tabular` / no `MoneyText`.
- (Opcional) **Display**: para os números-herói, considerar Geist com `feature-settings`
  de tabular + peso Semibold. Não é obrigatório trazer fonte nova.

### 2.2 Escala de tipos (rem, base 16px)

| Token | Tamanho / linha | Peso | Uso |
|-------|-----------------|------|-----|
| `display` | 2.5rem / 1.1 | 600 | número-herói (saldo/sobra do mês) |
| `h1` | 1.75rem / 1.2 | 600 | título de página |
| `h2` | 1.375rem / 1.25 | 600 | seção |
| `h3` | 1.125rem / 1.3 | 600 | subtítulo, título de cartão |
| `body` | 0.9375rem / 1.5 | 400 | texto padrão (15px) |
| `body-sm` | 0.8125rem / 1.45 | 400 | secundário (13px) |
| `label` | 0.75rem / 1.4 | 500 | rótulos de campo/métrica (**sem** uppercase) |
| `mono-num` | herda | 500–600 | valores monetários, tabular |

### 2.3 Regras de tipografia (o fim do "loud")

- ❌ **Banir `font-black` (900) como padrão.** Reservar peso 700+ só para números-herói.
  Padrão de destaque = **Semibold (600)**.
- ❌ **Banir `uppercase` + `tracking-widest` em rótulos.** Micro-labels viram `label`
  (13/12px, peso 500, _sentence case_). Ex.: "Previsão fim do mês", não
  "PREVISÃO FIM DO MÊS".
- ✅ Máximo **2 pesos** por bloco visual.
- ✅ Números sempre tabulares e alinhados à direita em colunas.
- ✅ Moeda pt-BR sempre: `R$ 1.234,56` (via `formatMoney`, ver 05).

---

## 3. Espaçamento, raio, elevação

### 3.1 Espaçamento (escala 4px — já é o Tailwind)
Usar a escala nativa; **padronizar ritmos**:
- Padding de cartão: `20px` (`p-5`) desktop, `16px` mobile.
- Gap entre cartões/seções: `24px` (`gap-6`).
- Gap interno de grupo: `8–12px`.
- Largura máxima de conteúdo: `1200px` (hoje é `max-w-6xl`/1152 — manter ~esse).
- Gutter de página: `32px` desktop (`p-8`), `16px` mobile.

### 3.2 Raio (uma escala só)
```
--radius-sm: 0.5rem;   /* 8px  — inputs, botões, chips, badges */
--radius-md: 0.75rem;  /* 12px — cartões pequenos, dropdowns */
--radius-lg: 1rem;     /* 16px — cartões grandes, dialogs, herói */
--radius-full: 9999px; /* avatares, pílulas */
```

### 3.3 Elevação (suave, escassa)
Só elementos **flutuantes** têm sombra. Superfícies estáticas usam borda.
```
--shadow-sm:  0 1px 2px oklch(0 0 0 / 0.04);                 /* card hover leve */
--shadow-md:  0 4px 12px oklch(0 0 0 / 0.08);                /* dropdown, popover */
--shadow-lg:  0 12px 32px oklch(0 0 0 / 0.12);               /* dialog, sheet */
```
❌ Abolir `shadow-lg shadow-primary/20` (sombra colorida) em cartões estáticos.

---

## 4. Motion

- Duração: `120ms` (feedback/hover), `180ms` (entrada de conteúdo), `240ms` (overlays).
- Easing: `cubic-bezier(0.2, 0, 0, 1)` (ease-out) para entrada; `ease-in` para saída.
- Só animar: entrada de conteúdo (fade+rise 4px), abertura de overlay (fade+scale 98→100),
  troca de aba (crossfade curto), toasts.
- ❌ Sem "pulo" de escala em hover de cartão. Hover = mudança sutil de `background`/`border`.
- ✅ Respeitar `@media (prefers-reduced-motion: reduce)` → desabilitar transform, manter
  opacity ≤ 100ms.
- Manter Framer Motion só onde há orquestração (listas, reordenação); o resto com
  `tw-animate-css` / transições CSS.

---

## 5. Densidade & grid

- **Grid de página**: 12 colunas conceituais, mas na prática usar flex/`grid` utilitário
  do Tailwind. Herói ocupa largura total ou 2/3; métricas numa linha de 3–4.
- **Duas densidades de tabela**: `comfortable` (48px linha) default; `compact` (36px) para
  faturas/parcelas longas. Definido no componente `DataTable` (05).
- **Breakpoints** (Tailwind default): `sm 640`, `md 768`, `lg 1024`, `xl 1280`.
  - `< md`: sidebar vira bottom-nav; grids de métrica empilham 2-col; tabelas viram
    _cards_ empilhados (ver 04/05).

---

## 6. Iconografia
- `lucide-react` (mantido). Tamanho padrão 16–18px em linha, 20–24px em destaque.
- Traço 1.75–2px. Cor herda de `currentColor` (nunca cor fixa).
- Ícone de categoria: mapear os `icon` já vindos do back (`utensils`, `car`, `home`…) para
  lucide, com a `color` da categoria como tint de fundo (chip `--surface-2` + ícone na cor).

---

## 7. Acessibilidade (baseline do sistema)
- Contraste AA em todos os pares texto/fundo (validar tokens acima).
- Foco **sempre visível**: anel `--ring` de 2px + offset 2px. Nunca `outline: none` sem
  substituto.
- Alvos de toque ≥ 40×40px no mobile (hoje há botões de 32px `h-8` — subir no mobile).
- Ações que hoje só aparecem no `hover` (editar/excluir) precisam de alternativa acessível
  por teclado/foco e no mobile (ver 05, `TransactionItem`).
- `aria-label` em botões-ícone (já existe em vários; padronizar).

---

## 8. Entregável desta camada (o que a Fase 1 produz)
1. `src/index.css` reescrito com os tokens acima (`:root` + `.dark` + mapa de compat).
2. `tailwind.config.js` estendido com os nomes semânticos:
   `bg`, `surface`, `surface-2`, `text`, `text-muted`, `border`, `brand`, `income`,
   `expense`, `warning`, `chart-1..6`, e os raios/sombras.
3. Um arquivo `src/styles/tokens.md` (ou Storybook leve) mostrando a paleta e a escala —
   referência viva para quem implementa.
4. Classe utilitária `.tabular` (`font-variant-numeric: tabular-nums`).

Com isso pronto, os componentes (05) e telas (06/07) têm vocabulário para existir.
