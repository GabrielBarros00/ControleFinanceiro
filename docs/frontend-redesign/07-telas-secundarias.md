# 07 — Redesign das telas secundárias

Mesma linguagem do doc 06, para o restante das telas. Reaproveitam os padrões já
definidos (`PageHeader`, `DataTable`/`CardList`, `MoneyText`, `EmptyState`, `StatusPill`),
então aqui o foco é o que é **específico** de cada uma.

---

## 1. Rendas (`/income`) + Rendas recorrentes

Hoje: duas tabelas (rendas e recorrentes) + modal com toggle "recorrente". Boa base; só
alinhar ao sistema e reduzir ruído (`UPPERCASE` nos headers, valores sempre verdes soltos).

```
┌ PageHeader · Rendas                  [ ‹ Julho › ]  [Lançar pendentes] [+ Nova renda] │
│ Salários e entradas que alimentam sua previsão.  Total do mês +R$ 9.050,00 │

┌ Tabs: [ Rendas do mês ]  [ Recorrentes ] ────────────────────────────┐

RENDAS DO MÊS (DataTable/CardList)
  💰 Salário           recebida 02/07        recorrente          +R$ 7.200,00  ⋯
  💰 Freelance Design  recebida 14/07                            +R$ 1.850,00  ⋯

RECORRENTES
  Salário   Todo mês · dia 5   [Ativa]                          R$ 7.200,00  ⋯
```

**O que muda:**
- Recorrência de renda vira **aba** (não seção solta) — consistente com "Lançamentos →
  Fixos" (04). O mesmo `RecurrenceEditor` no modal.
- Valores via `MoneyText kind="income"` (verde + `+`), headers em `label` sentence case.
- "Lançar pendentes" ganha destaque quando **há** pendências (badge com contagem); some/
  fica discreto quando não há.
- Total do mês no `PageHeader` (não num parágrafo). `StatusPill` Ativa/Inativa.

---

## 2. Dívidas & Acertos (`/debts`) — clareza de "quem paga quem"

Tela rica (balanço mensal + saldo geral + histórico). Boa informação, apresentação pesada.

```
┌ PageHeader · Dívidas & Acertos            [ ‹ Julho › ]   [Atualizar] │
│ Quem deve para quem — e os acertos já feitos.                         │

┌ Seu balanço (destaque) ──────────────────────────────────────────────┐
│  Você deve         Você recebe        Saldo líquido                    │
│  −R$ 80,00          +R$ 0,00           você deve R$ 80,00              │
└───────────────────────────────────────────────────────────────────────┘

┌ A acertar (cards de pessoa, não tabela) ─────────────────────────────┐
│  (BIA)  Bianca            você deve            −R$ 80,00   [ Paguei ]  │
│  (CAR)  Carlos            te deve              +R$ 40,00   [ Recebi ]  │
└───────────────────────────────────────────────────────────────────────┘

┌ Por mês (MonthlyDebtsSection) — chips de mês + status por parcela ────┐
┌ Histórico de acertos (DataTable) — desfazer ─────────────────────────┐
┌ 💡 Como os acertos funcionam (callout discreto) ─────────────────────┐
```

**O que muda:**
- **"Seu balanço"** no topo (deve / recebe / líquido) com `MoneyText` — resposta imediata
  ("você deve R$ 80"). Hoje isso está diluído em dois cards grandes lado a lado.
- Dívidas como **linha de pessoa** (avatar + nome + direção + valor + ação), calmas — não
  cartões com borda vermelha/verde grossa. Direção clara: "você deve" / "te deve".
- Mantém `MonthlyDebtsSection` (settlement-aware por mês — bom) e histórico com "desfazer".
- Callout explicativo vira nota discreta ao final (bom conteúdo, tom mais leve).
- Empty: "Ninguém deve nada 🎉" só quando realmente zero (manter o toque simpático).

---

## 3. Financiamentos (`/financing`) — valorizar o SAC/PRICE

Funcionalmente impressionante (saldo devedor, próxima parcela, **economia se quitar hoje**,
tabela de amortização, pagar parcela). Só precisa de hierarquia e mobile.

```
┌ PageHeader · Financiamentos                              [+ Novo] ────┐
│ Chips de financiamentos: [ Apartamento ] [ Carro • QUITADO ]          │

┌ 3 StatTiles ─────────────────────────────────────────────────────────┐
│ Saldo devedor R$ 182.400   Próxima R$ 2.310 · vence 10/08   Economia se quitar hoje +R$ 14.200 │
│ [████░░░░░░] 12 de 240 parcelas pagas                                  │

┌ Tabela de amortização (DataTable · densidade compacta) ──────────────┐
│ Nº  Vencimento  Amortização  Juros   Total    Saldo devedor   Status  │
│  13 10/08/2026  R$ 760       R$ 1.550 R$2.310  R$ 181.640    [Pagar]  │
│  14 …                                                         Pendente │
└───────────────────────────────────────────────────────────────────────┘
```

**O que muda:**
- "Economia se quitar hoje" ganha **destaque de insight** (é o recurso mais legal e hoje é
  só um card cinza). Cor `income` + explicação ("pagaria R$ X a valor presente").
- Barra de progresso de parcelas no StatTile de saldo.
- Tabela em `DataTable` compacto; no mobile vira `CardList` (parcela = card com nº/venc/
  total/status/ação Pagar). `StatusPill` Paga/Próxima/Pendente.
