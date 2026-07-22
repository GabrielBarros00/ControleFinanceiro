# 02 — Visão de design & princípios

O que queremos que o app _seja_, antes de qualquer pixel. Este documento é a régua para
decidir qualquer dúvida de design nas fases seguintes.

---

## O conceito: **"Calm Finance / Ledger"**

Um companheiro financeiro **calmo, confiável e editorial**. Pense na diferença entre:

- ❌ um _dashboard de startup_ com 12 widgets neon disputando atenção (o que temos hoje), e
- ✅ um **extrato bem tipografado** de um private bank: espaço para respirar, números
  impecáveis, uma cor de destaque usada com intenção, hierarquia óbvia.

A palavra-chave é **intenção**. Cada elemento na tela justifica sua presença. O usuário
abre o app e em 2 segundos sabe: _quanto tenho, quanto gastei, quanto sobra, o que
aconteceu por último._ Nada mais compete com isso.

### As três qualidades que perseguimos

1. **Confiança** — precisão visual. Números tabulares alinhados, moeda sempre no mesmo
   formato, sinais e cores corretos. Um erro de formatação num app de dinheiro custa
   credibilidade desproporcional.
2. **Calma** — pouco contraste desnecessário, superfícies suaves, um só nível de
   elevação, movimento discreto. O dinheiro já é estressante; a interface não soma a isso.
3. **Modernidade sóbria** — atual (2025+), mas atemporal. Cantos suaves, tipografia
   variável, densidade confortável, dark mode de verdade. Sem "efeitos" que envelhecem
   rápido (glow neon, glassmorphism pesado, gradientes berrantes).

### Personalidade (se o app fosse uma pessoa)

> Organizado, direto e discreto. Fala pouco e no ponto. Não usa CAIXA ALTA para gritar —
> usa negrito só quando importa. Gosta de números redondos e margens generosas. Passa a
> sensação de "está tudo sob controle".

---

## Princípios de UX financeiro (específicos do domínio)

Estes princípios são o "porquê" das decisões nos docs de tela.

### P1 — Um número, um significado, uma cor
Entrada de dinheiro, saída de dinheiro e saldo têm **sempre** o mesmo tratamento em todo
o app. Verde = entrou. Vermelho/âmbar = saiu. Neutro = informativo. Definido em tokens
(ver 03) e encapsulado no `MoneyText` (ver 05) — nenhuma tela decide cor de moeda na mão.
Isso, sozinho, resolve o bug do "tudo verde".

### P2 — Mostre a resposta, não os ingredientes
O usuário quer a **conclusão**: "sobram R$ 2.104 este mês", "você está 12% acima do
orçamento", "você deve R$ 80 à Bia". Cálculos e detalhes ficam a um toque de distância,
não na cara. No lugar de 4 cartões de números crus, um enunciado + o número + a tendência.

### P3 — Progressive disclosure é a regra, não a exceção
O caminho simples é o padrão visível; o poder mora atrás de "Opções avançadas",
_expand_, aba secundária ou detalhe. Já fazemos isso muito bem no form de despesa — é o
padrão a espalhar. Complexidade sob demanda = "sem muita complexidade" para quem só quer
o básico, sem perder recurso para quem quer tudo.

### P4 — A lista é a interface
Num app financeiro, o usuário passa mais tempo lendo **listas** (extrato, faturas,
parcelas, acertos) do que gráficos. Investir no _ledger_ perfeito (agrupamento por dia,
glifo de categoria, valor tabular à direita, densidade certa, hover/expand) rende mais do
que qualquer widget novo.

### P5 — Contexto temporal sempre visível
Finanças são mês a mês. O seletor de período (mês atual / anterior / range) é um cidadão
de primeira classe, ancorado e consistente entre Início, Relatórios, Dívidas e Faturas —
não um `<Select>` perdido no meio de uma tabela.

### P6 — Estados vazios que ensinam
Todo estado vazio é uma oportunidade de _onboarding_. "Nenhuma transação" vira "Registre
seu primeiro gasto" com um botão. "Nenhum cartão" explica o que um cartão desbloqueia
(faturas, limite). Um empty state = 1 frase + 1 ação primária + (opcional) ilustração leve.

