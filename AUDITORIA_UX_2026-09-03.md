# Auditoria de UI/UX, usabilidade e experiência — ControleFinanceiro V4

**Data:** 2026-09-03 (revisto em 2026-09-04 com 2 casos trazidos pelo dono)
**Branch:** `main` (`5dc2072`) · **Fase:** 1 (auditoria — nada implementado)
**Ambiente:** Windows 11 · Chromium (Playwright) · backend do venv na 8000 (`shots.db` semeado) · Vite na 5173
**Conta usada:** `demo@cf4.app` (semeada por `npm run shots`, 4 membros, 48 lançamentos, 5 cartões, 5 financiamentos, 5 contas)
**Contas extras criadas para o teste:** 3 (usuário novo, conta vazia, conta de onboarding)

> Todo achado abaixo foi **reproduzido no navegador**, com medição no DOM ou captura de tela.
> O que não passou de hipótese está na seção 16 ("o que eu achei que era problema e não era").

---

# 1. Resumo executivo

## Avaliação geral

Este é um frontend **muito acima da média**, e a distância entre ele e um produto excelente é
menor do que a lista de achados sugere. Os fundamentos estão certos: existe design system
com tokens em `oklch`, tema claro e escuro coerentes, estados vazios que **explicam** e
oferecem a próxima ação, microcopy pensada (os Acertos falam em português de gente:
"Bruno deve R$ 437,25 a você"), validação inline com foco no primeiro campo inválido,
trava de duplo clique nas mutações, erro do servidor mostrado **dentro do formulário sem
perder o que foi digitado**, e um portão de largura a 360px que segura firme — varri
24 rotas em 10 larguras de 320 a 1920 px e **não há uma única rolagem horizontal**.

O que a auditoria encontrou concentra-se em quatro lugares:

1. **A linha do extrato no celular.** O título do lançamento — o dado que identifica a
   despesa — é espremido a **0px de largura em 14 de 15 linhas** a 390px, e as pílulas de
   status transbordam por cima do valor. É o defeito mais grave do relatório e está na
   tela mais usada do app, no aparelho para o qual ele virou PWA.
2. **A faixa 768–1100px.** A barra lateral já aparece, o conteúdo ainda não tem espaço, e
   nenhum teste mede essa faixa. A lista de membros fica **ilegível** (nomes a 0–24px) com
   os controles de papel e de exclusão funcionando normalmente ao lado.
3. **A altura de 768px.** O botão "Salvar Despesa" **não está visível em nenhuma resolução
   exceto 1920×1080** (medido), e o item ativo da barra lateral fica fora da tela nas
   páginas de Administração, Configurações e Importar.
4. **O que acontece quando algo dá errado.** Sessão que expira com o app aberto = spinner
   infinito; queda de rede numa recarga = tela de login, como se a conta tivesse sumido;
   `/me/balance` que falha = os blocos somem sem aviso.
5. **O que só existe no aparelho de verdade** (acrescentado em 2026-09-04, a partir do
   relato do dono): a barra de status do celular fica branca e ilegível, e o topo do app
   não reserva a área do sistema — enquanto o rodapé reserva, com comentário explicando
   por quê. Somado a isso, campos numéricos guardam o zero à esquerda ("0" + "5" = "05"),
   fazendo um campo de número parecer campo de texto quebrado.

## Notas (0 a 10)

| Dimensão | Nota | Por quê |
|---|:--:|---|
| **UI (visual)** | 8,0 | Paleta, tipografia e superfícies coerentes; tema escuro tão cuidado quanto o claro. Perde por 46 cores fora do design system em 17 arquivos (dois verdes diferentes convivendo) e pelo vazio de 700×216px no Painel. |
| **UX (fluxos)** | 7,5 | Fluxos completos e bem pensados; vocabulário deliberado. Perde por perda de dados no Escape, CTA fora da tela, e três comportamentos diferentes de aba. |
| **Responsividade** | 6,5 | Zero rolagem horizontal de 320 a 1920px — raro. Mas a faixa 768–1100 quebra conteúdo e o extrato mobile perde o título. |
| **Acessibilidade** | 6,0 | Landmarks, hierarquia de headings, focus trap e contraste dos tokens estão certos. Falta skip link, `aria-current` na barra lateral, nome acessível em 4 comboboxes, label em 7 campos, e há 3 falhas de contraste medidas. |
| **Consistência** | 6,5 | Um design system real, mas contornado em 17 arquivos; 3 padrões de aba; 2 componentes de KPI; "workspace" vazando em 3 rótulos contra a decisão do próprio projeto. |
| **Clareza** | 9,0 | O ponto mais forte. Cada número diz o que é e o que não é; os estados vazios ensinam; os textos de apoio distinguem competência de caixa. |
| **Eficiência (usuário recorrente)** | 7,0 | Mês na URL, FAB no celular, filtros bons. Perde por não guardar busca/filtros/aba na URL e por não ter atalhos. |
| **Experiência mobile** | 5,5 | Barra inferior, gaveta "Mais", tabelas viradas em cartões, alvos de 40px no extrato — tudo certo. Derrubada pelo título de 0px e por alvos de 28px nas ações secundárias. |
| **Experiência desktop** | 7,5 | Excelente em 1920×1080. Em 1366×768 (o mais comum) a dobra e a barra lateral cobram caro. |
| **Qualidade geral** | 7,5 | Produto maduro com defeitos localizados e de causa conhecida — quase todos com correção de baixo risco. |

## Achados por severidade

| Severidade | Qtd |
|---|---:|
| **P0 — Crítico** | 1 |
| **P1 — Alto** | 11 |
| **P2 — Médio** | 18 |
| **P3 — Baixo** | 8 |
| **Total** | **38** |

> **Revisão de 2026-09-04.** O dono relatou dois casos que esta auditoria não tinha
> encontrado. Os dois foram **reproduzidos** e entram como **PWA-037** e **FORM-038**
> (seção 5). O primeiro é um ponto cego real do método: eu medi viewports, não o
> aparelho — a área da barra de status não existe num navegador de desktop. O segundo
> escapou porque eu testei os formulários **preenchendo** campos (`fill`), e `fill`
> substitui o valor inteiro; o defeito só aparece quando se **digita** sobre o que já
> está lá. Ambas as lições estão na seção 17.

---

# 2. Pontos fortes (preservar — não mexer na Fase 2)

Isto não é cortesia: cada item abaixo foi verificado e **deve ser protegido** de regressão
durante a implementação.

1. **Estados vazios.** Percorri as 17 rotas com uma conta recém-criada. **Todas** explicam
   o que não há, por quê, e o que fazer — com CTA quando cabe. Exemplo: "Nenhuma conta
   cadastrada · Cadastre suas contas, carteiras e o dinheiro vivo para o app saber onde o
   seu dinheiro está". É melhor que a média do mercado. **Não redesenhar.**
2. **Erro de servidor no formulário.** Simulei 500 no `POST /transactions/`: o diálogo
   **continua aberto**, mostra a mensagem do servidor em vermelho acima do botão, e o texto
   digitado **sobrevive**. Padrão exemplar (evidência `E10`).
3. **Trava de duplo clique.** Dois cliques em "Salvar Despesa" → **1 POST**. Medido.
4. **Validação inline.** Submit vazio mostra erro por campo e devolve o foco ao primeiro
   inválido. Sem `alert()` em lugar nenhum.
5. **Confirmação de ações destrutivas.** `useConfirm` substitui `window.confirm`, o botão
   destrutivo tem variante própria, "Cancelar" vem primeiro e recebe o foco inicial.
   As confirmações **nomeiam o alvo** ("Excluir o financiamento «Notebook»?").
6. **Vocabulário.** A decisão "Pessoal × Compartilhado" e "espaço" está documentada em
   `nav-items.ts` e aplicada em quase toda a interface. Os pares homônimos foram resolvidos
   com nomes ("Seus acertos" × "Acertos", "Compromissos" × "Contas a pagar").
7. **Portão de 360px.** `e2e/mobile_layout.mobile.spec.ts` funciona: 24 rotas × 10 larguras
   (320→1920) = **zero rolagem horizontal**, inclusive com título de 150 caracteres e valor
   de R$ 1.234.567,89 que criei de propósito.
8. **Tabelas viradas em cartões no celular.** Rendas, Recorrência e Financiamentos não são
   tabela espremida: são cartões com as ações à mão. É a solução certa.
9. **Tema escuro.** Não é um filtro: tokens próprios, contraste conferido, e as 60 telas
   escuras do catálogo estão tão acabadas quanto as claras.
10. **Acertos "Por mês".** Frases em vez de tabela ("Téo deve R$ 193,79 a você") com a ação
    ao lado. É a melhor tela do produto.
11. **Focus trap.** Tab e Shift+Tab não escapam do diálogo. O onboarding é bloqueante mas
    é um `Dialog` de verdade (inerte atrás, `aria-modal`, foco preso).
12. **Skeletons na maioria das telas** e `ErrorState` com "Tentar novamente" em `/overview`.

---

# 3. Problemas críticos (atenção imediata)

## P0

- **MOB-001** — No celular, a lista de lançamentos **não mostra a descrição de nenhuma
  despesa** e as pílulas de status invadem o valor.

## P1 (os que eu corrigiria na mesma semana)

- **RESP-002** — Membros do espaço ilegíveis entre 768 e 1100px, com "excluir" ativo.
- **RESP-003** — Campo de e-mail do convite colapsado (~20px) na mesma faixa.
- **UX-004** — "Salvar Despesa" fora da tela em tudo que não seja 1920×1080.
- **NAV-005** — Metade da navegação abaixo da dobra em 1366×768, sem afordância, e o item
  ativo invisível.
- **ERR-006** — Sessão que expira com o app aberto: spinner infinito, sem aviso.
- **ERR-007** — Queda de rede numa recarga leva à tela de login.
- **A11Y-008** — 4 filtros sem nome acessível na tela mais usada.
- **A11Y-009** — 7 campos do Importar sem rótulo associado.
- **A11Y-010** — Sem link "pular para o conteúdo": 14+ Tabs até chegar na página.
- **PWA-037** — A barra de status do celular fica branca e ilegível, e a área dela não é
  reservada por CSS nenhum.
- **FORM-038** — Campos numéricos guardam o zero à esquerda: "0" + "5" fica **"05"** na tela.

---

# 4. Inventário de telas testadas

Legenda: ✅ sem achado · ⚠️ achado médio/baixo · ❌ achado alto/crítico

| Tela / fluxo | Rota | 1920×1080 | 1366×768 | 768–1024 | Mobile 390/360 | Resultado |
|---|---|:--:|:--:|:--:|:--:|---|
| Login | `/login` | ✅ | ✅ | ✅ | ✅ | Sem achado |
| Cadastro | `/register` | ✅ | ⚠️ | ✅ | ✅ | Erro de senha cruza o divisor do cartão |
| Esqueci a senha | `/forgot-password` | ✅ | ✅ | ✅ | ✅ | — |
| Redefinir senha | `/reset-password` | ✅ | ✅ | ✅ | ✅ | Estado de link inválido correto |
| Onboarding (modal) | (sobre `/overview`) | ⚠️ | ⚠️ | ⚠️ | ⚠️ | UX-026 |
| Seu mês | `/overview` | ✅ | ⚠️ | ⚠️ | ⚠️ | FDB-014, MOB-024 |
| Contas | `/me/accounts` | ✅ | ✅ | ⚠️ | ⚠️ | Nome a 170px em 768; alvos 28px |
| Contas a pagar (pessoal) | `/me/payables` | ✅ | ✅ | ✅ | ⚠️ | 7.283px de altura em 360; UX-031 |
| Rendas | `/me/income` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | UI-011 (contraste 2,24:1), UI-033 |
| Cartões | `/me/cards` | ✅ | ✅ | ✅ | ⚠️ | Pílula "Aberta" com contraste baixo |
| Financiamentos | `/me/financing` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | UI-011 (2,47:1), A11Y progressbar sem nome |
| Compromissos | `/me/commitments` | ✅ | ✅ | ⚠️ | ⚠️ | Títulos truncados a 193–330px |
| Seus acertos (3 abas) | `/me/settlements` | ✅ | ✅ | ✅ | ⚠️ | Abas de 28px |
| Seus relatórios | `/me/reports` | ✅ | ✅ | ✅ | ✅ | — |
| Extrato | `/me/ledger` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | FDB-012, A11Y scrollable-region |
| Suas configurações | `/me/settings` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | CONT-023, NAV-021 |
| Painel do espaço | `/w/:id` | ⚠️ | ❌ | ⚠️ | ⚠️ | UI-022 (700×216px vazios) |
| **Lançamentos** | `/w/:id/transactions` | ⚠️ | ⚠️ | ⚠️ | ❌ | **MOB-001**, A11Y-008, A11Y-016 |
| Contas a pagar (espaço) | `/w/:id/payables` | ✅ | ✅ | ✅ | ⚠️ | 6.458px em 360 |
| Relatórios | `/w/:id/reports` | ✅ | ✅ | ⚠️ | ⚠️ | UI-025, UI-030, MOB-028 |
| Recorrência | `/w/:id/recurring` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | UI-011 (8 nós), UI-033 |
| Acertos (3 abas) | `/w/:id/debts` | ✅ | ✅ | ✅ | ⚠️ | Abas de 28px |
| Importar | `/w/:id/import` | ❌ | ❌ | ❌ | ❌ | A11Y-009, UX-032 |
| **Configurações do espaço** | `/w/:id/settings` | ✅ | ✅ | ❌ | ⚠️ | **RESP-002**, **RESP-003**, CONT-023 |
| Administração (6 abas) | `/admin` | ✅ | ⚠️ | ⚠️ | ⚠️ | NAV-005, NAV-021 |
| Aceitar convite | `/invite/:token` | ✅ | ✅ | ✅ | ✅ | — |
| Nova despesa (modal) | global | ⚠️ | ❌ | ❌ | ❌ | **UX-004**, UX-015, **FORM-038** (Qtd) |
| Novo cartão (modal) | `/me/cards` | ❌ | ❌ | ❌ | ❌ | **FORM-038** (2 campos) |
| Novo financiamento (modal) | `/me/financing` | ❌ | ❌ | ❌ | ❌ | **FORM-038** (parcelas) |
| Editor de recorrência | modal | ❌ | ❌ | ❌ | ❌ | **FORM-038** (3 campos) |
| Barra de status / área segura | todas | — | — | — | ❌ | **PWA-037** (só verificável em aparelho) |
| Detalhe do lançamento (modal) | global | ✅ | ✅ | ✅ | ✅ | — |
| Confirmação destrutiva (modal) | global | ✅ | ✅ | ✅ | ✅ | — |
| Filtros (gaveta) | mobile | — | — | — | ✅ | Bom padrão |
| Gaveta "Mais" | mobile | — | — | — | ✅ | — |
| Seletor de escopo | global | ✅ | ✅ | ✅ | ✅ | — |
| Central de avisos | global | ⚠️ | ⚠️ | ⚠️ | ⚠️ | UI-027 (dois sinos) |
| Toasts | global | ✅ | ✅ | ✅ | ✅ | — |
| Rota inexistente | `/qualquer-coisa` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | NAV-019 |
| Espaço inexistente | `/w/99999` | ⚠️ | ⚠️ | ⚠️ | ⚠️ | NAV-019 |
| Sessão expirada | qualquer | ❌ | ❌ | ❌ | ❌ | **ERR-006** |
| Sem rede | qualquer | ❌ | ❌ | ❌ | ❌ | **ERR-007** |

