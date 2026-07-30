# ADR 0020 — Início é global e pessoal; o workspace vive na URL

**Status:** aceito (2026-07-30)
**Relacionado:** [0006](0006-moeda-base-brl-sem-soma-mista.md) (moeda-base),
[0017](0017-orcamento-com-escopo-casa-ou-pessoal.md) (orçamento com escopo),
[0018](0018-privacidade-papel-e-acesso-financeiro.md) (privacidade),
[0019](0019-propriedade-pessoal-com-compartilhamento.md) (propriedade pessoal)

## Contexto

**O Início era a dashboard de um workspace disfarçada de tela pessoal.** Lia o
`currentWorkspaceId` guardado no `localStorage` e misturava duas perspectivas na
mesma tela: "minha parte" (`my_income`, `my_expenses`) ao lado de "Últimos
lançamentos" do workspace inteiro. Quem participa de duas casas não tinha onde
perguntar *"quanto eu ganhei, consumi e tenho a pagar no total?"*.

O workspace fora da URL cobrava caro:

- link compartilhado abria na casa de quem clicou, não na de quem mandou;
- duas abas disputavam a MESMA chave de `localStorage` — trocar de workspace numa
  mexia na outra, e a despesa ia parar na casa errada;
- o botão "voltar" não voltava para o workspace anterior, porque a troca nunca
  entrou no histórico;
- o id ficava guardado para sempre: quem fosse removido de um workspace seguia
  com o app apontado para ele, num ciclo de 403 sem explicação.

Havia ainda uma confusão de vocabulário que o produto herdou:

- **"Seu saldo"** era renda menos consumo do PERÍODO — resultado, não saldo
  bancário. O nome ensinava a pessoa a ler o número errado.
- **"Dívidas"** (entre membros, resolvida com uma transferência) e
  **"Endividamento"** (com bancos e cartões, resolvido pagando a fatura) são
  eixos diferentes com nomes quase iguais.
- E faltava um número: **quanto efetivamente saiu do meu bolso**. O app só sabia
  falar de consumo, então não havia como dizer "adiantei 600 e tenho a receber".

## Decisão

**Duas camadas explícitas**, e o escopo visível na URL.

### 1. Quatro números, nomeados pelo que são

| Número | Fórmula | Pergunta |
|---|---|---|
| **Consumo** | Σ dos meus `TransactionSplit` | quanto do gasto foi meu |
| **Saída de caixa** | Σ dos meus `TransactionPayer` | quanto saiu do meu bolso |
| **A pagar / a receber** | consumo − caixa, por workspace | quanto acerto, e com quem |
| **Resultado do mês** | renda − **consumo** | sobrou ou faltou |

O resultado desconta o CONSUMO, não a saída de caixa: adiantar dinheiro por outra
pessoa não é gasto meu, é crédito a receber. Descontando o caixa, quem paga a
conta do restaurante e é reembolsado apareceria no vermelho todo mês.

### 2. `/me/*` — rotas pessoais, sem workspace no caminho

O gate é só `get_current_user`. Cada consulta filtra por `user_id`, e a agregação
varre os workspaces de que ele participa. É o único grupo de hooks do app sem
`workspaceId` na query key, e de propósito.

**Saldos não se compensam entre workspaces.** Dever 100 na casa e ter 100 a
receber no rateio da viagem não é estar quitado: são pessoas e acordos diferentes.
`by_workspace` mantém as pontas separadas; o total é informativo.

**Moeda:** somar casas com bases diferentes viola o ADR 0006. O destino é
`User.report_currency`, e o que não converte fica de fora com contagem — mesma
política do `excluded_foreign_count`.

### 3. `/w/:workspaceId/*` — o workspace na URL

Um `WorkspaceGuard` confere que o id é de um workspace de que o usuário participa
antes de qualquer tela montar, e mantém o "último visitado" em dia.

O que tornou isso viável sem reescrever 29 arquivos foi **um ponto único de
indireção**: `useWorkspaceId()` lê `useParams()`, e cada um dos 22 hooks de dados
trocou `useUIStore()` por ele numa linha. As query keys, os guards `enabled` e o
contrato de `lib/ws-events.ts` ficaram idênticos.

`/` leva ao Início global. As rotas antigas (`/transactions`, `/income`, …)
redirecionam para o último workspace, para link velho e favorito continuarem
funcionando.

### 4. Renomeações

- "Seu saldo" → **"Resultado do mês"**
- "Dívidas" → **"Acertos entre pessoas"**
- "Endividamento" → **"Compromissos financeiros"**

## Consequências

- `User.report_currency` (migração `e1c9b482f57a`, junto do ADR 0019).
- O Início global é **só leitura**: lançar despesa é ato de UM workspace, então o
  botão não mora lá. Cada linha de workspace leva ao painel dela. Colocar um
  "Nova despesa" na tela global reintroduziria a ambiguidade que a onda combate —
  lançar num workspace invisível.
- `switchWorkspace` NÃO navega: navegação é decisão de quem chama. Embutir
  `useNavigate` no hook obrigaria todo consumidor — inclusive `useBaseCurrency`,
  usado em componentes testados isoladamente — a existir dentro de um `<Router>`.
  `workspacePath()` monta o destino preservando a subrota, para quem está em
  Lançamentos continuar em Lançamentos na casa nova.
- A store guarda o primeiro workspace quando está vazia; sem isso, quem acabou de
  se cadastrar cairia em `/overview` com a barra lateral só com a camada global,
  sem caminho para a própria casa.
- `set_report_currency` é a única rota mutante sem evento de tempo real, e está na
  lista de exceções do `test_ws_event_contract`: é ajuste pessoal e o canal é por
  sala de workspace — não há para quem transmitir.
- Fica de fora, conscientemente: `/me/income` e `/me/cards` como telas próprias.
  A renda já é global e aparece na tela de Rendas de qualquer workspace (ADR
  0019), então a tela dedicada é organização, não capacidade.