### P7 — Respeite o dinheiro do usuário com precisão
Centavos, arredondamento e divisão já são tratados com rigor no back-end (Money em
centavos, ADRs). O front deve **honrar** isso: nunca formatar float solto, sempre tabular,
sempre pt-BR, sinais explícitos.

---

## Direção visual (o "mood")

Detalhes concretos e valores estão no [`03-design-system.md`](03-design-system.md). Aqui,
a intenção:

- **Neutros levemente quentes** no lugar do branco/preto puro. Um fundo `#FAFAF9`-ish
  (não `#FFFFFF` estéril) e superfícies com um leve degrau de tom. Passa "papel", não
  "laboratório".
- **Uma cor de marca estável** nos dois temas — proposta: um **verde-esmeralda profundo /
  teal** (confiança + dinheiro, sem ser clichê de banco azul) OU um **índigo sóbrio**. A
  marca aparece em: logo, item de nav ativo, botão primário, links, foco. **Não** em toda
  borda de cartão.
- **Semânticas de dinheiro** separadas da marca: verde de "entrada" ≠ verde da marca
  (para não confundir), vermelho/âmbar de "saída" calibrados para AA.
- **Tipografia**: manter **Geist** (excelente, variável), mas usar a variante de números
  tabulares e uma escala de pesos contida (Regular/Medium/Semibold; Bold reservado a
  números-herói). Abolir `font-black` + `uppercase` como padrão.
- **Profundidade**: borda de 1px em `border`/`ring` sutil + no máximo **uma** sombra suave
  para elementos flutuantes (dropdown, dialog, toast). Nada de `shadow-primary/20` em
  cartões estáticos.
- **Raio**: uma escala só, cantos suaves (12–16px em cartões, 8–10px em inputs/botões).
- **Densidade**: confortável no desktop, com uma variante compacta para tabelas densas.
- **Movimento**: 120–200ms, `ease-out`, só em entrada de conteúdo e feedback. Respeitar
  `prefers-reduced-motion`. Sem animação de hover que "pula".
- **Ilustração/ícones**: lucere-react como está; ilustrações de empty state minimalistas
  e monocromáticas (na cor de marca a 10–20%).

### Referências de _padrão_ (não copiar marca, capturar o espírito)

- **Ledger/extrato editorial**: apps como Copilot Money, Monarch, Lunch Money — números
  como protagonistas, listas caprichadas, densidade calma.
- **Herói de saldo com "safe-to-spend"**: a ideia de mostrar "quanto pode gastar" em vez
  de só "quanto gastou".
- **Tabular financeiro**: relatórios de bancos digitais com tipografia tabular e cor
  semântica contida.

O que **NÃO** perseguir: dashboards cripto (neon, glow), glassmorphism pesado, "bento"
colorido de template, skeUEUomorfismo de cofrinho.

---

## Anti-objetivos (o que este redesign explicitamente evita)

- ❌ **Não** adicionar complexidade nova de fluxo. Menos cliques, não mais.
- ❌ **Não** trocar o stack nem introduzir uma UI lib nova "da moda". A base atual
  (Tailwind + Radix) chega lá; consolidamos, não trocamos (ver 03/05).
- ❌ **Não** encher de gráficos. Gráfico só onde conta uma história que a lista não conta.
- ❌ **Não** "gamificar" finanças (medalhas, confete). Um app sério, não um joguinho.
  (O único emoji hoje, o 🎉 do "não deve nada", pode ficar — é simpático e pontual.)
- ❌ **Não** esconder poder atrás de minimalismo cego. Progressive disclosure ≠ remover
  recursos. Tudo que existe continua acessível.

---

## Critérios de sucesso (como saberemos que deu certo)

1. **Teste dos 2 segundos**: abrir o Início e responder "quanto sobra e o que gastei por
   último" sem pensar.
2. **Teste da cor**: percorrer o extrato e nunca confundir entrada com saída.
3. **Teste do mobile**: registrar uma despesa inteira pelo celular, confortável.
4. **Teste da consistência**: qualquer valor monetário, em qualquer tela, no mesmo
   formato e com a mesma semântica de cor.
5. **Teste do "não é template"**: um usuário descreve o app como "limpo/confiável/
   caprichado", não como "mais um dashboard".
6. **Teste do tema**: claro e escuro igualmente cuidados, sem elemento quebrado.