---

# 5. Problemas encontrados

---

## MOB-001 — No celular a lista de lançamentos não mostra a descrição de nenhuma despesa

**Categoria:** Responsividade / Bug · **Prioridade:** P0 · **Severidade:** Crítica
**Tela:** Lançamentos (e Painel a 320px) · **Rota:** `/w/:id/transactions`
**Resolução:** 390×844, 360×800, 320×800 (e degradado desde 430px)

### Problema

O título do lançamento é espremido até **0px de largura**. A linha exibe glifo de categoria,
pílula "Pendente", pílula "A pagar", valor e os botões de editar/excluir — **e nada que
identifique a despesa**. A pílula "A pagar", também espremida, quebra em duas linhas e o
texto **transborda por cima do valor em dinheiro**.

### Como reproduzir

1. Entrar com uma conta que tenha lançamentos não liquidados (`Já foi paga` desmarcada).
2. Abrir `/w/1/transactions` numa viewport de 390×844.
3. Ler a lista.

### Medição (larguras do título, 15 linhas na página)

| Largura | Títulos com 0px | Menor | Maior |
|---:|---:|---:|---:|
| 1366 | 0 | 28px | 401px |
| 768 | 0 | 28px | 213px |
| 430 | 0 | **12px** | 131px |
| 412 | **2 de 15** | 0px | 113px |
| **390** | **14 de 15** | 0px | 91px |
| **360** | **14 de 15** | 0px | 61px |
| **320** | **14 de 15** | 0px | 21px |

### Impacto

A tela mais visitada do produto, no aparelho para o qual ele virou PWA, deixa de responder
a "que despesa é esta?". Restam quatro valores de R$ 12,50 indistinguíveis, com um botão de
excluir ao lado de cada um. É a combinação mais perigosa possível: ação destrutiva sobre
uma linha que não pode ser identificada.

### Evidência

`E01-lancamentos-390-sem-titulo.png`, `E02-lancamentos-390-pilula-sobre-valor.png`

### Causa provável

`frontend/src/components/money/TransactionItem.tsx:109-116`:

```tsx
<div className="min-w-0 flex-1">
  <div className="flex items-center gap-1.5">
    <p className="truncate text-sm font-medium text-foreground">{tx.title}</p>
    {status && <StatusPill …>}
    {liquidacao && <StatusPill …>}
```

O `<p>` tem `truncate` (`overflow:hidden`), o que zera o `min-width:auto` automático do
item flex — ele pode encolher **até zero**. As `StatusPill` não encolhem
(`whitespace-nowrap`, `shrink-0` na prática). Quando as duas pílulas + glifo + valor +
2 botões de 40px passam da largura da linha, o único que cede é o título.
Por isso o defeito aparece só nas linhas com **as duas** pílulas.

Nenhum teste pega: `mobile_layout.mobile.spec.ts` mede `scrollWidth` — e um texto
truncado a zero **não estoura nada**.

### Solução recomendada

1. No celular, empilhar: título em linha própria (largura total) e as pílulas na linha da
   meta, abaixo — é o layout que a densidade da tela pede.
2. Dar às pílulas `min-w-0` + `truncate` para nunca transbordarem sobre o valor.
3. Estender o gate: além de `scrollWidth`, assertar que **todo elemento com `truncate` e
   texto tem `clientWidth ≥ 40px`** nas rotas medidas. Este é o portão que impede a volta.

### Arquivos envolvidos

- `frontend/src/components/money/TransactionItem.tsx`
- `frontend/src/components/ui/status-pill.tsx`
- `frontend/e2e/mobile_layout.mobile.spec.ts` (gate novo)

### Esforço

**Baixo** (CSS) + **Baixo** (gate).

---

## RESP-002 — Entre 768 e 1100px os membros do espaço ficam ilegíveis, com os controles ativos

**Categoria:** Responsividade / Bug · **Prioridade:** P1 · **Severidade:** Alta
**Tela:** Configurações do espaço → Espaço e membros · **Rota:** `/w/:id/settings`
**Resolução:** 768×1024, 900×800, 1024×768

### Problema

Nome e e-mail de cada membro são truncados a **0–24px**. A tela mostra "B / E / b",
"C… / ca…", "T / t." — e ao lado, funcionando normalmente, os selects de **papel**
(Membro/Admin/Leitor), de **visibilidade** e o botão de **remover membro**.

### Como reproduzir

1. Abrir `/w/1/settings` com 4 membros numa viewport de 1024×768.
2. Tentar dizer de quem é cada linha.

### Medição (DOM)

| Largura | `Bruno Nascimento Albuquerque` (212px de texto) | `bruno.demo@cf4.app` |
|---:|---:|---:|
| 1366 | 212px (íntegro) | íntegro |
| 1024 | **6px** | **6px** |
| 900 | **0px** | **0px** |
| 768 | **0px** | **0px** |
| 390 | íntegro (layout empilha) | íntegro |

### Impacto

É a tela de **permissões**. Rebaixar alguém a Leitor ou remover a pessoa errada é
irreversível pela interface, e nessa faixa não há como saber em quem se está clicando.
1024×768 é iPad em paisagem, notebook antigo e janela dividida em qualquer monitor.

### Evidência

`E03-membros-1024-ilegivel.png`

### Causa provável

`frontend/src/pages/Settings/SettingsPage.tsx` (aba de membros): a linha é um flex com o
bloco de identidade concorrendo com **dois selects e um botão de largura fixa**, sem
`flex-wrap` e sem largura mínima para o bloco de identidade. Mesma mecânica do MOB-001.

### Solução recomendada

Quebrar a linha em duas abaixo de `lg`: identidade em cima, controles embaixo
(`flex-col lg:flex-row`), com `min-w-[12rem]` no bloco de identidade.

### Arquivos envolvidos

- `frontend/src/pages/Settings/SettingsPage.tsx`

### Esforço

**Baixo**.

---

## RESP-003 — O campo de e-mail do convite fica com ~20px de largura na mesma faixa

**Categoria:** Responsividade · **Prioridade:** P1 · **Severidade:** Alta
**Rota:** `/w/:id/settings` → Convidar Pessoas · **Resolução:** 768–1024px

### Problema

O `input` de e-mail colapsa a uma caixa vazia de ~20px; o botão de copiar link fica
cortado na borda do cartão. Não dá para convidar ninguém nessa largura.

### Como reproduzir

1. `/w/1/settings` em 1024×768.
2. Olhar o bloco "Convidar Pessoas" (evidência `E03`, faixa inferior).

### Causa provável / Solução

Mesma da RESP-002 — a linha de convite é `flex` com input + 2 selects + 2 botões sem
`flex-wrap`. Envolver em `flex-wrap` e dar `min-w-[16rem]` ao input.

### Esforço

**Baixo**.

---

## UX-004 — "Salvar Despesa" está fora da tela em toda resolução exceto 1920×1080

**Categoria:** UX / Formulário · **Prioridade:** P1 · **Severidade:** Alta
**Tela:** Nova Despesa (modal global) · **Rota:** qualquer

### Problema

Ao abrir o formulário mais importante do produto, o botão que o conclui não está visível.
O diálogo tem rolagem interna e **não tem rodapé fixo**.

### Medição (posição do botão × altura da janela, medida no DOM)

| Viewport | Topo do botão | Altura da janela | Visível? |
|---|---:|---:|:--:|
| 1920×1080 | 941 | 1080 | ✅ |
| 1600×900 | 928 | 900 | ❌ |
| **1366×768** | **918** | 768 | ❌ |
| 1280×720 | 914 | 720 | ❌ |
| 1024×768 | 918 | 768 | ❌ |
| **390×844** | **1166** | 844 | ❌ (322px abaixo) |
| 360×800 | 1182 | 800 | ❌ |

### Impacto

Toda criação de despesa — a ação central do app — exige rolar um modal para encontrar o
botão. Usuário novo pode concluir que o formulário não tem como ser enviado; usuário
recorrente paga o pedágio de uma rolagem em cada lançamento.

### Evidência

`E04-modal-1366-salvar-fora-da-tela.png`

### Causa provável

`frontend/src/components/ui/dialog.tsx:58` — `sm:max-h-[85vh]` com o conteúdo inteiro
(incluindo as ações) dentro da área rolável. Não há `sticky` no rodapé.

### Solução recomendada

Rodapé fixo no `DialogContent`: cabeçalho e ações fora da área de rolagem
(`grid-rows-[auto_1fr_auto]`), com `position: sticky; bottom: 0` e um `border-t` +
`bg-card` para separar. Aplicar ao primitivo, não só a este formulário — vale para todos
os diálogos longos.

### Arquivos envolvidos

- `frontend/src/components/ui/dialog.tsx`
- `frontend/src/components/dashboard/NewTransactionDialog.tsx`
- `frontend/src/components/dashboard/transaction-form/TransactionForm.tsx`

### Esforço

**Médio** (mexe no primitivo usado por ~12 diálogos; exige revisão visual de todos).

---

## NAV-005 — Em 1366×768 metade da navegação fica abaixo da dobra e o item ativo some

**Categoria:** Navegação · **Prioridade:** P1 · **Severidade:** Alta
**Rota:** todas as autenticadas · **Resolução:** 1366×768 (e 1920×1080 para `/admin`)

### Problema

A barra lateral tem 21 itens (12 pessoais + 8 do espaço + Administração) e ~1.100px de
altura, num painel de 768px. O `nav` rola, mas:

- **não há afordância nenhuma** (sem sombra, sem gradiente, sem barra visível);
- o item ativo **não é rolado para a vista**.

### Medição (posição do item ativo × altura da janela)

| Rota | Topo do item ativo | 1366×768 | 1920×1080 |
|---|---:|:--:|:--:|
| `/admin` | 1066 | ❌ fora | ❌ fora |
| `/w/:id/settings` | 969 | ❌ fora | ✅ |
| `/w/:id/import` | 929 | ❌ fora | ✅ |
| `/me/settings` | 592 | ✅ | ✅ |

### Impacto

Duas perguntas ficam sem resposta ao mesmo tempo: **"onde estou?"** (nada aceso na barra)
e **"para onde posso ir?"** (Lançamentos, Relatórios, Acertos e Importar invisíveis em
`/admin`). Um usuário novo em 1366×768 pode concluir que o espaço compartilhado tem só o
cabeçalho "COMPARTILHADO".

### Evidência

`E05-sidebar-1366-item-ativo-invisivel.png` — nesta captura, estando **em** Administração,
nenhum item está aceso e a seção "COMPARTILHADO" aparece sem um único item.

### Causa provável

`frontend/src/components/layout/Sidebar.tsx:89` — `<nav className="flex-1 … overflow-y-auto">`
sem `scrollIntoView` do ativo e sem indicação de continuidade.

### Solução recomendada

1. `scrollIntoView({ block: 'nearest' })` no item ativo ao montar e a cada mudança de rota.
2. Máscara de gradiente no topo/base do `nav` enquanto houver conteúdo fora da vista.
3. (Estrutural, avaliar) tornar a seção **Pessoal** recolhível quando há um espaço aberto —
   é a que tem 12 itens e a que menos se usa estando dentro de um espaço.

### Esforço

**Baixo** (1 e 2) · **Médio** (3).

---

## ERR-006 — Sessão que expira com o app aberto deixa a tela em spinner infinito

**Categoria:** Bug / Feedback · **Prioridade:** P1 · **Severidade:** Alta
**Rota:** qualquer autenticada

### Problema

Com o app aberto, se a sessão morre (cookie expirado ou revogado), a próxima navegação
interna **gira para sempre**. Não redireciona para `/login`, não mostra erro, não oferece
nada. Só uma recarga completa (F5) resolve — e o usuário não tem como saber disso.

### Como reproduzir

1. Entrar e abrir `/overview`.
2. Apagar os cookies (ou esperar o refresh token vencer).
3. Clicar em "Cartões" na barra lateral.
4. Esperar. Reproduzido com cookies apagados de verdade **e** com 401 forçado; 3 de 3.

### Impacto

O sintoma que o usuário relata é "o app travou". A tela fica com o cabeçalho da página
certa e um spinner no meio do conteúdo, indefinidamente (evidência `E08`).

### Evidência

`E08-sessao-expirada-spinner-infinito.png`

### Causa provável

`frontend/src/api/client.ts:66-77` — no ramo de refresh falhado, o interceptor faz
`useAuthStore.getState().logout()` e o comentário diz *"o ProtectedRoute redireciona ao ver
que não há usuário"*. **Isso deixou de ser verdade**: o `ProtectedRoute` foi movido para
`useAuth()` (react-query) justamente para resolver outra corrida — e o `auth-me` continua
no cache como sucesso (a query é preservada de propósito pelo `predicate`). Resultado: o
store diz "saiu", o guard diz "está dentro", e as demais queries ficam em erro/pendentes.

O teste que existe (`e2e-prod/sessao_expirada.spec.ts`) cobre só a **carga fria** com
cookie inválido — que funciona. A expiração **durante** a sessão não é medida por nada.

### Solução recomendada

No `catch` do interceptor, invalidar/derrubar também o estado de autenticação que o guard
lê: `queryClient.setQueryData(['auth-me'], null)` (ou `resetQueries` na chave), de modo que
o `ProtectedRoute` conclua "sem sessão" e redirecione com `state.from`. Acrescentar um
teste E2E que expira a sessão **com o app montado**.

### Arquivos envolvidos

- `frontend/src/api/client.ts`
- `frontend/src/hooks/use-auth.ts`
- `frontend/e2e/` (spec novo)

### Esforço

**Baixo** (correção) · **Baixo** (teste).

---

## ERR-007 — Queda de rede numa recarga leva o usuário à tela de login

**Categoria:** Feedback / Erro · **Prioridade:** P1 · **Severidade:** Alta
**Rota:** qualquer autenticada

### Problema

Com a API inalcançável (falha de rede, backend fora, túnel caído), recarregar qualquer
página apresenta a tela de **login** — "Bem-vindo · Entre com suas credenciais". A sessão
continua válida; o app apenas não conseguiu perguntar.

### Como reproduzir

1. Entrar normalmente.
2. Derrubar a rede (ou o backend) e apertar F5.
3. Depois de ~3 tentativas do react-query: tela de login.

### Impacto

O usuário conclui que foi desconectado e digita a senha — que também falha, agora com
mensagem de erro. Para um app financeiro, "sua sessão sumiu" é uma mensagem cara.

### Causa provável

`useAuth`/`ProtectedRoute` tratam **qualquer** falha de `/auth/me` como "não autenticado".
O `retry` do QueryClient distingue 4xx de erro de rede, mas o **consumidor** não distingue
`error` de `isAuthenticated === false`.

### Solução recomendada

Separar os dois estados: erro de rede/5xx em `/auth/me` → tela de "sem conexão com o
servidor" com botão "Tentar de novo" (o `ErrorState` já existe); **401 explícito** →
`/login`. É a mesma regra ERR-001 que a `OverviewPage` já aplica internamente.

### Esforço

**Baixo**.

---

## A11Y-008 — Os quatro filtros de Lançamentos não têm nome acessível

**Categoria:** Acessibilidade · **Prioridade:** P1 · **Severidade:** Alta (axe: *critical*)
**Rota:** `/w/:id/transactions`

### Problema

Os quatro `Select` (pagamento, categoria, situação, tag) renderizam
`<button role="combobox">` cujo conteúdo é o **valor atual**, não o nome do campo. Como
`combobox` não é papel que aceita "nome pelo conteúdo", os quatro ficam **sem nome
acessível**. Um leitor de tela anuncia "caixa de combinação, recolhida" quatro vezes.

