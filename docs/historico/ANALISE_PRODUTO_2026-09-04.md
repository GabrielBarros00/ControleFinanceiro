# Análise de produto — tela a tela, ponto a ponto

**Data:** 2026-09-04 · **Base:** `fix/auditoria-ux` (PR #80, com os 38 achados de UX já corrigidos)
**Método:** o produto rodando, com dados semeados e com conta nova; catálogo de 129 capturas;
leitura do código de cada página; medições no DOM.

> Este documento é **diferente da auditoria**. Lá a pergunta era "o que está quebrado?".
> Aqui é **"o que este produto deveria ser?"** — e a resposta inclui remover coisas que
> funcionam. Onde eu proponho mudança grande, digo o custo e o risco; onde a decisão atual
> é boa, digo para não mexer.

---

# 1. A tese

O ControleFinanceiro V4 sabe fazer contas melhor do que sabe **contar uma história**.

A engenharia por baixo é séria: divisão por item em centavos, máquina de estados de fatura,
SAC/PRICE, acertos multi-membro, recorrência ancorada, conversão de moeda com PTAX. Cada
número tem um significado defendido, e a interface até explica esses significados com um
cuidado raro ("De qual mês é cada renda e cada gasto — independentemente de quando o
dinheiro se move").

O problema é que **ela explica tudo, o tempo todo, para todo mundo**. O app apresenta 20
itens de menu, ~14 números só na primeira tela e 14 controles para lançar um café de
R$ 12,50. Ele foi desenhado para responder toda pergunta que o modelo de dados permite
responder — e não para responder, primeiro e bem, as três perguntas que a pessoa faz todo
dia:

1. **Quanto eu tenho?**
2. **O que eu preciso pagar?**
3. **Onde foi meu dinheiro?**

A proposta deste documento é reorganizar o produto em torno dessas três perguntas, e tratar
o resto — competência × caixa, por espaço, por categoria, por método de divisão — como
**aprofundamento**, alcançável mas não imposto.

---

# 2. O achado que precisa de decisão hoje

**A projeção do "Seu mês" soma parcelas vencidas de meses passados e apresenta o resultado
como se fosse o fim deste mês.**

Reproduzido do zero, num cenário banal:

- conta com **R$ 10.000,00**;
- **um** financiamento de 240 parcelas que **começou há 12 meses** (o caso de quem cadastra
  um contrato que já existia);
- nenhuma parcela marcada como paga — que é o **estado natural**: o app gera o cronograma
  sozinho e marcar 12 parcelas passadas à mão não é algo que alguém faça.

O que a primeira tela do app diz:

| Campo | Mostra | Deveria mostrar |
|---|---|---|
| A pagar | **−R$ 43.140,00** ("obrigações conhecidas até o fim do mês") | ~R$ 3.595 (uma parcela) |
| Saldo projetado | **−R$ 33.140,00**, em vermelho | ~+R$ 6.400 |
| Detalhamento | "Parcelas de financiamento (12)" | (1) |

A causa está em `backend/app/services/projection_service.py:209`:

```python
.where(AmortizationInstallment.due_date <= fim_do_mes)   # sem piso inferior
```

Não há limite inferior, e "não paga" é o estado padrão de toda parcela gerada. Então
"até o fim do mês" quer dizer, na prática, **"desde o começo dos tempos"**.

Isso atravessa três telas: o "Seu mês" (saldo projetado), "Compromissos" (Vencido
−R$ 423.052,57 nos dados semeados, e "próxima parcela em 31/08/2025" — mais de um ano
atrás) e "Seus relatórios" (Caixa líquido).

**Por que isto é o primeiro item do documento:** um app de finanças que diz a alguém com
dinheiro no banco que ele vai fechar o mês R$ 33 mil negativo perde a confiança na primeira
tela, e nenhuma melhoria de layout compra essa confiança de volta.

**Correção proposta** (pequena, e é decisão de produto, não de código):

1. A projeção passa a considerar **de hoje até o fim do mês**. O que venceu antes é
   **atraso**, não previsão.
2. O vencido ganha linha própria, como "Contas a pagar" já faz ("Vencido" separado de "A
   vencer neste mês") — a tela ao lado já resolveu isto direito.
3. Para financiamento, oferecer **"marcar as parcelas anteriores como pagas"** em um toque
   ao cadastrar um contrato antigo. Sem isso, o dado nasce errado e o usuário não tem como
   saber por quê.

Está fora do escopo desta análise implementar — mas é o que eu faria antes de qualquer
redesenho.

---

# 3. O problema estrutural: o app tem duas cópias de si mesmo

A separação **Pessoal × Compartilhado** (ADR 0020/0021) está conceitualmente certa: renda é
da pessoa, despesa dividida é da casa. Mas a forma como ela chegou à interface foi
duplicando telas, e o resultado é um menu de **20 itens** com **quatro pares homônimos**:

| Pessoal | Compartilhado | A pergunta que os separa |
|---|---|---|
| Seus acertos | Acertos | "com quem eu me acerto" × "quem deve a quem nesta casa" |
| Seus relatórios | Relatórios | "renda × consumo meu" × "para onde foi o dinheiro da casa" |
| Contas a pagar | Contas a pagar | somando espaços × só deste espaço |
| Suas configurações | Configurações | perfil e senha × membros e categorias |

O projeto já gastou energia nomeando isso ("Seus acertos" × "Acertos") e os nomes
funcionam — mas eles tratam o sintoma. A causa é que **a mesma tela existe duas vezes,
variando um filtro**. E o app já tem o componente que expressa esse filtro: o
`ScopeSwitcher`, que a pessoa aprende no primeiro minuto.

**Proposta:** escopo vira **filtro dentro da tela**, não item de menu.

```
HOJE (20 itens)                        PROPOSTA (9 itens)
─────────────────────────────          ───────────────────────────
PESSOAL                                 Início
  Seu mês                               Contas a pagar     [Tudo ▾]
  Contas                                Lançamentos        [Tudo ▾]
  Contas a pagar                        Acertos            [Tudo ▾]
  Rendas                                Relatórios         [Tudo ▾]
  Cartões                               ─────
  Financiamentos                        Contas e cartões
  Compromissos                          Rendas e recorrência
  Seus acertos                          ─────
  Seus relatórios                       Configurações
  Extrato                               Administração (só admin)
  Suas configurações
COMPARTILHADO
  Painel · Lançamentos · Contas a pagar
  Recorrência · Relatórios · Acertos
  Importar · Configurações
SITE
  Administração
```

O seletor de escopo no topo de cada tela responde "estou vendo o quê?" — e ele já existe,
já está no lugar certo (topo da barra lateral no desktop, topo da tela no celular) e já é
entendido.

**Custo e risco (honestos):** é a mudança mais cara do documento. Mexe em rotas, em
`nav-items.ts`, no `WorkspaceGuard` e em todo link salvo. Contradiz a estrutura do ADR
0020, que foi decidida com motivo — então merece um ADR próprio explicando por que o eixo
continua existindo, só que como filtro. **Não é para fazer de imediato**; é para decidir
antes de investir em qualquer outra reorganização.

---

# 4. Proposta de estado-alvo

Três telas carregam o produto; o resto é aprofundamento.

**"Hoje"** (substitui "Seu mês" como primeira tela)
Responde as três perguntas, nessa ordem, em uma tela sem rolagem:
- **quanto eu tenho** — o saldo, um número;
- **o que preciso resolver** — vencidos e a vencer nos próximos 7 dias, com ação direta;
- **como está o mês** — uma linha: gastei X de Y previsto.
Tudo o mais vira link.

**"Lançamentos"** (o extrato unificado)
Hoje há três telas de linha do tempo — Lançamentos (competência, do espaço), Extrato
(caixa, global) e Contas a pagar (o que não saiu). São três recortes da mesma lista. Uma
tela com filtros (escopo, período, situação, origem) e **busca** resolve as três.

**"Acertos"**
Já é a melhor tela do produto. Só precisa absorver a versão pessoal como filtro.

---

# 5. Tela a tela

Legenda do veredito: **manter** · **ajustar** · **fundir** · **repensar**

---

## 5.1 Login, cadastro, esqueci a senha, redefinir

**Veredito: manter.**

1. A tela dividida (painel de marca à esquerda, formulário à direita) é sóbria e adequada.
2. A validação inline é exemplar: erro por campo, foco no primeiro inválido, mensagem em
   português direto.
3. **Falta "mostrar senha".** É o campo mais errado do mundo em celular, e o app pede senha
   duas vezes no cadastro.
4. No cadastro a 1366×768, a mensagem "A senha deve ter pelo menos 6 caracteres" quebra em
   duas linhas e cruza o divisor do cartão. Pequeno, mas é a primeira tela.
5. **Oportunidade:** o painel esquerdo é 50% da tela mostrando uma frase. Poderia mostrar o
   que o app faz (uma captura, três bullets) — é a única chance de explicar o produto a
   quem ainda não entrou.

---

## 5.2 Onboarding (modal de 3 passos)

**Veredito: repensar.**

1. Ele pede **renda** e **cartão** antes de a pessoa ver o app. São as duas coisas que menos
   importam no primeiro minuto — e a renda é o dado mais privado do sistema, pedido antes
   de qualquer confiança ter sido construída.
2. O que o app precisa saber para ser útil no minuto 1 é **quanto você tem hoje** (saldo de
   uma conta). É justamente o que ele **não** pergunta — e o resultado é o "Saldo ainda não
   configurado" que o usuário novo encontra na primeira tela.
3. Proposta: passo único — "Quanto você tem hoje, e onde?" — e o resto (renda, cartão)
   oferecido **em contexto**, quando a pessoa abrir Rendas ou Cartões pela primeira vez.
4. Já corrigido no PR #80: o botão travado agora se explica, há saída no passo 1, e a cor
   voltou para a marca.

---

## 5.3 "Seu mês" (`/overview`) — a primeira tela

**Veredito: repensar.** É a tela que mais precisa de decisão.

1. **Seis blocos, ~14 números.** Medido: **2.475px** de altura no celular com conta quase
   vazia, **3.064px** com dados reais. Três telas de rolagem para "como está meu mês".
2. **O mesmo número aparece três vezes.** "R$ 106.781,50" é o título de "Seu dinheiro", é o
   KPI "Saldo atual" logo abaixo, e é o topo da tela Contas. Dois deles a 300px de
   distância um do outro.
3. **"Saldo projetado" é a conta dos outros três KPIs** (atual + a receber − a pagar). De
   quatro números, um é repetição e outro é aritmética dos vizinhos. Dois bastam:
   **quanto tenho** e **quanto devo ter no fim do mês**.
4. **A lista de contas não pertence aqui.** Cinco linhas de saldo por conta duplicam a tela
   "Contas", que existe e é boa. Aqui basta o total com link.
5. **"Resultado do mês" e "Caixa do mês" são a mesma pergunta em dois regimes contábeis.**
   A distinção é real e a explicação é boa — mas ela é *avançada*. Numa primeira tela, dois
   quadros de quatro números cada que quase sempre contam a mesma história é carga
   cognitiva sem retorno. Um deles vira link para os Relatórios.
6. **Nada nesta tela é acionável.** Não há um botão. A tela que a pessoa abre todo dia não
   oferece nenhuma próxima ação — nem "lançar", nem "pagar", nem "conferir".
7. **A projeção mente** (seção 2).

**Proposta:** virar **"Hoje"**, com saldo, o que vence nos próximos dias (com ação) e uma
linha de mês. De seis blocos para três, e um botão.

---

## 5.4 Contas (`/me/accounts`)

**Veredito: ajustar.**

1. O aviso "**28 movimentos sem conta declarada não entram em saldo nenhum**" é o melhor
   texto do app: diz o fato, a consequência e a ação. Mas é **passivo** — não tem botão.
   Deveria abrir a lista dos 28 para resolver em lote. É a única tela onde o app admite que
   o próprio número está incompleto, e não oferece o conserto.
2. **Seis ações por conta**, todas em texto do mesmo peso: Extrato · Saldo inicial ·
   Ajustar · Tornar padrão · Desativar · 🗑. São 30 alvos numa tela com 5 contas, e nenhum
   é primário. "Extrato" fica; o resto vai para um menu "…".
3. **"desde 2026-07-06"** — data ISO crua, num app que formata tudo em pt-BR.
4. O total "Seu dinheiro" repete o "Seu mês" (ver 5.3.2).
5. Ordenação por criação; para "onde está meu dinheiro", ordenar por saldo é mais útil.

---

## 5.5 Contas a pagar (`/me/payables` e `/w/:id/payables`)

**Veredito: fundir** (as duas viram uma, com filtro de escopo) **e ajustar.**

1. É a tela **mais acionável do produto** e uma das melhores: agrupa por vencimento, tem
   caixa de seleção por linha, separa "Vencido" de "A vencer".
2. **Altura medida: 7.095px no celular** com dados reais — oito telas de rolagem, sem
   paginação e sem recolher. As seções deveriam nascer fechadas, exceto "Vencidas".
3. Os três KPIs no topo (Total em aberto · Vencido · A vencer) ocupam a primeira tela
   inteira no celular antes da primeira conta. Uma linha de resumo bastaria.
4. **A ação em lote existe** (caixas de seleção) mas o botão que a executa fica no fim da
   lista — a 7.000px de distância no celular.

---

## 5.6 Rendas (`/me/income`)

**Veredito: fundir com Recorrência.**

1. A tela tem **duas tabelas**: "Rendas do mês" e "Rendas recorrentes". A segunda é uma
   *regra*, não um lançamento — e o app tem uma tela inteira para regras (Recorrência), que
   só trata de despesas.
2. Proposta: **uma tela "Fixos"** com o que se repete (rendas e despesas recorrentes), e as
   rendas do mês passam a ser linhas do extrato, como qualquer movimento.
3. "Lançar pendentes" é um botão poderoso e opaco: não diz quantas nem quais. Deveria dizer
   "Lançar 3 pendentes" e mostrar o que vai criar.
4. O título da tabela ("Título · Quando · Valor · Ações") ocupa uma coluna estreita e o
   texto quebra em 3 linhas enquanto sobra espaço à direita.

---

## 5.7 Cartões (`/me/cards`)

**Veredito: manter, com um ajuste.**

1. Os cartões visuais são bonitos e legíveis, e "Disponível" como número principal é a
   escolha certa.
2. **A meta de cada cartão é inconsistente**: uns dizem "Fecha dia 10 · vence 18", outro só
   "Vence 07/10". Mesma informação, duas formas.
3. **Duas formas de criar cartão na mesma tela** ("+ Novo cartão" no topo e o cartão
   tracejado "Adicionar cartão"). Não é erro, mas é redundância visual num lugar apertado.
4. A fatura abaixo depende de selecionar um cartão, e a seleção é marcada por um anel
   discreto. Em 5 cartões, é fácil perder de vista qual está selecionado.

---

## 5.8 Financiamentos (`/me/financing`)

**Veredito: ajustar** (e é a tela mais afetada pela seção 2).

1. **O seletor é uma faixa de chips com o título inteiro do contrato.** No celular são
   ~330px de altura só para escolher qual financiamento ver. Um `select` resolve.
2. **"Excluir" é um botão de texto vermelho colado em "+ Novo Financiamento".** A ação
   destrutiva e a construtiva, lado a lado, com o mesmo peso. (Há confirmação nomeando o
   contrato — isso está certo.)
3. Os três KPIs usam rótulo em caixa alta e um estilo próprio, diferente do `StatTile` do
   resto do app.
4. **O cronograma é a razão da tela e fica abaixo de tudo.** Quem abre Financiamentos quer
   ver "quanto falta e quando acaba".

---

## 5.9 Compromissos (`/me/commitments`)

**Veredito: fundir em Contas a pagar.**

1. A distinção "instituição (banco) × conta do mês" é real, mas é **sutil demais para
   custar um item de menu**. Quem tem uma fatura e uma parcela para pagar não pensa "isso é
   compromisso, aquilo é conta a pagar".
2. **O número em destaque de cada linha é o valor TOTAL do contrato** (R$ 1.250.000 para o
   imóvel), numa tela chamada "a vencer". É a informação menos acionável possível ali —
   deveria ser a próxima parcela.
3. **"próxima em 31/08/2025"** — mais de um ano no passado (ver seção 2).
4. Proposta: virar um **filtro** em Contas a pagar ("só faturas e financiamentos").

---

## 5.10 Seus acertos / Acertos (`/me/settlements`, `/w/:id/debts`)

**Veredito: manter e fundir as duas.** É a melhor tela do produto.

1. As frases fazem o trabalho: "Bruno Nascimento Albuquerque deve R$ 437,25 a você", com
   "Registrar" ao lado. Isso é o que um app de dividir contas precisa dizer.
2. O bloco "Por que os saldos ficam separados por espaço?" é ensino embutido de altíssima
   qualidade — mas é **permanente**. Depois da terceira visita vira ruído. Deveria recolher
   após ser lido.
3. **"Você deve R$ 0,00"** ocupa metade da largura para dizer zero. Quando um lado é zero, o
   outro deveria ocupar a tela.
4. **"Abrir a casa"** — "casa" aqui, "espaço" em todo o resto. Mesma família do "workspace"
   que o PR #80 corrigiu.
5. As três abas (Resumo · Por mês · Histórico) estão certas e a aba vive na URL.

---

## 5.11 Seus relatórios / Relatórios (`/me/reports`, `/w/:id/reports`)

**Veredito: fundir as duas; ajustar.**

1. **"(ADR 0022)" aparece no subtítulo, para o usuário.** Referência interna de arquitetura
   vazando para a interface — o exemplo mais claro de texto escrito para quem programa.
2. As cores dos gráficos **contradizem a semântica do app**: no resto do produto verde é
   entrada e vermelho é saída; no gráfico, consumo é roxo e renda é verde. Cor como dado é
   defensável, mas aqui as duas séries são exatamente entrada e saída.
3. A legenda lista "Consumo" antes de "Renda" enquanto o título diz "Renda × consumo".
4. "Maior categoria: **Sem categoria**" é um resultado legítimo e uma resposta ruim. Quando
   a maior categoria é a ausência de categoria, a tela deveria convidar a categorizar.
5. Os quatro KPIs somam o mesmo problema da seção 2 no "Caixa líquido".

---

## 5.12 Extrato (`/me/ledger`)

**Veredito: promover a tela principal de lista** (absorvendo Lançamentos).

1. É a tabela mais bem construída do app: data, movimento, origem etiquetada, valor
   alinhado.
2. **Os 6 chips de origem não mostram estado.** Olhando a tela, não dá para saber se algum
   filtro está aplicado — todos parecem iguais.
3. **Não tem busca.** É a tela que mais precisa: todos os movimentos, de todos os espaços,
   de todos os tipos. "Onde foi aquele pagamento do dentista?" não tem resposta no app hoje.
4. **Não tem saldo acumulado por linha.** Num extrato, é o que responde "como cheguei aqui".
5. O `select` "Todos os cartões" ocupa uma linha inteira de largura total para um filtro
   secundário, enquanto os seis chips principais se espremem acima.

---

## 5.13 Lançamentos (`/w/:id/transactions`)

**Veredito: fundir no Extrato.**

1. Depois do PR #80 a linha está legível no celular e as ações têm alvo adequado.
2. É **a mesma lista do Extrato** com outro recorte (competência em vez de caixa, um espaço
   em vez de todos). Manter as duas obriga a pessoa a saber a diferença entre competência e
   caixa **para escolher em qual menu clicar** — decisão contábil na navegação.
3. O cabeçalho "50 lançamentos · saídas R$ 82.995,00" é ótimo e deveria existir no Extrato.
4. A busca agora vive na URL (PR #80) — falta ser global.

---

## 5.14 Painel do espaço (`/w/:id`)

**Veredito: repensar ou remover.**

1. Depois do PR #80 o vazio de 700×216px acabou e três lançamentos cabem acima da dobra.
2. Mas a tela continua sendo **um resumo de resumos**: quatro números que existem nos
   Relatórios e uma lista que existe em Lançamentos. Se o escopo virar filtro (seção 3),
   ela deixa de ter função própria.
3. **"Painel" não diz nada.** É o único título do app que não nomeia o que mostra. Se ficar,
   deveria chamar-se pelo nome do espaço.
4. "Sua parte no mês −R$ 1.212,50" e, uma linha abaixo, "Você gastou R$ 1.212,50 este mês":
   o mesmo número duas vezes no mesmo cartão.

---

## 5.15 Recorrência (`/w/:id/recurring`)

**Veredito: ajustar** (e fundir com Rendas recorrentes — ver 5.6).

1. **A tela não responde a própria pergunta.** Quem abre "gastos fixos" quer saber **quanto
   sai por mês de fixo**. Não há totalizador em lugar nenhum.
2. A coluna **"Ações" tem cabeçalho e nenhuma linha mostra ação** (aparecem no hover). Uma
   coluna vazia é pior que nenhuma.
3. **Todas as linhas dizem "ATIVO".** Uma coluna cujo valor é sempre o mesmo não informa —
   o status só deveria aparecer quando é exceção (pausado).
4. O "—" solitário sob cada descrição (o mesmo ruído que o PR #80 removeu do extrato, aqui
   com renderização própria).
5. "Valor Base" — Title Case e jargão. "Valor" basta.

---

## 5.16 Importar (`/w/:id/import`)

**Veredito: repensar.** É a tela mais árida do produto.

1. Pede **delimitador, separador decimal e formato de data em códigos strftime**
   (`%d/%m/%Y`) — e os **nomes das colunas digitados de cabeça**, antes de o arquivo ser
   lido.
2. O seletor de arquivo é o controle **nativo do navegador**, sem estilo e em inglês
   ("Choose File / No file chosen"), no meio de uma interface em português.
3. Correção incremental (sem o wizard completo, que o roadmap já diferiu): ler o cabeçalho
   ao escolher o arquivo, transformar as três "Coluna X" em `select`, e inferir delimitador
   e formato por amostragem.
4. O PR #80 já resolveu a parte que não podia esperar: os 7 campos sem rótulo acessível.

---

## 5.17 Configurações do espaço (`/w/:id/settings`)

**Veredito: ajustar.**

1. Depois do PR #80 a tela é legível em 768px e a exclusão exige digitar o nome.
2. **A aba "Auditoria" é poderosa e invisível.** É o registro de quem fez o quê — a
   funcionalidade que resolve briga entre pessoas — escondida na terceira aba de uma tela de
   configuração.
3. O interruptor "Controlar o pagamento das contas" muda o **significado de todo lançamento
   futuro** e vive no meio de nome e moeda. Merece destaque e uma explicação do antes/depois.
4. A Zona de perigo mistura "Sair do espaço" (reversível por convite) e "Excluir espaço"
   (irreversível para todos) com o mesmo peso visual.

---

## 5.18 Suas configurações (`/me/settings`)

**Veredito: manter.**

1. Estrutura clara, abas agora na URL (PR #80).
2. "Sair da conta" está dentro da lista de abas, com aparência de aba. É ação, não seção.
3. A aba "Convidar alguém" (convite de cadastro no site) fica ao lado de perfil e senha —
   ela é de plataforma, não de pessoa. Confunde com o convite para um espaço.

---

## 5.19 Administração (`/admin`)

**Veredito: manter.**

1. Bem organizada, seis abas com escopo claro, e o cuidado de não exibir dinheiro de
   ninguém está evidente.
2. A aba "Saúde" e a "Auditoria" são as mais valiosas e as duas últimas da fila.
3. Sem ações em lote: desativar cinco contas exige cinco confirmações.

---

## 5.20 Nova despesa (modal)

**Veredito: repensar.** É o formulário mais usado do app.

1. **14 controles visíveis** e 9 rótulos no caminho simples, medidos no celular, para
   lançar um café: título, valor, moeda, quem pagou, data, forma de pagamento, "já foi
   paga", tags, dividir com, opções avançadas, anexos.
2. Proposta: **título + valor + salvar**, e tudo o mais atrás de "detalhar". Quem divide
   conta, divide; quem só registra, registra em três toques. O app já sabe o pagador
   (você), a data (hoje) e o espaço (o atual).
3. Depois do PR #80 o botão está sempre visível, o Escape pergunta antes de descartar e o
   erro do servidor aparece sem perder o que foi digitado — a mecânica está boa; sobra a
   quantidade.
4. Falta **"salvar e lançar outro"**. Quem registra o dia inteiro de uma vez reabre o modal
   a cada linha.

---

## 5.21 Detalhe do lançamento (modal)

**Veredito: ajustar** — tem um defeito visual real.

1. **O botão de fechar cobre o valor.** Medido: o "×" ocupa x=870–910 e o valor
   "−R$ 486,20" vai de x=806 a x=898 — sobreposição confirmada no desktop **e** no celular.
2. O bloco "Fatura" (com o `statement_shift`) é excelente: explica o problema real do
   mundo — o banco processa a compra dias depois — e oferece a correção ali mesmo.
3. Falta **"Duplicar"**. Depois de olhar uma despesa parecida, repetir é a ação mais
   provável.

---

## 5.22 Barra inferior e gaveta "Mais" (celular)

**Veredito: manter.**

1. Quatro slots + FAB é a estrutura certa, e o PR #80 fez o "voltar" fechar a gaveta.
2. A gaveta lista **15 destinos** com cabeçalho de seção. Se o menu encolher (seção 3), ela
   deixa de precisar rolar.
3. O terceiro slot é "Cartões" — para a maioria, "Contas a pagar" seria mais usado.

---

## 5.23 Cabeçalho (dois sinos)

1. O PR #80 diferenciou os ícones, mas ainda são **dois botões de aviso lado a lado**.
   "Ativar avisos" é configuração, não notificação — poderia ser a primeira linha do painel
   do sino, não um segundo botão permanente.

---

# 6. Padrões transversais

1. **O vermelho perdeu força.** Quase todo número é despesa, então quase tudo é vermelho — e
   aí nada chama atenção. Eu reservaria vermelho para o que **exige ação** (vencido, meta
   estourada) e usaria neutro para gasto normal.
2. **Quatro estilos de KPI convivem:** `StatTile` (sentence case), os cartões de
   Financiamentos (caixa alta), a faixa de Acertos "Por mês" (caixa alta, três células) e
   blocos montados à mão. Um só componente.
3. **Números repetidos entre telas.** O saldo aparece 3×, "sua parte" 3× no Painel. Cada
   repetição é uma chance de os dois divergirem e de a pessoa reparar.
4. **Nenhum "desfazer".** Excluir tem confirmação, mas depois dela não há volta — mesmo com
   soft-delete no backend. Cinco segundos de "Desfazer" no toast eliminam o medo de errar.
5. **Nenhuma ação em lote fora de Contas a pagar.** Categorizar 28 lançamentos ou marcar 12
   parcelas exige 28 e 12 idas.
6. **O app não tem estado "vazio mas configurado".** Quem tem tudo em dia vê as mesmas
   telas com zeros, em vez de "está tudo certo".

---

# 7. Plano em ondas

| Onda | O que entra | Custo | Risco |
|---|---|---|---|
| **0 — Confiança** | Projeção só do que vence de hoje em diante; vencido em linha própria; "marcar parcelas anteriores como pagas" | Baixo | Baixo |
| **1 — Ruído** | Fechar o "×" sobre o valor; totalizador na Recorrência; coluna "Ações"/"ATIVO"; datas ISO; "(ADR 0022)"; "casa" → "espaço"; cores do gráfico | Baixo | Baixo |
| **2 — A primeira tela** | "Seu mês" vira "Hoje": saldo, o que vence, uma linha de mês, um botão | Médio | Médio |
| **3 — O formulário** | Nova despesa slim de verdade (título + valor + salvar); "salvar e lançar outro"; "Duplicar" no detalhe | Médio | Médio |
| **4 — Busca e desfazer** | Busca global; "Desfazer" nos toasts; ação em lote para categorizar | Médio | Baixo |
| **5 — A arquitetura** | Escopo vira filtro; fundir os 4 pares homônimos; Extrato absorve Lançamentos; Compromissos vira filtro | **Alto** | **Alto** — pede ADR |
| **6 — Onboarding** | Passo único ("quanto você tem hoje"); renda e cartão em contexto | Médio | Médio |

A ordem não é negociável nos dois primeiros: **enquanto a projeção mentir, melhorar o
layout dela é polir o número errado.**

---

# 8. O que NÃO mudar

- **Acertos "Por mês"** — frases em vez de tabela. É o padrão a copiar, não a mudar.
- **Os estados vazios.** Todos ensinam o próximo passo. Conferidos com conta nova nas 17
  rotas.
- **O tratamento de erro no formulário** — mensagem do servidor inline, dados preservados.
- **O bloco "Fatura" do detalhe** — modela um problema real do mundo e resolve ali.
- **O aviso de movimentos sem conta** — só falta a ação.
- **Os tokens de cor e o tema escuro.**
- **`useConfirm`, `useAcaoPendente`, os portões de largura e de teclado.**
- **A conversão de tabela em cartões no celular.**

---

# 9. O que eu NÃO recomendo

Para o plano não virar redesenho por moda:

1. **Não trocar a biblioteca de UI.** O F1.7 do roadmap (Base UI → Radix) é rework
   transversal com risco em toda tela, por ganho estético. As duas convenções que
   sobrevivem estão documentadas.
2. **Não adicionar gráficos.** O app já tem mais gráfico do que resposta. O que falta é
   busca, não visualização.
3. **Não perseguir densidade compacta.** As tabelas cabem.
4. **Não criar "dashboard configurável".** É a saída que todo produto usa para não decidir o
   que é importante — e decidir é o trabalho.
5. **Não mexer no vocabulário de novo.** "Pessoal × Compartilhado" e "espaço" estão certos e
   já custaram uma rodada. Se o escopo virar filtro, as palavras continuam valendo.

---

**Resumo em uma frase:** o produto está bem construído e mal priorizado — e a maior parte do
ganho está em **remover**, não em acrescentar. Começando por fazer a primeira tela dizer a
verdade.