- Seleção de financiamento por chips (mantido), com estado QUITADO claro.
- Empty educa: "Cadastre um financiamento para ver o cronograma SAC/PRICE e simular
  quitação antecipada."

---

## 4. Importar (`/import`) — assistente em passos

Hoje: 1 coluna de config (muitos inputs de mapeamento) + preview. Funciona, mas parece
formulário técnico. Alvo: **wizard** leve de 3 passos, menos intimidante.

```
┌ PageHeader · Importar extrato ───────────────────────────────────────┐
│ Passos:  ①(Arquivo) → ②(Mapear colunas) → ③(Revisar & confirmar)      │

① Arquivo:   área de drop grande "Arraste seu CSV ou clique" + presets de banco (Nubank,
             Itaú, …) que pré-preenchem delimitador/colunas/formato de data.
② Mapear:    os campos atuais (delimitador, decimal, formato de data, colunas) — mas em 2
             colunas, com **preview ao vivo** das 3 primeiras linhas do arquivo ao lado.
③ Revisar:   a tabela de preview atual + destaque de duplicatas (âmbar) e linhas inválidas
             (vermelho) + toggle "pular duplicatas" + [ Confirmar N transações ].
```

**O que muda:**
- Transforma a parede de inputs num **stepper** (menos "cara de config"). Presets de banco
  reduzem o mapeamento manual (maior fricção hoje).
- `EmptyState` do preview vira o passo ① (drop zone), não uma caixa vazia.
- Duplicata/erro com `StatusPill`/tint (âmbar/vermelho), como já começa a existir.
- Mantém a lógica boa (fingerprint/idempotência, decisão por linha).

---

## 5. Configurações (`/settings`) — manter, alinhar

Já é um hub de abas bem organizado (Perfil, Segurança, Membros, Categorias, Contas,
Aparência). Mudanças mínimas:

- **Aparência**: além de Claro/Escuro/Sistema, é onde a pessoa escolhe (se adotarmos)
  a variante de marca; e onde mostramos um _preview_ do tema. Ótimo lugar para densidade
  (Confortável/Compacta) no futuro.
- **Categorias**: mostrar o **ícone + cor** de cada categoria (hoje só a cor); permitir
  escolher ícone/cor (o back já guarda `icon`/`color`). Liga direto ao `CategoryGlyph`.
- **Membros**: linhas de membro no padrão pessoa (avatar+nome+papel via `StatusPill`),
  convites e "zona de perigo" como estão (bem resolvidos), só realinhados.
- **Contas & Carteiras**: idem, com ícone por tipo.
- Navegação de abas: no mobile vira um `Select`/sheet em vez da coluna lateral de 240px.

---

## 6. Autenticação (`/login`, `/register`, recuperar senha)

Hoje: card central limpo, porém **preto-e-branco estéril** (`auth-login.png`). Elevar para
"confiável e caprichado" sem exagero.

```
┌ Split layout (desktop) ──────────────────────────────────────────────┐
│  Painel de marca (esq., 40%)      │   Card de formulário (dir., 60%)   │
│  • logo + nome                    │   Bem-vindo de volta               │
│  • frase de valor curta           │   [ E-mail ]                       │
│  • fundo: gradiente sutil da marca│   [ Senha ]           Esqueceu?    │
│    + textura/leve ilustração      │   [ Acessar conta → ]              │
│                                   │   ── ou ──  [ G  Entrar com Google]│
│                                   │   Não tem conta? Cadastre-se       │
└───────────────────────────────────────────────────────────────────────┘
mobile: só o card, com logo no topo.
```

**O que muda:**
- **Split layout** com um painel de marca (gradiente sutil da cor de marca + logo + uma
  frase). Dá identidade sem pesar; o formulário fica igualmente simples.
- Inputs, foco e botão no sistema (marca, não preto). Ícones de campo mantidos.
- Consistência entre login/registro/recuperar (mesma casca).
- Acessibilidade: labels já ok; garantir contraste do painel de marca.

---

## 7. Onboarding (modal 3 passos)

Hoje: modal centralizado sobre dashboard borrado, 3 passos (boas-vindas → renda → cartão).
Boa ideia, manter o fluxo; alinhar visual e reforçar o "porquê".

- Passo 1: boas-vindas — calmo, com o que a pessoa vai conseguir ("acompanhe gastos,
  divida contas, controle faturas").
- Passo 2: renda — `AmountInput`, com dica de que alimenta a "sobra do mês".
- Passo 3: cartão (opcional) — com preview do `CreditCardVisual` sendo "montado".
- Barra de progresso no topo (já existe) alinhada ao sistema; botão "Pular" sempre claro.
- Ao concluir, cair no **Início já com o HeroBalance** fazendo sentido (renda preenchida).
- Mobile: vira bottom sheet em passos.

---

### Resumo do impacto (telas secundárias)

| Tela | Mudança-chave | Resolve |
|------|---------------|---------|
| Rendas | Recorrente vira aba; `MoneyText` income; total no header | H2, H4, B1 |
| Dívidas | "Seu balanço" no topo; dívidas como linha de pessoa | H1, H2 |
| Financiamentos | Destaque "economia se quitar"; tabela compacta + mobile | H2, H5 |
| Importar | Wizard 3 passos + presets de banco | H2 |
| Configurações | Alinhar; ícone/cor de categoria; abas mobile | H4, H5 |
| Auth | Split layout com painel de marca | H3 |
| Onboarding | Alinhar + preview do cartão; sheet no mobile | H2, H5 |