### Evidência

```
## button-name [critical] (4)
  <button role="combobox" aria-expanded="false" data-slot="select-trigger" id="base-ui-_r_12_">
  <button role="combobox" … id="base-ui-_r_15_">
  <button role="combobox" … id="base-ui-_r_18_">
  <button role="combobox" … id="base-ui-_r_1b_">
```

### Causa provável

`frontend/src/components/ui/select.tsx:29-58` — o `SelectTrigger` não aceita nem propaga
rótulo; nenhum chamador passa `aria-label`.

### Solução recomendada

Aceitar (e exigir por tipo) um `aria-label` no `SelectTrigger`, ou passar
`aria-label="Filtrar por forma de pagamento"` etc. em cada uso. Como o padrão visual "o
valor é o rótulo" é bom, `aria-label` é a correção certa — não é preciso mudar o visual.

### Arquivos envolvidos

- `frontend/src/components/ui/select.tsx`
- `frontend/src/pages/TransactionsPage.tsx`, `GlobalLedgerPage.tsx` e demais usos

### Esforço

**Baixo**.

---

## A11Y-009 — Os sete campos da tela Importar não têm rótulo associado

**Categoria:** Acessibilidade · **Prioridade:** P1 · **Severidade:** Alta (axe: *critical*)
**Rota:** `/w/:id/import`

### Problema

Existe rótulo **visual** ("Delimitador", "Sep. Decimal", "Formato Data", "Coluna Data"…),
mas nenhum `<Label htmlFor>` e nenhum `id` nos `<Input>`. Para tecnologia assistiva são
sete campos de texto sem nome. Clicar no rótulo também não foca o campo.

### Evidência (código)

`frontend/src/pages/ImportPage.tsx:129-162` — sete pares `<Label>…</Label>` + `<Input …>`
sem `htmlFor`/`id`.

### Solução recomendada

`id` em cada `Input` e `htmlFor` no `Label` correspondente. Considerar uma checagem no
lint (`jsx-a11y/label-has-associated-control`) para não voltar.

### Esforço

**Baixo**.

---

## A11Y-010 — Não existe "pular para o conteúdo"; são 14+ Tabs até a página

**Categoria:** Acessibilidade · **Prioridade:** P1 · **Severidade:** Alta (WCAG 2.4.1, nível A)
**Rota:** todas as autenticadas

### Problema

O primeiro Tab foca a marca; os 13 seguintes percorrem a barra lateral. Só no 15º Tab
(ou no 22º, dentro de um espaço) o foco chega ao conteúdo. **Em toda navegação de página.**

### Medição

`tab1` = "Controle Financeiro" · `tab3`…`tab13` = os 11 itens de Pessoal ·
`tab14` = "Painel" · busca por link de pular: **0 elementos**.

### Solução recomendada

Um `<a href="#conteudo" className="sr-only focus:not-sr-only …">Pular para o conteúdo</a>`
como primeiro filho do `AppShell`, e `id="conteudo"` + `tabIndex={-1}` no `<main>`.

### Arquivos envolvidos

- `frontend/src/components/layout/AppShell.tsx`

### Esforço

**Baixo**.

---

## PWA-037 — A barra de status do celular fica branca e ilegível, e a área dela não é reservada

**Categoria:** Mobile / PWA / UI · **Prioridade:** P1 · **Severidade:** Alta
**Tela:** todas, no celular · **Origem:** relatado pelo dono em 2026-09-04
**Cenário confirmado pelo dono:** **Android, app instalado, app no tema ESCURO**

### Problema

Duas coisas distintas acontecendo no mesmo lugar, e vale separá-las porque as correções
são diferentes:

**(a) A barra fica branca mesmo com o app no escuro — e a cor vem do manifesto.**

O app faz a parte dele **certo**: `use-theme.ts` mantém a meta `theme-color` sincronizada
com o tema aplicado, e a cor escura que ele grava é `#121215` — que dá **18,7:1** contra
ícones brancos. Medido:

| Fonte da cor | Valor | Contraste com ícone branco | Contraste com ícone preto |
|---|---|---:|---:|
| `<meta theme-color>` no tema claro | `#fcfbf9` | **1,03:1** | 20,31:1 |
| `<meta theme-color>` no tema escuro | `#121215` | 18,70:1 | 1,12:1 |
| **`manifest.theme_color`** (fixo) | **`#fcfbf9`** | **1,03:1** | 20,31:1 |
| `manifest.background_color` (fixo) | `#fcfbf9` | — | — |
| `--primary` do tema claro (marca) | `#4c55bc` | 6,30:1 | 3,33:1 |

A dedução fecha: com o app no escuro, a **única** fonte de cor clara que sobra é o
**manifesto** — e um manifesto não tem como acompanhar o tema, porque é lido na
instalação e não em tempo de execução. O app instalado no Android pinta a barra com
`theme_color: #fcfbf9`, que dá **1,03:1** contra ícones brancos: na prática, invisível.
Pelo mesmo motivo, a **splash** de toda abertura a frio é branca (`background_color`) num
app escuro.

Em iOS o quadro é análogo por outro caminho: `apple-mobile-web-app-status-bar-style` está
em `default` (`index.html:19`) e o iOS **ignora** a meta `theme-color` — a sincronização
que funciona no Android não o alcança.

**(b) A área da barra não é reservada por CSS nenhum.**
O `index.html:26` declara `viewport-fit=cover`, cujo efeito é justamente estender o layout
por baixo das áreas do sistema — e o comentário ali explica isso corretamente para o
**rodapé**. Mas:

- `env(safe-area-inset-bottom)` aparece em **5 lugares** (`AppShell`, `BottomNav`,
  `dialog.tsx`, `AdminPage`, a utilidade `pb-safe` do `index.css`);
- `env(safe-area-inset-top)` aparece em **zero**. Verificado em execução, varrendo todas
  as `CSSRule` da página: `algumaRegraUsaInsetTop: false`.

### Como reproduzir

1. Instalar o app no Android.
2. Deixar o app no tema escuro.
3. Abrir: a splash é branca e a barra de status fica branca sobre um app escuro, com os
   ícones do sistema ilegíveis.

### Medição (390×844, app rodando)

```
theme-color (tema claro) : #fcfbf9      ← 1,03:1 contra ícone branco
theme-color (tema escuro): #121215      ← 18,7:1  — o app faz a parte dele CERTO
manifest.theme_color     : #fcfbf9      ← FIXO, sem variante escura  ← a causa
manifest.background_color: #fcfbf9      ← FIXO (é a cor da splash)
apple-…-status-bar-style : default      ← o iOS ignora a meta theme-color

barra superior do app: top=0  altura=57px  padding=8px/8px   ← sem termo env()
primeiro botão dela  : top=8  altura=40px                    ← 8..48px
barra inferior       : padding-bottom com pb-safe            ← correto
env(safe-area-inset-top) referenciado em alguma regra: NÃO
```

> Um detalhe de operação que vale registrar para a validação: o WebAPK do Android guarda
> os valores do manifesto **na instalação**. Depois de mudar o manifesto, o Chrome só
> atualiza o atalho na varredura periódica dele — para conferir a correção **é preciso
> desinstalar e instalar de novo**, senão o teste dá falso negativo.

### Impacto

O item (a) é o que o dono vê: perde-se a hora, a bateria e os avisos do sistema enquanto o
app está aberto — num app que a pessoa deixa aberto para conferir dinheiro.

O item (b) é o que ainda **não** apareceu mas está armado: em qualquer configuração em que
o inset de topo passe a valer (iOS com `black-translucent`, Android edge-to-edge, notch em
paisagem), os 57px do topo do app ficam **por baixo** da barra do sistema — e é ali que
moram o seletor de espaço, o botão de instalar e os dois sinos. O rodapé foi protegido
justamente contra isso, com comentário explicando; o topo ficou sem.

### Causa provável

- `frontend/index.html:19` — `apple-mobile-web-app-status-bar-style` em `default`.
- `frontend/index.html:35` + `frontend/src/hooks/use-theme.ts:14` — `#fcfbf9`, claro
  demais para garantir contraste com ícones brancos.
- `frontend/public/manifest.webmanifest` — `theme_color` e `background_color` fixos no
  claro, sem variante para o tema escuro (e o manifesto não muda em tempo de execução).
- `frontend/src/components/layout/AppShell.tsx:62` — a barra superior é
  `sticky top-0 … py-2`, sem `padding-top: env(safe-area-inset-top)`.

### Solução recomendada

Três peças, e a ordem importa:

1. **Uma cor de manifesto que sirva aos dois temas.** Como `theme_color` não pode variar,
   ela tem de ser escolhida para funcionar no claro **e** no escuro. A candidata natural
   já está no design system: a marca, `#4c55bc` (`--primary` do tema claro), que dá
   **6,3:1** contra ícones brancos — folgado, e é a cor com que a pessoa já identifica o
   app. `background_color` acompanha, e a splash deixa de ser um clarão branco em quem usa
   o tema escuro. (A alternativa mais conservadora — deixar `theme_color` no `#121215` do
   tema escuro — resolve o contraste mas dá barra escura para quem usa o tema claro.)
2. **Reservar a área de cima.** Criar a utilidade `pt-safe` irmã da `pb-safe` que já
   existe (`index.css:287`) e aplicá-la à barra superior do `AppShell`, pintando a faixa
   com o fundo do app. Isto é correto independentemente do item 1 e não muda **nada** onde
   o inset é zero — ou seja, risco praticamente nulo no desktop e no navegador.
3. **iOS.** A meta é lida no lançamento e não acompanha o tema; a escolha é entre
   `default` (texto preto — certo para o tema claro, errado para o escuro) e
   `black-translucent` (texto branco + conteúdo por baixo, o que **exige** o item 2). A
   recomendação é `black-translucent` **depois** do item 2: aí o app controla a cor por
   trás da barra nos dois temas e o texto branco fica sobre a cor que ele escolheu.

Manter a sincronização de `theme-color` do `use-theme.ts` como está — ela é o que faz o
navegador (não instalado) acertar, e não é a causa do problema.

### Como validar

Não dá para validar no emulador — `env(safe-area-inset-top)` vale 0 num navegador de
desktop e a barra do sistema não existe ali. A validação é **no aparelho**:

1. **Desinstalar** o app e instalar de novo (senão o WebAPK segue com o manifesto antigo).
2. Abrir no tema escuro: a splash e a barra de status não podem ser brancas.
3. Alternar o tema do app e o modo do sistema — as quatro combinações — e conferir que
   hora, bateria e ícones de notificação continuam legíveis.
4. Conferir que o seletor de espaço e os dois sinos não ficam sob a barra do sistema.

O que **dá** para automatizar, e vale como portão barato: um teste que leia o
`manifest.webmanifest` e reprove se `theme_color` tiver contraste < 4,5:1 com branco
**e** com preto ao mesmo tempo — que é exatamente a condição em que a barra fica ilegível
para algum dos dois temas.

### Esforço

**Baixo** para os itens 1 e 2 · **Baixo** para o 3, mas exige teste em aparelho iOS real.

---

## FORM-038 — Campos numéricos guardam o zero à esquerda: "0" + "5" vira "05"

**Categoria:** Formulário / Bug · **Prioridade:** P1 · **Severidade:** Alta
**Telas:** Novo cartão, Novo financiamento, Recorrência, Nova despesa (itens), Onboarding
**Origem:** relatado pelo dono em 2026-09-04 · **Reproduzido:** 5 campos, 3 telas

### Problema

Um campo que mostra `0`; a pessoa digita `5`; o campo passa a mostrar **`05`** e fica
assim. Parece campo de texto, não de número. O mesmo vale para um zero digitado na frente
de um valor existente: `7` vira **`07`** e permanece.

### Como reproduzir

1. Abrir Cartões → **Novo cartão**.
2. No campo "Dia de fechamento", selecionar tudo e digitar `0`.
3. Digitar `5` em seguida.
4. O campo mostra `05`.

### Medição (reprodução automatizada, 1366×768)

```
##### NOVO CARTÃO
  >>> Dia de fechamento     "0" + "5"            -> "05"    ZERO PERSISTE
  >>> Dia de vencimento     "7" com 0 na frente  -> "07"    PERSISTE
##### NOVO FINANCIAMENTO
  >>> Nº de parcelas        "0" + "5"            -> "05"    ZERO PERSISTE
##### RECORRÊNCIA
  >>> Dia do mês            "0" + "5"            -> "05"    ZERO PERSISTE
##### NOVA DESPESA -> item
  >>> Qtd                   "0" + "5"            -> "05"    ZERO PERSISTE
##### ADMIN -> Configurações (7 campos)
  ok  cfg-expira, cfg-cota, cfg-quota, cfg-upload, cfg-linhas, cfg-rl-ip, cfg-rl-conta -> "5"
```

**O dado que chega no servidor está certo** — conferido interceptando a requisição com a
tela mostrando `05`:

```
"Dia de fechamento" na TELA: "05"
enviado: POST /me/credit-cards/ {"name":"…","limit":1000,"closing_day":5,"due_day":10,…}
```

### Impacto

Não corrompe dado — corrói **confiança**, que num app de dinheiro é o produto. O campo
parece quebrado, e a pessoa não tem como saber se o que será salvo é `05`, `5` ou `50`.
Ela apaga e redigita, e continua acontecendo. Está nos caminhos de cadastro mais usados:
criar cartão, criar financiamento, montar recorrência, dividir despesa por item.

### Causa provável (identificada, e a correção já existe no próprio repositório)

Duas mecânicas diferentes com o mesmo sintoma:

**1) Campos controlados com `value={numero}` (4 dos 5 casos).** O React, para
`<input type="number">`, decide se reescreve o DOM com uma comparação **frouxa**:

```js
if (node.value != value) node.value = toString(value);   // != , não !==
```

Com `node.value === "05"` e `value === 5`, `"05" == 5` é **verdadeiro** em JavaScript —
então a condição é falsa e o React **não** reescreve o campo. O estado vira 5, a tela
continua com `05`, e nada mais acontece porque o número não muda mais.

**A prova de que é isso** está na própria base: os 7 campos numéricos da Administração são
os únicos que **não** têm o defeito, e são os únicos que passam `value={String(...)}`
(`AdminPage.tsx:638`). Com string, a comparação é entre `"05"` e `"5"` — diferentes — e o
React reescreve.

**2) Campos do react-hook-form com `register(..., { valueAsNumber: true })` (o "Qtd").**
Aqui o input é **não controlado**: o RHF lê o valor, converte para número e nunca reescreve
o DOM. O zero fica na tela por construção.

### Variante irmã (mesma raiz, sintoma oposto) — confirmada

Nos campos cujo `onChange` tem um fallback, digitar `0` faz o valor **saltar** sem aviso:

| Campo | Código | O que acontece ao digitar `0` |
|---|---|---|
| Onboarding → "Fechamento" | `parseInt(e.target.value) \|\| 5` | vira **5** |
| Recorrência → "A cada" | `Math.max(1, Number(…) \|\| 1)` | vira **1** |
| Recorrência → "Nº de ocorrências" | `Math.max(1, Number(…) \|\| 1)` | vira **1** |

Efeito colateral: **não dá para esvaziar esses campos** para redigitar, e não dá para
digitar um número que comece por 0 (ex.: apagar tudo e teclar `0` e depois `1` para chegar
a 1 — o campo já saltou).

### Solução recomendada

Um componente só, do jeito que o `MoneyInput` já resolveu para dinheiro — a base tem o
padrão certo, só não o generalizou para inteiros:

1. Criar `components/ui/NumberInput.tsx` guardando o texto digitado em estado local
   (como o `MoneyInput` faz com `displayValue`), normalizando **no `blur`** e emitindo
   número pelo `onChange`. Assim o zero à esquerda some quando a pessoa sai do campo, e
   não enquanto ela digita.
2. Enquanto isso não existir, a correção de uma linha por campo é `value={String(x)}` —
   exatamente o que a Administração já faz.
3. Trocar os fallbacks `|| 5` / `|| 1` por: aceitar campo vazio durante a digitação e
   aplicar o mínimo **no `blur`**.
4. Nos campos do RHF, usar `Controller` com o mesmo `NumberInput`.

### Arquivos envolvidos

- `frontend/src/components/credit-cards/CreditCardList.tsx:267,279`
- `frontend/src/components/financing/AmortizationTable.tsx:245`
- `frontend/src/components/recurrence/RecurrenceEditor.tsx:72,126,189`
- `frontend/src/components/layout/OnboardingModal.tsx:184`
- `frontend/src/components/dashboard/transaction-form/ItemsEditor.tsx:172,313`
- `frontend/src/components/dashboard/transaction-form/SplitEditor.tsx:98`
- `frontend/src/pages/Admin/AdminPage.tsx` — **referência do jeito certo, não mexer**

### Como validar

Um teste de componente para cada campo: escrever `0`, teclar `5`, e afirmar que o valor
**exibido** é `"5"`. Deve falhar hoje em 5 campos e passar nos 7 da Administração — é o
controle que prova que o teste mede o que diz medir.

### Esforço

**Baixo** (correção de uma linha por campo) · **Médio** (o `NumberInput`, que é a
correção que não volta atrás).

---

## UI-011 — 46 cores fora do design system, com 3 falhas de contraste medidas

**Categoria:** UI / Consistência / Acessibilidade · **Prioridade:** P2 · **Severidade:** Média
**Rotas:** `/me/income`, `/me/financing`, `/w/:id/recurring` (medidas) + 14 arquivos

### Problema

O design system define `--income`, `--expense`, `--success`, `--warning` com luminosidade
escolhida **exatamente** para passar em 4,5:1 (há comentário no `index.css` explicando a
conta). Ainda assim, `emerald-*`, `amber-*` e `slate-*` crus aparecem **46 vezes em
17 arquivos**, e o axe reprova três deles:

| Rota | Elemento | Contraste | Mínimo |
|---|---|---:|---:|
| `/me/financing` | `.text-emerald-500` (20px, bold) | **2,47:1** | 3,0:1 |
| `/me/income` | pílula `RECORRENTE` (10px) | **2,24:1** | 4,5:1 |
| `/w/:id/recurring` | 8 pílulas iguais | **2,24:1** | 4,5:1 |
| `/me/income` | `.opacity-60` sobre verde | **2,75:1** | 4,5:1 |

Além do contraste, há o efeito visual: `--income` (oklch 0.47) e `emerald-500` (#00bc7d)
são **dois verdes diferentes** convivendo na mesma tela. O toast de sucesso, o "Salvo!" das
Configurações, o CTA do onboarding e a barra de orçamento usam o verde que **não** é o do
sistema.

### Casos que merecem atenção especial

- `components/ui/progress.tsx:13` — `bg-slate-900/50` como trilho: cor fixa que ignora os
  dois temas.
- `components/layout/OnboardingModal.tsx:200` — o CTA da **primeira tela do usuário novo**
  é `bg-emerald-600`, enquanto todo o resto do app usa a marca índigo.
- `components/ui/toaster.tsx:8,11` — `border-l-emerald-500` e `border-l-amber-500` na
  faixa do toast, ao lado de um ícone que usa `text-warning` (do sistema). O mesmo
  componente mistura as duas fontes.

### Solução recomendada

Substituir por token (`text-income`, `bg-income-subtle`, `border-income`, `bg-warning`,
`bg-muted` no trilho do progress) e acrescentar uma regra de ESLint/`grep` no gate de lint
proibindo `emerald-|amber-[0-9]|slate-[0-9]|rose-[0-9]` em `src/**/*.tsx` — sem o gate isso
volta.

### Esforço

**Médio** (46 pontos, mas mecânico) · **Baixo** para o gate.

---

## FDB-012 — O Extrato mostra "R$ 0,00" com ar de número certo enquanto carrega

**Categoria:** Feedback / Loading · **Prioridade:** P2 · **Severidade:** Média
**Rota:** `/me/ledger`

### Problema

Com a API lenta (simulei 3s), a faixa de KPIs exibe **"Entrou R$ 0,00 · Saiu R$ 0,00 ·
Saldo do mês R$ 0,00"** — em verde e vermelho, com a mesma tipografia do valor final —
enquanto a lista abaixo mostra skeletons. Não há como distinguir "ainda não sei" de "é
zero".

### Evidência

`E07-extrato-zeros-durante-carregamento.png`

### Impacto

Num app de dinheiro, um zero apresentado com confiança é pior do que um vazio. O projeto
já registrou esse mesmo defeito uma vez (o comentário do catálogo em
`e2e-shots/screenshots.spec.ts:92` conta a história) — ele voltou noutra tela.

### Solução recomendada

Skeleton nos três KPIs enquanto `isLoading` (é o que a `OverviewPage` faz), e `ErrorState`
quando `isError`.

### Esforço

**Baixo**.

---

## FDB-013 — As rotas de espaço carregam sem título e sem contexto

**Categoria:** Feedback / Consistência · **Prioridade:** P2 · **Severidade:** Média
**Rotas:** `/w/:id/*`

### Problema

Enquanto o `WorkspaceGuard` resolve, a área de conteúdo é **um retângulo cinza sem nada**:
sem título de página, sem cabeçalho, sem indicação do que está carregando. O seletor de
escopo mostra o texto genérico "Espaço". Em `/overview` o comportamento é o oposto (título
e período aparecem na hora, com skeleton só nos números).

### Evidência

`E09-carregamento-sem-contexto.png` (`/w/1/transactions` a 3s de latência)

### Solução recomendada

Renderizar `PageHeader` (título + escopo) fora do gate do `WorkspaceGuard`, deixando o
skeleton só para o conteúdo — o mesmo padrão de `/overview`.

### Esforço

**Baixo/Médio**.

---

## FDB-014 — O bloco de saldo do "Seu mês" some em silêncio quando a API falha

**Categoria:** Feedback / Erro · **Prioridade:** P2 · **Severidade:** Média
**Rota:** `/overview`

### Problema

Com `GET /me/balance` respondendo 500, os blocos **"Seu dinheiro"** e **"Até o fim do mês"**
simplesmente **desaparecem** da página. Não há erro, aviso ou botão de tentar de novo — a
tela parece uma versão do produto que não tem saldo.

### Como reproduzir

Interceptar `/api/v1/me/balance` com 500 e abrir `/overview`. O resto da tela renderiza
normalmente.

### Impacto

Viola a regra ERR-001 que o próprio arquivo cita: *"'Renda R$ 0,00' é uma resposta, não um
erro — e o usuário não teria como saber que ela não foi calculada"*. Aqui é pior: nem o
zero aparece.

### Causa provável

`frontend/src/components/dashboard/SaldoEProjecao.tsx` — sem ramo `isError`.

### Solução recomendada

`ErrorState` com "Tentar novamente" dentro do bloco, como a `OverviewPage` faz para o
`/me/overview`.

### Esforço

**Baixo**.

---

## UX-015 — Escape descarta o formulário de despesa preenchido, sem perguntar

**Categoria:** UX / Formulário · **Prioridade:** P2 · **Severidade:** Média
**Tela:** Nova Despesa

### Problema

Com título, valor, pagadores, divisão por item e anexos preenchidos, um **Escape** (ou um
clique fora) fecha o diálogo e **descarta tudo**. Ao reabrir, o formulário está vazio —
verificado: campo título volta como `""`.

### Impacto

O formulário mais longo do app (título, valor, moeda, pagadores, data, forma de pagamento,
tags, divisão, itens, anexos) é o mais fácil de perder por acidente. É o cenário clássico
do "usuário desatento" — e o gesto de fechar é o mesmo que se usa cem vezes por dia em
diálogos triviais.

### Solução recomendada

Se o formulário está *dirty*, `onEscapeKeyDown`/`onPointerDownOutside` pedem confirmação
("Descartar esta despesa?"). O `useConfirm` já existe e já é usado para o mesmo tipo de
decisão. Alternativa complementar (menor esforço, menos garantia): manter o rascunho em
memória e reabrir com o que foi digitado.

### Esforço

**Baixo**.

---

## A11Y-016 — Linha do extrato é `role="button"` com botões focáveis dentro

**Categoria:** Acessibilidade · **Prioridade:** P2 · **Severidade:** Média (axe: *serious*, 15 nós)
**Rota:** `/w/:id/transactions`, `/w/:id`

### Problema

Cada linha é `<div role="button" tabIndex={0}>` contendo os botões de editar e excluir.
Controles interativos aninhados quebram a semântica: o leitor de tela anuncia a linha como
um único botão chamado *"Faxina Pendente A pagar — −R$ 220,00"*, e o que há dentro fica
ambíguo.

### Solução recomendada

Um dos dois padrões:
- **Stretched link**: a linha vira `<div>` comum; o título vira `<button>`/`<a>` que cobre
  a área com `after:inset-0`, e os botões de ação ficam acima no z-index. (É o padrão que
  a própria `OverviewPage` usa no `<dl>` do Caixa — inclusive com o comentário explicando.)
- Ou: linha não focável, com as ações sendo os únicos alvos de teclado.

### Esforço

**Médio**.

---

## A11Y-017 — Ao fechar o diálogo global, o foco volta para o `body`

**Categoria:** Acessibilidade · **Prioridade:** P2 · **Severidade:** Média
**Tela:** Nova Despesa, detalhe do lançamento

### Problema

Depois do Escape, `document.activeElement` é o `body` — o usuário de teclado volta ao
começo do documento e precisa refazer todo o caminho de Tabs (ver A11Y-010, que agrava).

### Causa provável

O diálogo é global (aberto por store, a partir do FAB, do botão da página ou de uma linha),
então não há `DialogTrigger` para o Radix devolver o foco.

### Solução recomendada

Guardar `document.activeElement` no store ao abrir e restaurar no `onCloseAutoFocus`.

### Esforço

**Baixo**.

---

## A11Y-018 — Barra lateral sem `aria-current`; os dois `nav` sem rótulo

**Categoria:** Acessibilidade · **Prioridade:** P2 · **Severidade:** Média
**Rota:** todas

### Problema

O item ativo da barra lateral é marcado **só visualmente** (`bg-brand-subtle` + barrinha
decorativa). Medido: `aria-current` existe **uma vez** na página, e é da barra inferior
(mobile) — o link ativo da sidebar tem `aria-current: null`. Além disso, os dois `<nav>`
não têm `aria-label`, então um leitor de tela lista "navegação" duas vezes.

### Solução recomendada

`aria-current="page"` no `Link` ativo (`Sidebar.tsx:107`) e `aria-label` em cada `nav`
("Navegação principal" / "Navegação rápida").

### Esforço

**Baixo**.

---

## NAV-019 — URL inválida e espaço inexistente redirecionam em silêncio

**Categoria:** Navegação · **Prioridade:** P2 · **Severidade:** Média
**Rotas:** `*`, `/w/:id` inexistente

### Problema

`/rota-que-nao-existe` → `/overview`, **sem mensagem**.
`/w/99999` (espaço que não existe ou do qual não sou membro) → `/overview`, **sem mensagem**.

### Impacto

Quem clica num link antigo, num favorito de um espaço do qual saiu, ou num link
compartilhado por engano, aterrissa no "Seu mês" sem entender por quê. A dúvida que fica é
"o link estava errado ou eu perdi o acesso?" — e essas duas coisas exigem ações diferentes.

### Solução recomendada

- `*` → página 404 simples ("Esta página não existe") com link para o Início. Custa pouco e
  responde à pergunta.
- `/w/:id` inválido → redirecionar com um toast informativo ("Você não tem acesso a este
  espaço" / "Espaço não encontrado"). O `WorkspaceGuard` já sabe distinguir os casos.

### Esforço

**Baixo**.

---

## NAV-020 — Busca e filtros não vão para a URL e se perdem no F5

**Categoria:** Navegação / Eficiência · **Prioridade:** P2 · **Severidade:** Média
**Rota:** `/w/:id/transactions` (e demais telas com filtro)

### Problema

O **mês** está na URL (`?month=2026-07`) e sobrevive a recarga, link e botão Voltar. A
**busca** e os **quatro filtros** não: digitar "Café", recarregar, e o campo volta vazio
com a lista completa. Também não dá para mandar a alguém "olha esses lançamentos".

### Como reproduzir

1. `/w/1/transactions`, digitar "Café" na busca. URL segue `/w/1/transactions`.
2. F5. Campo de busca: `""`.

### Solução recomendada

Levar `search`, `payment_method`, `category_id`, `tag_id` e `settled` para a query string
com `useSearchParams` (o `useMonthParam`/`useTabParam` já são o padrão da casa), com
`replace: true` na digitação para não poluir o histórico.

### Esforço

**Médio**.

---

## NAV-021 — Três comportamentos diferentes de aba no mesmo produto

**Categoria:** Consistência / Navegação · **Prioridade:** P2 · **Severidade:** Média

### Problema

| Tela | Componente | Aba na URL | Sobrevive ao F5 |
|---|---|:--:|:--:|
| Acertos (`/w/:id/debts`) | `Tabs` + `useTabParam` | ✅ `?tab=historico` | ✅ |
| Seus acertos (`/me/settlements`) | `Tabs` + `useTabParam` | ✅ | ✅ |
| Relatórios (`/w/:id/reports`) | `Tabs` | ❌ | ❌ |
| Administração (`/admin`) | `Tabs` | ❌ | ❌ |
| Suas configurações (`/me/settings`) | rail de botões próprio | ❌ | ❌ |
| Configurações do espaço | rail de botões próprio | ❌ | ❌ |

Medido clicando a aba, lendo a URL e recarregando.

### Impacto

Além da inconsistência, dois efeitos concretos: não dá para mandar link de "Administração →
Convites" nem de "Configurações → Segurança"; e o botão **Voltar** do navegador, depois de
navegar por quatro abas da Administração, sai da página em vez de voltar uma aba.

### Solução recomendada

`useTabParam` em todas as telas com aba, e as duas telas de Configurações passam a usar o
`Tabs` do design system (com o rail lateral como variante visual, não como componente
paralelo).

### Esforço

**Médio**.

---

## UI-022 — O Painel do espaço tem 700×216px vazios em 1366×768

**Categoria:** UI / Densidade · **Prioridade:** P2 · **Severidade:** Média
**Rota:** `/w/:id` · **Resolução:** 1366×768

### Problema

Grade de duas colunas: à esquerda o cartão-herói ("Sua parte no mês"), com **170px** de
altura; à direita três cartões que somam **362px**. A coluna esquerda não estica nem
recebe mais nada, deixando um vazio de **700×216px** — a maior área ociosa do produto.

### Medição (DOM, 1366×768)

```
herói           x=272  y=172  700×170   → termina em y=342
Gasto do espaço x=996  y=172  338×110
Adiantado       x=996  y=298  338×110
Você tem a receber x=996 y=424 338×110  → termina em y=534
Últimos lançamentos x=272 y=558 1062×556
```

Vazio: `y 342→558` × 700px. E **só 2 linhas de lançamento** cabem acima da dobra.

### Evidência

`E06-painel-1366-espaco-vazio.png`

### Solução recomendada

Duas opções, ambas baratas:
- subir "Últimos lançamentos" para dentro da coluna esquerda (o herói vira o topo dela); ou
- transformar os quatro números numa faixa de 4 KPIs (padrão que `/overview` e
  `/w/:id/reports` já usam) e dar a largura toda para a lista.

A segunda também resolve a redundância: hoje "Sua parte no mês −R$ 2.173,11" e "Você gastou
R$ 2.173,11 este mês" são o **mesmo número duas vezes no mesmo cartão**, e "Sua parte:
R$ 2.173,11" repete de novo no cartão ao lado.

### Esforço

**Baixo/Médio**.

---

## CONT-023 — "Workspace" vaza em 3 rótulos e o Title Case é inconsistente

**Categoria:** Conteúdo / Consistência · **Prioridade:** P2 · **Severidade:** Média

### Problema

O projeto decidiu, por escrito (`nav-items.ts:32-42`), que a palavra da interface é
**espaço** — e o jargão sobrou em três lugares, dois deles com a incoerência dentro da
própria ação:

| Onde | Rótulo do botão | Título da confirmação |
|---|---|---|
| `SettingsPage.tsx:272` | "+ Criar Novo Workspace" | (seção acima chama-se "Espaços") |
| `SettingsPage.tsx:935` | "Excluir workspace" | **"Excluir espaço"** |
| `SettingsPage.tsx:917` | "Sair do workspace" | **"Sair do espaço"** |

Capitalização: convivem "Nova despesa" e "Nova Despesa"; "Novo cartão", "Nova conta" e
"+ Novo Financiamento"; "Salvar Alterações", "Informações do Perfil", "Sair da Conta",
"Concluir Tutorial", "Começar Setup", "Próximo Passo".

E dois anglicismos na **primeira tela do usuário novo**: "Setup" e "Tutorial" — sendo que
o passo não é um tutorial, é o cadastro de renda e cartão.

### Solução recomendada

Trocar os três rótulos; padronizar em **sentence case** (a regra que o resto da interface
já segue); trocar "Começar Setup" → "Começar" e "Concluir Tutorial" → "Concluir".
Um `grep` no gate de lint contra `Workspace` em string de UI evita a volta.

### Esforço

**Baixo**.

---

## MOB-024 — Alvos de toque de 28px (e um de 16px) nas ações secundárias

**Categoria:** Mobile / Acessibilidade · **Prioridade:** P2 · **Severidade:** Média
**Resolução:** 390×844, 360×800

### Problema

O extrato já teve os botões de editar/excluir corrigidos para 40×40 no celular — a regra
existe e está comentada no código. Mas as ações secundárias ficaram para trás:

| Tela | Alvo | Tamanho |
|---|---|---|
| `/me/accounts` | "Extrato", "Saldo inicial", "Ajustar" (×5 contas) | **61×28**, **87×28**, **60×28** |
| `/me/settlements`, `/w/:id/debts` | abas "Resumo/Por mês/Histórico" | **75×28** |
| `/me/settlements` | "Recebi" (×3) | **82×28** |
| `/me/settlements` | link "Abrir a casa" | **80×16** |
| barra superior | os dois sinos | **36×36** |

### Impacto

Em `/me/accounts` são três botões de 28px de altura por conta, empilhados — o erro de toque
manda para a tela errada. O link de 16px é o pior caso.

### Solução recomendada

Piso de 44px de altura (ou `py` maior + `touch-action`) para botão e aba em `< sm`,
como já foi feito no `TransactionItem`. É a mesma correção, generalizada.

### Esforço

**Baixo**.

---

## UI-025 — O gráfico "Gasto da casa × sua parte" não tem legenda

**Categoria:** UI / Dados · **Prioridade:** P2 · **Severidade:** Média
**Rota:** `/w/:id/reports` → Visão geral

### Problema

Duas séries de barras (índigo e âmbar) sem legenda. O título nomeia as duas grandezas mas
não diz qual cor é qual; só o tooltip (hover) responde — e no celular não há hover.

### Solução recomendada

`<Legend />` do recharts, ou rótulos diretos nas séries. Cores devem vir de `--chart-1`/
`--chart-3` (já vêm).

### Esforço

**Baixo**.

---

## UX-026 — O onboarding trava o botão sem dizer por quê e usa cor fora da marca

**Categoria:** UX / UI / Conteúdo · **Prioridade:** P2 · **Severidade:** Média
**Tela:** modal de onboarding, passo 3

### Problema

1. Preencher "Nome do Cartão" **sem** o limite deixa "Concluir Tutorial" **desabilitado**
   (verificado). O motivo (`!!cardName && !cardLimit`) não é dito em lugar nenhum: não há
   erro no campo, nem `aria-describedby`, nem asterisco de obrigatório. O usuário fica
   olhando um botão apagado.
2. Esse mesmo botão é `bg-emerald-600` — a única ação primária verde do app inteiro, e é a
   **primeira** que o usuário novo vê.
3. O passo 1 não oferece nenhuma saída ("Começar Setup" é a única opção; o Escape está
   bloqueado de propósito). Só nos passos 2 e 3 aparece "Pular".
4. "Fechamento" é `type="number"` com `parseInt(...) || 5`: apagar o campo faz o valor
   saltar para 5 sozinho.

### Solução recomendada

Marcar "Limite" como obrigatório quando há nome, com mensagem inline; usar a cor primária;
oferecer "Configurar depois" já no passo 1; e permitir campo vazio no dia de fechamento.

### Esforço

**Baixo**.

---

## UI-027 — Dois sinos praticamente idênticos na barra superior

**Categoria:** UI / Conteúdo · **Prioridade:** P2 · **Severidade:** Média
**Rota:** todas

### Problema

O canto superior direito tem dois botões de 36×36 com ícone de **sino**, lado a lado:
"Notificações bloqueadas" (ou "Ativar avisos de vencimento") e "Notificações". A diferença
entre os desenhos é um risco de "sino cortado". Não há rótulo nem separação visual.

### Solução recomendada

Trocar o ícone do botão de ativar (`BellPlus`/`BellRing` × `Bell`), ou fundi-lo ao próprio
painel de notificações como primeira linha ("Ativar avisos de vencimento"), que é onde a
pessoa vai procurar.

### Esforço

**Baixo**.

---

## MOB-028 — Relatórios empilha 4 KPIs em 1 coluna no celular; Seu mês usa 2

**Categoria:** Mobile / Consistência · **Prioridade:** P2 · **Severidade:** Média

### Problema

`/overview` usa `grid-cols-2` no celular; `/w/:id/reports` usa 1 coluna. São ~440px de
KPI antes de qualquer conteúdo — quase uma tela inteira de rolagem antes das abas.

### Solução recomendada

`grid-cols-2` também nos Relatórios (e conferir Compromissos e Contas a pagar, que têm três
KPIs num grid de 2 e deixam um órfão).

### Esforço

**Baixo**.

---

## UI-029 — Quase toda linha do extrato exibe um "—" solitário

**Categoria:** UI · **Prioridade:** P3 · **Severidade:** Baixa
**Rota:** `/w/:id/transactions`, `/w/:id`

### Problema

A linha de meta abaixo do título mostra `categoria · forma de pagamento · parcela`. Sem
categoria e sem forma de pagamento, sobra um `—` sozinho — em 8 das 9 linhas visíveis nas
capturas. Vira ruído repetido na tela mais densa.

### Solução recomendada

Não renderizar a linha de meta quando o resultado é só o travessão.

### Esforço

**Baixo**.

---

## UI-030 — `/w/:id/reports` estoura 5px em 768px

**Categoria:** Responsividade · **Prioridade:** P3 · **Severidade:** Baixa

### Problema

`scrollWidth 773 > clientWidth 768` — única rolagem horizontal encontrada em 24 rotas ×
10 larguras. Não achei o elemento culpado pela medição (provavelmente o SVG do recharts,
que costuma ultrapassar o contêiner por alguns pixels). Na mesma largura, "Sem categoria"
é truncado a 70px.

### Solução recomendada

`overflow-x-hidden` no contêiner do gráfico + `min-w-0` no cartão do KPI; conferir com o
gate estendido de MOB-001.

### Esforço

**Baixo**.

---

## UX-031 — A faixa "Notificações bloqueadas" não pode ser dispensada

**Categoria:** UX · **Prioridade:** P3 · **Severidade:** Baixa
**Rota:** `/me/payables`

### Problema

Para quem bloqueou notificações no navegador, a faixa ocupa o topo de Contas a pagar
**permanentemente**, empurrando os KPIs para baixo. O modal de convite tem adiamento de
uma semana (bem feito); a faixa não tem nada.

### Solução recomendada

Botão de dispensar reaproveitando o mesmo `adiar()` do convite.

### Esforço

**Baixo**.

---

## UX-032 — Importar exige conhecer `%d/%m/%Y` e digitar o nome das colunas de cabeça

**Categoria:** UX · **Prioridade:** P3 · **Severidade:** Baixa (alta para quem tenta usar)
**Rota:** `/w/:id/import`

### Problema

Antes de o arquivo ser lido, o usuário precisa preencher: delimitador, separador decimal,
formato de data em **códigos strftime** e os **nomes exatos** das três colunas do CSV. O
seletor de arquivo é o controle nativo do navegador, sem estilo e em inglês
("Choose File / No file chosen").

O roadmap já registra isto como diferido conscientemente (F4.7) — mantenho o achado porque
ele mudou de peso: com A11Y-009 (sem rótulo) a tela é hoje a menos acessível do produto.

### Solução recomendada (incremental, sem o wizard completo)

1. Ler o cabeçalho do CSV **ao escolher o arquivo** e transformar as três "Coluna X" em
   `select` com as colunas encontradas.
2. Inferir delimitador e formato de data por amostragem, deixando os campos como ajuste.
3. Botão de arquivo estilizado com o `Button` do sistema.

### Esforço

**Médio**.

---

## UI-033 — Estados vazios de tabela sem o componente `EmptyState`

**Categoria:** Consistência · **Prioridade:** P3 · **Severidade:** Baixa
**Rotas:** `/me/income`, `/w/:id/recurring`

### Problema

Enquanto 15 telas usam o `EmptyState` (ícone + título + descrição + CTA), estas duas
mostram o **cabeçalho da tabela vazio** com uma frase solta na linha
("Nenhuma renda registrada neste mês.", "Nenhuma despesa recorrente cadastrada.").

### Solução recomendada

Usar `EmptyState` com a ação correspondente ("Nova renda" / "Nova despesa recorrente").

### Esforço

**Baixo**.

---

## PERF-034 — 11 endpoints na abertura do "Seu mês", incluindo dados do espaço que a tela não usa

**Categoria:** Performance · **Prioridade:** P3 · **Severidade:** Baixa

### Problema

Abrir `/overview` (tela **pessoal**) dispara, além do esperado:
`/workspaces/1/transactions/`, `/workspaces/1/categories`, `/workspaces/1/members`,
`/workspaces/1/invites`. Nada disso aparece na tela.

> Nota de método: o log mostra cada chamada **duas vezes**; isso é o `StrictMode` do React
> em desenvolvimento (`main.tsx`), **não** um defeito. A contagem acima é de endpoints
> distintos.

### Impacto

Nada perceptível em rede local. Em 3G, são 4 requisições concorrendo com as que importam.

### Solução recomendada

Carregar membros/categorias/convites sob demanda (na tela que os usa) em vez de no shell.

### Esforço

**Médio**.

---

## UX-035 — Excluir um espaço inteiro é protegido apenas por um "Excluir" genérico

**Categoria:** UX / Ação destrutiva · **Prioridade:** P3 · **Severidade:** Baixa

### Problema

A ação mais destrutiva do produto (apaga o histórico financeiro compartilhado de todos os
membros) tem a **mesma** proteção de apagar um café de R$ 12,50: um diálogo de sim/não.
A confirmação nomeia o espaço — o que já é bom — mas não exige nenhum gesto deliberado.

### Solução recomendada

Exigir digitar o nome do espaço para habilitar o botão (padrão consagrado), e dizer o que
será perdido ("48 lançamentos, 3 membros, 12 meses de histórico").

### Esforço

**Baixo**.

---

## UI-036 — Rótulos em caixa alta convivem com o padrão do `StatTile`

**Categoria:** Consistência · **Prioridade:** P3 · **Severidade:** Baixa

### Problema

Números apresentados com rótulo `UPPERCASE` ("SUA PARTE", "VOCÊ PAGOU", "SALDO DEVEDOR",
"PRÓXIMA PARCELA", "QUEM PAGOU", "CONVITES PENDENTES") convivem com o `StatTile`, que usa
sentence case. O estudo de redesign lista `UPPERCASE` como um dos vícios que ele veio
remover.

### Solução recomendada

Padronizar em sentence case e, onde o bloco cumpre o papel de KPI, usar o `StatTile`.

### Esforço

**Baixo**.

---

# 6. Análise por resolução

## 6.1 — 1920×1080 (desktop grande)

**A melhor experiência do produto.** Tudo respira, a barra lateral inteira cabe (exceto
"Administração", ver abaixo), os KPIs ficam em 4 colunas e o modal de despesa é o **único**
caso em que "Salvar" aparece sem rolar.

Achados exclusivos ou agravados nesta resolução:

- **NAV-005 parcial** — `/admin` ainda tem o item ativo em y=1066, fora da janela de 1080.
- **UI-022** — o vazio do Painel existe aqui também (a grade é a mesma), mas incomoda menos
  porque a lista aparece na sequência.
- Nenhuma rolagem horizontal, nenhum truncamento, nenhum erro de console em 24 rotas.

## 6.2 — 1366×768 (o caso mais importante)

É aqui que a **altura** cobra. Com 768px de janela:

| Tela | O que fica acima da dobra | O que fica escondido |
|---|---|---|
| Seu mês | título, "Seu dinheiro" (5 contas), "Até o fim do mês" | Resultado do mês, Caixa do mês, Por espaço, Atividade |
| Painel do espaço | herói + 3 KPIs + **2 linhas** de lançamento | o resto da lista |
| Lançamentos | filtros + ~5 linhas | resto |
| Nova Despesa (modal) | até "Dividir com" | **o botão Salvar** |
| Configurações do espaço | Espaço + início de Membros | Convites, Zona de Perigo |
| Barra lateral | 12 itens pessoais + o cabeçalho "COMPARTILHADO" | **os 8 itens do espaço + Administração** |

Achados desta faixa: **UX-004** (Salvar fora da tela), **NAV-005** (navegação e item ativo
abaixo da dobra), **UI-022** (vazio de 700×216), e o cartão de cadastro cuja mensagem de
erro de senha cruza o divisor interno.

**Não há rolagem horizontal nem truncamento de valores** nesta largura — o defeito da
auditoria anterior (F3, valores cortados) está corrigido.

## 6.3 — 768×1024 até ~1100 (tablet e janela dividida)

A faixa mais frágil, e a que **nenhum teste cobre** — exatamente o padrão que o projeto já
documentou uma vez.

- **RESP-002** — membros a 0px.
- **RESP-003** — e-mail do convite a ~20px.
- `/me/accounts` — nome da conta a **170px** ("Conta Corrente Itaú Personnalité — Agên…").
- `/me/commitments` — títulos a 299–342px, 13 nós truncados.
- `/me/settings` — nome e e-mail do perfil a 64px.
- **UI-030** — Relatórios estoura 5px em 768.
- Em 900px a mesma lista de membros ainda está a 0px; a partir de ~1100px normaliza.

## 6.4 — 390×844 (iPhone 12/13/14)

- **MOB-001** — 14 de 15 títulos a 0px. *O achado que define esta resolução.*
- **UX-004** — "Salvar Despesa" 322px abaixo da janela.
- **MOB-024** — abas e ações secundárias de 28px.
- `/me/payables` com **7.095px** de altura (≈8 telas) sem paginação.
- `/me/commitments` — 13 títulos truncados a 193–236px.
- `/me/accounts` — nome a 302px.
- Positivo: zero rolagem horizontal; barra inferior, FAB, gaveta "Mais" e filtros em gaveta
  funcionam bem; tabelas viradas em cartões.

## 6.5 — 360×800 (Galaxy A / Moto G)

Igual a 390 em natureza, pior em grau:

- **MOB-001** — 14 de 15 títulos a 0px, o maior com **61px**.
- `/me/payables` com **7.283px**.
- `/w/:id/settings` com 2.253px.
- Zero rolagem horizontal — o gate de 360px cumpre o que promete.

## 6.6 — Extras testados

- **412×915** (Pixel): MOB-001 aparece em 2 de 15 linhas — é aqui que o defeito começa.
- **320×800**: nenhuma rolagem horizontal (bom sinal para zoom a 400%); `/me/payables`
  chega a **7.951px**; 1 título do Painel também zera.
- **430×932** (iPhone Pro Max): sem títulos zerados, mas o menor tem **12px**.

---

# 7. Análise mobile específica

O app **não** é um desktop encolhido — isso está claro e é mérito do projeto: barra
inferior com 4 slots + gaveta "Mais", FAB de nova despesa, filtros em gaveta com contador,
tabelas convertidas em cartões, `min-h-dvh`, `env(safe-area-inset-bottom)`, `inputMode`
correto nos campos de dinheiro. O trabalho de mobile foi feito.

O que ainda pede decisão **estrutural** (não só CSS):

> **Área do sistema (revisão de 2026-09-04).** O rodapé foi protegido com `pb-safe` e um
> comentário explicando por quê; o **topo não tem nada equivalente**, e a `theme-color`
> clara (`#fcfbf9`) não garante contraste com os ícones brancos do sistema. Ver PWA-037 —
> é a diferença entre "responsivo" e "cabe num aparelho de verdade", e foi o ponto cego
> desta auditoria por eu ter medido viewports em vez de aparelhos.

| Situação hoje | O que seria melhor no celular |
|---|---|
| Linha do extrato com título, 2 pílulas, valor e 2 botões na **mesma linha** | Duas linhas: título em cima (largura toda); meta + pílulas embaixo; ações por deslize ou menu "…" — resolve MOB-001 na raiz |
| Barra superior do app colada em `top:0`, sem reservar a área do sistema | `pt-safe` na barra e uma `theme-color` que garanta ícones legíveis nos dois temas |
| Campos de dia/quantidade como `type="number"` cru | Um `NumberInput` do sistema, como o `MoneyInput` já é para dinheiro — o teclado numérico já está certo; falta a normalização |
| `/me/payables` com 7.283px e todas as contas | Agrupar por seção recolhível (Vencidas / Hoje / Este mês / Depois), com as vencidas abertas |
| Seletor de financiamento como 6 chips (330px de altura) | `<select>` nativo ou carrossel horizontal |
| 4 KPIs em 1 coluna nos Relatórios (440px) | 2 colunas, como no Seu mês |
| Ações secundárias de 28px | Piso de 44px |
| "Salvar Despesa" a 322px abaixo da janela | Rodapé fixo na folha, com o botão sempre visível |
| Três botões por conta em `/me/accounts` | Um menu "…" por conta, ou uma ação primária + menu |
| Abas de 28px | 44px, e manter a rolagem lateral que já existe |

---

# 8. Quick wins (baixo esforço, baixo risco, efeito visível)

| # | O quê | Achado | Esforço |
|---|---|---|---|
| 1 | Skip link no `AppShell` | A11Y-010 | 15 min |
| 2 | `aria-current="page"` + `aria-label` nos `nav` | A11Y-018 | 15 min |
| 3 | `aria-label` nos 4 `SelectTrigger` de filtro | A11Y-008 | 20 min |
| 4 | `id`/`htmlFor` nos 7 campos do Importar | A11Y-009 | 20 min |
| 5 | `scrollIntoView` do item ativo da barra lateral | NAV-005 (parte) | 20 min |
| 6 | Skeleton nos 3 KPIs do Extrato | FDB-012 | 20 min |
| 7 | `ErrorState` no `SaldoEProjecao` | FDB-014 | 20 min |
| 8 | Trocar os 3 rótulos "workspace" → "espaço" | CONT-023 | 10 min |
| 9 | Esconder a linha de meta quando é só "—" | UI-029 | 10 min |
| 10 | `<Legend />` no gráfico de Relatórios | UI-025 | 15 min |
| 11 | Ícone diferente no botão de ativar avisos | UI-027 | 10 min |
| 12 | `grid-cols-2` nos KPIs dos Relatórios no celular | MOB-028 | 10 min |
| 13 | Piso de 44px em abas e ações secundárias no celular | MOB-024 | 40 min |
| 14 | `EmptyState` em Rendas e Recorrência | UI-033 | 30 min |
| 15 | Dispensar a faixa "Notificações bloqueadas" | UX-031 | 20 min |

**Total estimado: menos de um dia**, e cobre 3 dos 9 achados P1.

---

# 9. Melhorias estruturais

1. **Portão de truncamento.** O gate atual mede rolagem horizontal — e o pior defeito do
   relatório **não estoura nada**. Um portão que meça `clientWidth` de todo elemento com
   `truncate` (mínimo de 40px) e o rode em 320/360/390/412/768/900/1024/1366/1920 teria
   pegado MOB-001, RESP-002 e RESP-003 juntos.
2. **Fechar o design system.** 46 cores fora do sistema em 17 arquivos, com contraste
   reprovado em 4 lugares. Substituir por token **e** proibir por lint. Sem a segunda
   metade, volta.
3. **Rodapé fixo no primitivo de diálogo.** Resolve UX-004 para os ~12 diálogos de uma vez.
4. **Um contrato de estado de tela.** Hoje cada tela decide sozinha o que fazer em
   `isLoading` e `isError`, e o resultado varia de skeleton estruturado (Overview) a bloco
   cinza sem título (rotas de espaço) a números zerados (Extrato) a sumiço silencioso
   (Saldo). Um componente `<SecaoDeDados loading error onRetry>` padroniza os três estados
   e torna o erro impossível de esquecer.
5. **Estado de tela na URL.** `useMonthParam` e `useTabParam` já existem e são bons; falta
   generalizar para busca, filtros e abas (NAV-020, NAV-021).
6. **Navegação que caiba em 768px de altura.** 21 itens é muito para a barra. Recolher a
   seção "Pessoal" quando há um espaço aberto (e vice-versa) resolve sem perder acesso.
7. **Distinguir "sem sessão" de "sem rede".** Uma decisão só, no `useAuth`, que corrige
   ERR-006 e ERR-007 e evita a classe inteira de defeito.

---

# 10. Plano detalhado de implementação

> Ordem pensada para que cada etapa deixe o produto **verificável** ao final, e para que os
> portões venham antes das correções que eles protegem.

## Etapa 0 — Portões primeiro (antes de qualquer correção)

**Objetivo:** que os defeitos deste relatório fiquem vermelhos **antes** de serem
corrigidos. Sem isto não há como provar que a Fase 2 funcionou.

**Arquivos**
- `frontend/e2e/mobile_layout.mobile.spec.ts` (estender) ou novo
  `frontend/e2e/larguras.spec.ts`
- `frontend/eslint.config.js`

**Mudanças**
1. Portão de truncamento: em cada rota autenticada, para cada elemento com `truncate` e
   texto não vazio, assertar `clientWidth ≥ 40`. Nomear o elemento culpado na falha.
2. Rodar o portão em **320, 360, 390, 412, 768, 900, 1024, 1366, 1920**.
3. Portão de "ação primária visível": em cada diálogo do catálogo, o botão de submissão
   deve estar dentro da janela em 1366×768 e em 390×844.
4. Regra de lint proibindo `emerald-|amber-[0-9]|slate-[0-9]|rose-[0-9]|sky-[0-9]` em
   `src/**/*.tsx`, com allowlist vazia.
5. Estender `e2e/a11y.spec.ts` para **todas** as rotas autenticadas (hoje cobre 8).
6. **Portão do zero à esquerda:** teste de componente que, para cada campo numérico,
   escreve `0`, **digita** `5` (com `type`, nunca `fill`) e afirma que o campo exibe `5`.
   Os 7 campos da Administração entram como **controle positivo** — se eles também
   falharem, o teste está errado, não o app.
7. **Lista de verificação de PWA** (não automatizável no CI, entra na revalidação em
   aparelho da Etapa 9): barra de status legível nas 4 combinações de tema, área segura de
   cima reservada, splash coerente com o tema.

**Problemas endereçados:** infraestrutura de MOB-001, RESP-002, RESP-003, UX-004, UI-011,
A11Y-008, A11Y-009, **FORM-038**, **PWA-037**.

**Validação:** os portões novos **falham** (é o critério de aceitação desta etapa) e nomeiam
exatamente os elementos citados na seção 5.

**Risco:** nenhum (só teste). **Dependências:** nenhuma.

---

## Etapa 1 — Fundações (design system e primitivos)

**Objetivo:** eliminar a fonte comum de vários achados.

**Arquivos**
- `components/ui/dialog.tsx`, `progress.tsx`, `toaster.tsx`, `select.tsx`, `status-pill.tsx`
- os 17 arquivos com cor fora do sistema
- novo: `components/ui/secao-de-dados.tsx`

**Mudanças**
1. `DialogContent` com `grid-rows-[auto_1fr_auto]` e `DialogFooter` `sticky bottom-0`.
2. Substituir as 46 cores por token; `bg-muted` no trilho do `Progress`.
3. `SelectTrigger` passa a aceitar/exigir `aria-label`.
4. `StatusPill` ganha `min-w-0` + `truncate`.
5. `<SecaoDeDados>` encapsulando loading/erro/vazio com `ErrorState` + "Tentar novamente".

**Problemas resolvidos:** UX-004, UI-011 (parcial), A11Y-008 (mecanismo), base de MOB-001,
FDB-012/013/014.

**Riscos:** o rodapé fixo muda **todos** os diálogos — exige revisão visual do catálogo
inteiro. O trilho do progress muda o visual do onboarding e dos financiamentos.

**Validação:** `npm run shots` + comparação a olho das telas com diálogo; portão 3 da
Etapa 0 passa a verde.

---

## Etapa 2 — Responsividade (os três achados de largura)

**Arquivos**
- `components/money/TransactionItem.tsx`
- `pages/Settings/SettingsPage.tsx` (membros e convite)
- `pages/Reports/ReportsPage.tsx` (5px em 768)

**Mudanças**
1. `TransactionItem`: layout de duas linhas abaixo de `sm` (título em cima; meta e pílulas
   embaixo), pílulas com `min-w-0 truncate`, título com `min-w-0 flex-1`.
2. Linha de membro: `flex-col lg:flex-row`, identidade com `min-w-[12rem]`.
3. Linha de convite: `flex-wrap`, input com `min-w-[16rem]`.
4. `min-w-0` no cartão de KPI dos Relatórios e `overflow-x-hidden` no contêiner do gráfico.

**Problemas resolvidos:** MOB-001, RESP-002, RESP-003, UI-030.

**Validação:** portão de truncamento (Etapa 0) fica verde nas 9 larguras; conferir a olho
`390`, `1024` e `768` nas três telas.

---

## Etapa 3 — Estados de erro e sessão

**Arquivos**
- `api/client.ts`, `hooks/use-auth.ts`, `App.tsx`
- `components/dashboard/SaldoEProjecao.tsx`, `pages/GlobalLedgerPage.tsx`
- `components/layout/WorkspaceGuard.tsx`

**Mudanças**
1. Interceptor de 401: derrubar também o estado que o `ProtectedRoute` lê.
2. `useAuth`: separar "erro de rede/5xx" de "401" — o primeiro leva a "sem conexão" com
   retry, o segundo a `/login`.
3. `SaldoEProjecao` e KPIs do Extrato passam a usar `<SecaoDeDados>`.
4. `WorkspaceGuard` renderiza o `PageHeader` antes de resolver.
5. Rota `*` → página 404; `/w/:id` inválido → toast explicando.

**Problemas resolvidos:** ERR-006, ERR-007, FDB-012, FDB-013, FDB-014, NAV-019.

**Validação:** teste E2E novo — expirar a sessão com o app montado deve levar a `/login`
em ≤ 5s; teste com rota bloqueada deve mostrar "sem conexão", não a tela de login.

---

## Etapa 4 — Navegação e estado na URL

**Arquivos**
- `components/layout/Sidebar.tsx`, `AppShell.tsx`
- `pages/TransactionsPage.tsx`, `Reports/ReportsPage.tsx`, `Admin/AdminPage.tsx`,
  `Settings/SettingsPage.tsx`
- `hooks/` (generalizar `useTabParam`)

**Mudanças**
1. `scrollIntoView` do item ativo + máscara de gradiente no `nav`.
2. `aria-current="page"` e `aria-label` nos `nav`.
3. Skip link.
4. Busca e filtros de Lançamentos na query string.
5. `useTabParam` em Relatórios, Administração e nas duas telas de Configurações.

**Problemas resolvidos:** NAV-005, NAV-020, NAV-021, A11Y-010, A11Y-018.

**Validação:** clicar aba → recarregar → aba preservada, nas 6 telas; Tab #1 revela o skip
link; item ativo visível nas 4 rotas medidas.

---

## Etapa 5 — Formulários e ações

**Arquivos**
- `components/dashboard/NewTransactionDialog.tsx`, `TransactionForm.tsx`
- `components/layout/OnboardingModal.tsx`
- `pages/Settings/SettingsPage.tsx` (Zona de Perigo)
- `stores/` (foco de origem do diálogo)

**Mudanças**
1. Confirmação ao descartar formulário sujo (Escape/clique fora).
2. Restaurar o foco ao elemento que abriu o diálogo.
3. Onboarding: motivo do botão desabilitado, cor da marca, saída no passo 1, dia de
   fechamento aceitando vazio.
4. Excluir espaço: exigir digitar o nome + listar o que se perde.
5. **`NumberInput`** com texto em estado local e normalização no `blur`, aplicado aos
   5 campos com zero à esquerda e aos 3 com salto silencioso; os campos do
   react-hook-form passam por `Controller`. A referência do comportamento correto é a
   aba de Configurações da Administração, que já funciona.

**Problemas resolvidos:** UX-015, A11Y-017, UX-026, UX-035, **FORM-038**.

**Validação:** preencher, apertar Escape, confirmar que pergunta; Tab após fechar continua
de onde parou.

---

## Etapa 6 — Mobile

**Arquivos**
- `components/ui/tabs.tsx`, `button.tsx` (piso de altura em `< sm`)
- `pages/AccountsPage.tsx`, `MySettlementsPage.tsx`, `PayablesPage.tsx`
- `pages/Reports/ReportsPage.tsx`
- `components/financing/AmortizationTable.tsx`

**Mudanças**
1. Piso de 44px para aba, botão e link no celular.
2. KPIs dos Relatórios em 2 colunas.
3. Contas a pagar em seções recolhíveis por vencimento.
4. Seletor de financiamento vira `select` no celular.
5. Ações de conta agrupadas em menu.
6. **Área segura de cima:** utilidade `pt-safe` irmã da `pb-safe`, aplicada à barra
   superior do `AppShell`; `theme-color` clara trocada por um tom com contraste garantido
   contra ícones brancos; decisão sobre `apple-mobile-web-app-status-bar-style` e
   `background_color` do manifesto (ver PWA-037).

**Problemas resolvidos:** MOB-024, MOB-028, **PWA-037**, e a rolagem de 7.000px.

**Validação:** nenhum alvo interativo abaixo de 44px nas rotas medidas; `/me/payables` cabe
em ≤ 3.000px com as seções fechadas; **PWA-037 conferido em aparelho físico** nas quatro
combinações de tema do app × tema do sistema.

---

## Etapa 7 — Conteúdo e polimento

**Arquivos:** transversal.

**Mudanças**
1. Três rótulos "workspace" → "espaço"; `grep` no gate.
2. Sentence case em toda a interface.
3. "Setup"/"Tutorial" fora do onboarding.
4. Linha de meta sem o "—" solitário.
5. Legenda no gráfico; `EmptyState` em Rendas e Recorrência; ícone do sino; faixa de
   notificações dispensável; rótulos UPPERCASE padronizados.

**Problemas resolvidos:** CONT-023, UI-025, UI-027, UI-029, UI-033, UX-031, UI-036.

---

## Etapa 8 — Importar (opcional nesta rodada)

Colunas viradas em `select` a partir do cabeçalho lido, inferência de delimitador e formato,
botão de arquivo estilizado. **Resolve:** UX-032. **Esforço:** médio. Pode ficar para
depois — mas A11Y-009 (Etapa 0/4) **não** pode.

---

## Etapa 9 — Revalidação completa (obrigatória)

Repetir **toda** esta auditoria sobre o código já alterado:

1. Varredura de 24 rotas × 9 larguras: rolagem horizontal, truncamento, alvos de toque.
2. `axe` (wcag2a/aa + wcag21a/aa) em **todas** as rotas autenticadas, claro e escuro.
3. Jornadas ponta a ponta: cadastro → onboarding → primeira despesa → editar → excluir →
   filtrar → acertar → sair.
4. Estados: vazio (conta nova), carregando (latência de 3s), erro 500, 401, rede caída.
5. Teclado: Tab do topo até o conteúdo, focus trap, Escape, retorno de foco.
6. `npm run shots` e **conferência a olho** do catálogo (claro e escuro, desktop e mobile).
7. Os gates do projeto: `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`,
   `npm run test:e2e`, `pytest`.

**A implementação não está pronta quando o código muda; está pronta quando esta lista
passa.**

---

# 11. Ordem recomendada

```
0. Portões (que devem falhar)          ← sem isto, nada acima é verificável
1. Fundações: dialog, tokens, SecaoDeDados
2. Responsividade: extrato mobile, membros, convite
3. Erro e sessão
4. Navegação e estado na URL
5. Formulários e ações destrutivas
6. Mobile
7. Conteúdo e polimento
8. Importar (opcional)
9. Revalidação completa
```

Racional: a Etapa 1 mexe em primitivos usados por todas as outras (fazer depois obrigaria a
revisar duas vezes). A Etapa 2 depende do `StatusPill` da Etapa 1. As Etapas 3 e 4 são
independentes entre si e podem ir em paralelo. A Etapa 6 depende do piso de altura definido
na 1.

---

# 12. Matriz problema → implementação

| ID | Problema | Prior. | Solução | Etapa | Arquivos |
|---|---|:--:|---|:--:|---|
| MOB-001 | Título a 0px no celular | P0 | Duas linhas em `< sm`; `min-w-0` nas pílulas | 2 | `money/TransactionItem.tsx`, `ui/status-pill.tsx` |
| RESP-002 | Membros ilegíveis em 768–1100 | P1 | `flex-col lg:flex-row` + `min-w` | 2 | `Settings/SettingsPage.tsx` |
| RESP-003 | E-mail do convite a 20px | P1 | `flex-wrap` + `min-w` | 2 | `Settings/SettingsPage.tsx` |
| UX-004 | Salvar fora da tela | P1 | Rodapé fixo no `DialogContent` | 1 | `ui/dialog.tsx` |
| NAV-005 | Navegação abaixo da dobra | P1 | `scrollIntoView` + gradiente (+ seções recolhíveis) | 4 | `layout/Sidebar.tsx` |
| ERR-006 | Sessão expirada = spinner | P1 | Derrubar `auth-me` no interceptor | 3 | `api/client.ts`, `hooks/use-auth.ts` |
| ERR-007 | Sem rede = tela de login | P1 | Separar erro de rede de 401 | 3 | `hooks/use-auth.ts`, `App.tsx` |
| A11Y-008 | Filtros sem nome acessível | P1 | `aria-label` no trigger | 1 | `ui/select.tsx`, `TransactionsPage.tsx` |
| A11Y-009 | 7 campos sem rótulo | P1 | `id`/`htmlFor` | 4 | `pages/ImportPage.tsx` |
| A11Y-010 | Sem skip link | P1 | Link + `id` no `main` | 4 | `layout/AppShell.tsx` |
| PWA-037 | Barra de status branca / topo sem reserva | P1 | `pt-safe` + `theme-color` com contraste + meta do iOS | 6 | `index.css`, `layout/AppShell.tsx`, `index.html`, `manifest.webmanifest`, `hooks/use-theme.ts` |
| FORM-038 | Zero à esquerda persiste | P1 | `NumberInput` (ou `value={String(x)}`) | 5 | `CreditCardList.tsx`, `AmortizationTable.tsx`, `RecurrenceEditor.tsx`, `OnboardingModal.tsx`, `ItemsEditor.tsx`, `SplitEditor.tsx` |
| UI-011 | 46 cores fora do sistema | P2 | Tokens + lint | 1 | 17 arquivos |
| FDB-012 | Zeros durante o carregamento | P2 | Skeleton nos KPIs | 3 | `GlobalLedgerPage.tsx` |
| FDB-013 | Carregamento sem contexto | P2 | `PageHeader` fora do guard | 3 | `layout/WorkspaceGuard.tsx` |
| FDB-014 | Saldo falha em silêncio | P2 | `ErrorState` | 3 | `dashboard/SaldoEProjecao.tsx` |
| UX-015 | Escape descarta o formulário | P2 | Confirmar se sujo | 5 | `NewTransactionDialog.tsx` |
| A11Y-016 | `role=button` aninhado | P2 | Stretched link | 2 | `money/TransactionItem.tsx` |
| A11Y-017 | Foco volta ao `body` | P2 | Guardar/restaurar origem | 5 | `stores/`, `TransactionDetailHost.tsx` |
| A11Y-018 | Sem `aria-current` | P2 | Atributo + `aria-label` | 4 | `layout/Sidebar.tsx` |
| NAV-019 | Rota inválida em silêncio | P2 | 404 + toast | 3 | `App.tsx`, `WorkspaceGuard.tsx` |
| NAV-020 | Filtros fora da URL | P2 | `useSearchParams` | 4 | `TransactionsPage.tsx` |
| NAV-021 | 3 padrões de aba | P2 | `useTabParam` em todas | 4 | 4 páginas |
| UI-022 | 700×216px vazios no Painel | P2 | Faixa de KPIs + lista larga | 6 | `pages/Home.tsx` |
| CONT-023 | "workspace" e Title Case | P2 | Rótulos + gate | 7 | `Settings/SettingsPage.tsx` e outros |
| MOB-024 | Alvos de 28px | P2 | Piso de 44px | 6 | `ui/tabs.tsx`, `ui/button.tsx`, páginas |
| UI-025 | Gráfico sem legenda | P2 | `<Legend />` | 7 | `Reports/ReportsPage.tsx` |
| UX-026 | Onboarding trava sem dizer | P2 | Mensagem + cor + saída | 5 | `layout/OnboardingModal.tsx` |
| UI-027 | Dois sinos | P2 | Ícone distinto | 7 | `notifications/AtivarNotificacoes.tsx` |
| MOB-028 | KPIs em 1 coluna | P2 | `grid-cols-2` | 6 | `Reports/ReportsPage.tsx` |
| UI-029 | "—" solitário | P3 | Esconder meta vazia | 7 | `money/TransactionItem.tsx` |
| UI-030 | 5px em 768 | P3 | `min-w-0` + `overflow-x-hidden` | 2 | `Reports/ReportsPage.tsx` |
| UX-031 | Faixa não dispensável | P3 | Botão de dispensar | 7 | `notifications/AtivarNotificacoes.tsx` |
| UX-032 | Importar exige strftime | P3 | Colunas por `select` | 8 | `pages/ImportPage.tsx` |
| UI-033 | Vazio sem `EmptyState` | P3 | Componente padrão | 7 | `IncomePage.tsx`, `RecurringTransactionsPage.tsx` |
| PERF-034 | 11 endpoints na abertura | P3 | Carregar sob demanda | 6 | `layout/AppShell.tsx`, hooks |
| UX-035 | Excluir espaço genérico | P3 | Digitar o nome | 5 | `Settings/SettingsPage.tsx` |
| UI-036 | Rótulos UPPERCASE | P3 | Sentence case | 7 | transversal |

---

# 13. Checklist da Fase 2

**Etapa 0 — Portões**
- [ ] Portão de truncamento (`clientWidth ≥ 40`) em 9 larguras
- [ ] Portão de ação primária visível nos diálogos
- [ ] Lint contra cor fora do design system
- [ ] `a11y.spec.ts` estendido a todas as rotas autenticadas
- [ ] **Confirmado que os portões falham antes das correções**

**Etapa 1 — Fundações**
- [ ] UX-004 · [ ] UI-011 · [ ] A11Y-008 (mecanismo) · [ ] `SecaoDeDados`

**Etapa 2 — Responsividade**
- [ ] MOB-001 · [ ] RESP-002 · [ ] RESP-003 · [ ] A11Y-016 · [ ] UI-030

**Etapa 3 — Erro e sessão**
- [ ] ERR-006 · [ ] ERR-007 · [ ] FDB-012 · [ ] FDB-013 · [ ] FDB-014 · [ ] NAV-019

**Etapa 4 — Navegação**
- [ ] NAV-005 · [ ] NAV-020 · [ ] NAV-021 · [ ] A11Y-009 · [ ] A11Y-010 · [ ] A11Y-018

**Etapa 5 — Formulários**
- [ ] UX-015 · [ ] A11Y-017 · [ ] UX-026 · [ ] UX-035 · [ ] **FORM-038**

**Etapa 6 — Mobile**
- [ ] MOB-024 · [ ] MOB-028 · [ ] UI-022 · [ ] PERF-034 · [ ] **PWA-037**
- [ ] PWA-037 revalidado **em aparelho físico** (não dá para validar no emulador)

**Etapa 7 — Conteúdo**
- [ ] CONT-023 · [ ] UI-025 · [ ] UI-027 · [ ] UI-029 · [ ] UI-033 · [ ] UX-031 · [ ] UI-036

**Etapa 8 — Importar (opcional)**
- [ ] UX-032

**Etapa 9 — Revalidação**
- [ ] Auditoria repetida por inteiro (seção 10, Etapa 9)

---

# 14. Critérios de aceitação

| Etapa | Como saberemos que ficou certo |
|---|---|
| 0 | Os portões existem e **falham**, nomeando os elementos das seções MOB-001, RESP-002, UX-004 e UI-011. O portão do zero à esquerda falha nos 5 campos de FORM-038 e **passa** nos 7 da Administração (controle positivo). |
| 1 | Em 1366×768 e 390×844, o botão de submissão de **todo** diálogo tem `getBoundingClientRect().bottom ≤ innerHeight` sem rolar. `grep -E "emerald-\|amber-[0-9]\|slate-[0-9]" src --include=*.tsx` devolve **0**. Axe não reporta `color-contrast` em nenhuma rota. |
| 2 | Em 320, 360, 390, 412, 768, 900 e 1024px, **todo** elemento com `truncate` e texto tem `clientWidth ≥ 40px`. Em 390px, os 15 títulos da lista de lançamentos são legíveis e nenhuma pílula sobrepõe o valor. Em 1024px, os 4 nomes de membro aparecem por extenso ou com reticências (nunca abaixo de 120px). |
| 3 | Com a sessão expirada e o app montado, a URL vira `/login` em ≤ 5s. Com a API inalcançável, aparece "sem conexão" com botão de tentar de novo — **não** a tela de login. Com 500 em `/me/balance`, o bloco mostra erro com retry. Com latência de 3s, o Extrato mostra skeleton nos KPIs (nenhum "R$ 0,00"). `/w/:id/*` mostra o título desde o primeiro quadro. |
| 4 | Primeiro Tab revela "Pular para o conteúdo" e ele funciona. Em `/admin`, `/w/:id/settings` e `/w/:id/import` a 1366×768, o item ativo está dentro da janela e tem `aria-current="page"`. Clicar uma aba e recarregar preserva a aba nas 6 telas. Buscar "Café", recarregar e a busca continua aplicada. Axe: 0 violações `critical` em todas as rotas. |
| 5 | Preencher a despesa e apertar Escape abre confirmação; cancelar mantém o que foi digitado. Fechado o diálogo, o próximo Tab continua de onde parou. Nome de cartão sem limite mostra mensagem no campo. Excluir espaço exige digitar o nome. **Em cada um dos 8 campos numéricos listados em FORM-038: escrever `0`, teclar `5` e o campo exibir `5`; e ser possível apagar o campo por completo sem ele saltar sozinho.** |
| 6 | Em 390 e 360px, nenhum elemento interativo tem altura < 44px nas rotas medidas. `/me/payables` cabe em ≤ 3.000px com as seções fechadas. Relatórios mostra 4 KPIs em 2 colunas. `/w/:id` não tem área vazia > 100px de altura em 1366×768. **No aparelho, com o app instalado: hora, bateria e ícones de notificação legíveis nas 4 combinações (app claro/escuro × sistema claro/escuro), e nenhum controle da barra superior do app sob a barra do sistema.** |
| 7 | `grep -i "workspace" src --include=*.tsx` não devolve nenhuma **string de interface**. O gráfico tem legenda. Rendas e Recorrência usam `EmptyState`. |
| 9 | Todos os gates do projeto verdes **e** o catálogo de 129 capturas conferido a olho, claro e escuro. |

---

# 15. O que **não** deve ser alterado

Lista explícita, para a Fase 2 não gastar risco onde não há problema:

- **`EmptyState` e os textos dos estados vazios** — as 17 telas foram conferidas com conta
  nova. Estão certos. Só levar o componente às duas telas que ainda não o usam.
- **`useConfirm` e o padrão de confirmação** — bem construído, "Cancelar" primeiro, foco
  seguro, alvo nomeado. Só acrescentar a digitação do nome para excluir espaço.
- **Tratamento de erro no formulário de despesa** — mensagem do servidor inline + dados
  preservados. É o padrão a **copiar** para as outras telas, não a mudar.
- **`useAcaoPendente` (trava de duplo clique)** — medido, funciona.
- **A conversão de tabela em cartões no celular** (Rendas, Recorrência, Financiamentos).
- **A tela de Acertos "Por mês"** — o melhor texto do produto.
- **O vocabulário Pessoal × Compartilhado × espaço** e a estrutura de navegação em três
  camadas. Corrigir só os 3 vazamentos de "workspace".
- **Os tokens de cor do `index.css`** — as luminosidades foram escolhidas com a conta de
  contraste feita e comentada. O problema é quem **não** os usa.
- **O tema escuro** — não precisa de retoque.
- **A barra inferior, o FAB, a gaveta "Mais" e o `ScopeSwitcher`** — arquitetura mobile
  correta.
- **`min-h-dvh`, `env(safe-area-inset-bottom)`, `pb-safe`, `inputMode` dos campos de
  dinheiro** — decisões corretas e documentadas; não "simplificar".
- **O onboarding ser bloqueante** — é uma decisão de produto, não um defeito. Corrigir só o
  botão travado sem explicação, a cor e o texto.
- **O gate de 360px** — funciona. **Estender**, nunca substituir.
- **`ProtectedRoute` usando `useAuth()` em vez do store** — a mudança está certa; o que
  ficou para trás foi o interceptor (ERR-006).

---

# 16. O que eu achei que era problema e não era

Registrado para a próxima auditoria não gastar tempo:

1. **"Clicar no ícone de excluir abre o detalhe do lançamento."** Reproduzi 3 de 3 — e era
   artefato do meu seletor (`page.getByRole(...).first()` fora do escopo da linha). Com o
   clique correto, na linha, no desktop e no toque mobile: abre a confirmação certa,
   1 diálogo. **Não é defeito.**
2. **"24 chamadas de API ao abrir o Seu mês."** É o `StrictMode` do React em
   desenvolvimento duplicando os efeitos. Em produção são 11 endpoints distintos — o que
   ainda rende o PERF-034, mas de gravidade bem menor do que os 24 sugeriam.
3. **"O erro de rede não mostra toast."** Mostra melhor que isso: erro inline no
   formulário, com a mensagem do servidor e os dados preservados. Meu seletor procurava
   `[role="status"]`.
4. **"Valores em dinheiro cortados em 768–960px" (F3 da auditoria anterior).** **Corrigido**
   — medi as 24 rotas em 768, 900 e 1024: nenhum valor truncado. Só sobrou a rolagem de
   5px em Relatórios (UI-030).
5. **"`npm run shots` estoura o tempo" (F6 da auditoria anterior).** **Corrigido** — a
   execução completa gerou as 129 capturas com código de saída 0.
6. **Rolagem horizontal no celular.** Procurei em 24 rotas × 320/360/390/412px, com título
   de 150 caracteres e valor de R$ 1.234.567,89 semeados de propósito: **zero**.

---

# 17. Método e limites

**O que foi executado**

| Verificação | Escopo | Resultado |
|---|---|---|
| Varredura de larguras | 24 rotas × 10 larguras (320→1920), medindo `scrollWidth`, truncamento e alvos de toque | 0 rolagens horizontais; 6 telas com truncamento |
| `axe-core` (wcag2a/aa + 2.1) | 24 rotas em 1366 e 390 | 6 tipos de violação, 2 críticos |
| Jornada de usuário novo | cadastro pela UI → validação → onboarding → 17 rotas vazias | estados vazios íntegros |
| Fluxo de despesa | abrir, submeter vazio, preencher, duplo clique, Escape, erro 500 | 1 achado (UX-015) |
| Ação destrutiva | excluir lançamento (desktop e toque), excluir financiamento | confirmações corretas |
| Estados de erro | 500 em 2 endpoints, rede caída, 401, sessão apagada | 4 achados |
| Carregamento | latência de 3s em 8 rotas | 2 achados |
| Teclado | Tab do topo, focus trap, Shift+Tab, Escape, retorno de foco | 4 achados |
| Estresse de dados | título de 150 caracteres, valor de 7 dígitos, texto sem espaços | sem quebra |
| Catálogo visual | 129 capturas (`npm run shots`), claro e escuro, desktop e mobile | inspeção a olho |

**Dois pontos cegos, revelados pelo dono em 2026-09-04**

Os dois achados novos não são detalhe: são **falhas do método**, e vale registrar a causa
para a próxima rodada não repeti-las.

1. **PWA-037 — medi viewports, não aparelhos.** Toda a varredura foi
   `browser.newContext({ viewport })` num Chromium de desktop. Nesse ambiente
   `env(safe-area-inset-*)` vale **sempre 0** e a barra de status do sistema **não existe**
   — então a ausência de `safe-area-inset-top` no CSS não podia produzir nenhum sintoma
   mensurável, e a cor da barra do sistema não estava em tela nenhuma que eu capturei.
   *Lição:* o que só existe fora da viewport (barra de status, teclado virtual, gestos do
   sistema, splash da instalação) exige aparelho — ou, no mínimo, uma leitura explícita do
   `index.html`/manifesto contra uma lista de verificação de PWA. Eu li os dois arquivos
   procurando o botão de instalar, não a barra de status.

2. **FORM-038 — `fill()` não digita.** Testei os formulários com
   `locator.fill('valor')`, que **substitui** o conteúdo do campo de uma vez. O defeito só
   aparece quando se **digita sobre** o que já está lá (`type()` com o cursor no fim) —
   e é exatamente assim que uma pessoa usa um campo que já vem preenchido com `0`.
   Nenhum dos meus testes de formulário chegou a exercitar edição incremental.
   *Lição:* em campo que nasce com valor padrão, testar **digitação a partir do valor
   existente**, não só o preenchimento do zero. Vale para máscara, para clamp e para
   normalização.

Ambos entraram na Etapa 0 (portões) do plano: o caso do zero vira teste de componente, e a
lista de verificação de PWA vira parte da revalidação em aparelho da Etapa 9.

**Limites declarados**

- **Não testei em aparelho físico** — e é a limitação que produziu o ponto cego do
  PWA-037. A validação daquele achado, e a da Etapa 6, só valem no celular do dono.
  Teclado virtual e gestos do sistema também não foram exercitados de verdade.
- Não testei com **leitor de tela real** (NVDA/VoiceOver); a auditoria de acessibilidade é
  axe + navegação por teclado + inspeção do DOM.
- Não testei **Safari/Firefox** — só Chromium.
- **Performance de rede real** (3G, latência alta) foi simulada por interceptação, não por
  throttling de rede do DevTools.
- O fluxo de **importação de CSV** foi avaliado pela interface e pelo código; não importei
  um arquivo de verdade.
- **Notificações push** aparecem sempre como "bloqueadas" no navegador headless, então as
  telas que dependem do estado "ativado" não foram vistas nesse estado.
- Os **acertos com histórico** ficaram vazios na base semeada; a tabela mais larga do app
  (Histórico de acertos) foi avaliada vazia.

---

---

# 18. FASE 2 — implementação (2026-09-04)

Plano aprovado pelo dono e executado nas etapas 0 a 9. Esta seção registra o que foi
feito, o que ficou de fora **com o motivo**, e o resultado da revalidação.

## 18.1 — Resultado da revalidação

| Verificação | Antes | Depois |
|---|---|---|
| Portão de texto espremido (24 rotas × 5 larguras) | **4 falhas** | **6/6 verde** |
| Portão da ação primária do diálogo | falha em 1366 e 390 | verde |
| Portão do zero à esquerda | 4 falhas + 1 controle verde | **5/5 verde** |
| `axe` (wcag2a/aa + 2.1) em 24 rotas, 1366px | 6 tipos, 2 críticos | **0 violações** |
| `axe` em 24 rotas, 390px | 6 tipos | **0 violações** |
| Rolagem horizontal (24 rotas × 8 larguras = 192 cargas) | 1 rota | **0** |
| Erros de console na varredura | 0 | **0** |
| `npm test` (vitest) | 522 | **523 passando** |
| `npm run test:e2e` | 53/54 (1 corrida) | **54/54, três vezes seguidas** |
| `pytest` (backend) | — | **3.099 passando**, 10 pulados |
| `npm run typecheck` · `lint` · `build` | — | **verdes** |
| Catálogo `npm run shots` | 129 capturas | 129 capturas, conferidas a olho |

## 18.2 — O que mudou, por achado

**P0 e P1 — todos resolvidos**

- **MOB-001** — a linha do extrato virou duas: título sozinho na primeira, meta e
  pílulas na segunda. As pílulas ganharam `shrink-0` + `whitespace-nowrap`; quem cede é
  o título, que agora tem piso. Medido a 360/390/412px: nenhum título abaixo de 40px.
- **RESP-002 / RESP-003** — a causa real era mais funda do que a linha de membros: o rail
  de abas das Configurações abria em duas colunas já a partir de `md` (768px), deixando
  ~200px para o conteúdo inteiro. Passou a `lg`; a linha de membro empilha abaixo de `lg`
  e o convite ganhou `flex-wrap`.
- **UX-004** — `DialogFooter` virou rodapé fixo (`sticky`), com deslocamento negativo do
  tamanho exato do `padding` do diálogo. Vale para os 12 diálogos, não só o de despesa.
- **NAV-005** — item ativo entra em vista (`scrollIntoView`) e a barra ganhou máscara de
  gradiente como afordância de rolagem.
- **ERR-006** — o interceptor de 401 passou a derrubar a `auth-me` do react-query, não só
  o store. Sessão que expira com o app aberto agora vai para `/login` em segundos.
- **ERR-007** — `useAuth` distingue 401 de falha de rede/5xx; a segunda mostra "Sem
  conexão com o servidor" com botão de tentar de novo, em vez da tela de login.
- **A11Y-008** — `SelectTrigger` passou a **exigir** `aria-label`/`aria-labelledby` por
  tipo. O compilador achou os 6 usos sem rótulo.
- **A11Y-009** — os 7 campos do Importar ganharam `id`/`htmlFor`.
- **A11Y-010** — link "Pular para o conteúdo" + `id`/`tabIndex` no `<main>`.
- **PWA-037** — `theme_color` e `background_color` do manifesto passaram de `#fcfbf9`
  (1,03:1 contra ícone branco) para a marca `#4c55bc` (6,30:1); nasceu a utilidade
  `pt-safe`, irmã da `pb-safe`, aplicada à barra superior; o iOS passou a
  `black-translucent`, que só é correto **porque** a área de cima agora é reservada.
- **FORM-038** — nasceu `ui/NumberInput`: texto em estado local, número no `onChange`,
  normalização no `blur`. Aplicado a 6 campos; os 3 do react-hook-form usam
  `normalizarAoSair`. Os fallbacks `|| 5` e `Math.max(1, … || 1)`, que repunham o valor a
  cada tecla, saíram.

**P2 e P3** — resolvidos: UI-011 (46 cores → tokens, com regra de lint), FDB-012, FDB-013,
FDB-014, UX-015, A11Y-016, A11Y-017, A11Y-018, NAV-019, NAV-020, NAV-021, UI-022,
CONT-023, MOB-024, UI-025, UX-026, UI-027, MOB-028, UI-029, UI-030, UX-031, UI-033,
UX-035, UI-036.

## 18.3 — O que NÃO foi feito, e por quê

- **PERF-034** (11 endpoints na abertura do "Seu mês") — **diferido**. A correção exige
  mudar onde `useMembers`/`useCategories` são montados, o que atravessa o `AppShell` e
  vários hooks. É um P3 imperceptível em qualquer conexão normal, e o risco de quebrar
  fluxo de dados não se paga. Fica registrado com a causa já mapeada.
- **UX-032** (wizard de importação) — **diferido**, como o próprio plano previa (Etapa 8
  opcional). A parte que não podia esperar — os 7 campos sem rótulo (A11Y-009) — foi
  feita.
- **`<SecaoDeDados>`** — foi **construído e depois removido**. A ideia era um contrato
  único para carregando/erro/vazio, mas aplicá-lo aos dois lugares que precisavam exigia
  reestruturar telas já validadas, sem ganho de comportamento. Os três estados foram
  corrigidos direto; um componente compartilhado sem nenhum chamador apodrece e engana
  quem vier depois.

## 18.4 — Defeitos que a própria implementação criou (e como apareceram)

Registrado porque é o que justifica ter feito os portões primeiro:

1. **Um comentário JSX mal colocado** quebrou a compilação de `SettingsPage` — e o portão
   de truncamento ficou **verde**, porque numa página que não renderiza não há texto
   espremido. O portão ganhou `telaRenderizou()`, que reprova quando o `<main>` está
   vazio ou há tarja de erro do Vite.
2. **O efeito de troca de espaço reescrevia a URL** e atropelava a navegação do
   `ScopeSwitcher`: escolher outro espaço no celular deixava o endereço no espaço antigo.
   Quem pegou foi `mobile_layout.mobile.spec.ts`.
3. **A margem negativa do rodapé fixo** deixava o conteúdo reaparecer por baixo da barra
   de ações. Medido (25px no desktop, 21px no celular) e trocado por deslocamento de
   `sticky`.
4. **`pt-safe` sem piso** zerou os 8px de respiro da barra superior no desktop. Virou
   `max(0.5rem, env(...))`.
5. **A minha própria spec disputava a conta de superadministrador** com dois outros
   arquivos. Ao investigar, apareceu uma **corrida pré-existente** entre `a11y.spec.ts` e
   `mobile_layout.mobile.spec.ts` — os dois registravam a mesma conta única, e quem
   chegasse depois encontrava a janela de bootstrap fechada. Resolvido na raiz:
   `scripts/e2e.mjs` cria o superadministrador antes de o Playwright subir. Três rodadas
   seguidas de 54/54 confirmam.

## 18.5 — Portões novos (o que impede a volta)

| Portão | Onde | O que mede |
|---|---|---|
| Texto espremido | `e2e/larguras.spec.ts` | todo `truncate` cortado tem ≥ 40px, em 5 larguras |
| Ação principal visível | `e2e/larguras.spec.ts` | o botão de submissão do diálogo nasce dentro da janela |
| Página renderizou | `e2e/larguras.spec.ts` | impede o portão de passar numa tela quebrada |
| Zero à esquerda | `e2e/campos_numericos.spec.ts` | digita sobre o valor existente (nunca `fill`) |
| Cor fora do design system | `eslint.config.js` | proíbe `emerald-*`, `amber-N`, `slate-N`… em `src/**` |
| Contraste da barra de status | `scripts/verify-build-assets.mjs` | `theme_color` legível com ícone branco (roda no `npm run build`) |
| Tag dentro de comentário | `teclado-do-celular.test.ts` | o portão do teclado deixou de acusar prosa — nos dois sentidos |

## 18.6 — O que continua pendente de validação em aparelho

**PWA-037 só se confirma no celular do dono.** `env(safe-area-inset-top)` vale 0 num
navegador de desktop e a barra de status do sistema não existe ali. O que fazer:

1. **Desinstalar e reinstalar** o app (o WebAPK guarda o manifesto da instalação — sem
   isso o teste dá falso negativo).
2. Abrir no tema escuro: nem a splash nem a barra de status podem ser brancas.
3. Alternar as quatro combinações (app claro/escuro × sistema claro/escuro) e conferir que
   hora, bateria e ícones continuam legíveis.
4. Conferir que o seletor de espaço e os sinos não ficam sob a barra do sistema.

---

**FASE 1 concluída em 2026-09-03. FASE 2 concluída em 2026-09-04: 37 dos 38 achados
implementados e revalidados; PERF-034 diferido com o motivo registrado. Falta a
conferência do PWA-037 em aparelho físico.**
