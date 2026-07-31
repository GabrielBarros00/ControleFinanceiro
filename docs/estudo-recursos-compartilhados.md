# Estudo — compartilhar recursos entre pessoas (co-propriedade)

**Status:** estudo, não implementado. Nada aqui existe no código.
**Origem:** pedido do dono na Onda 5 — *"um ponto de melhoria é uma opção de
compartilhar os «recursos», como um casal que divide tudo mas utiliza contas
separadas. Por padrão deve ser considerado uso individual. Mas deve ser estudado
para implementar essa forma, para compartilhar as coisas. O casal poder ter
cartões, rendas, tudo compartilhado, seja em 1 workspace ou global."*
**Relacionado:** [ADR 0021](adr/0021-recurso-pessoal-sem-workspace.md)

## Por que a tentativa anterior falhou

O ADR 0019 já tinha tentado compartilhar cartão, conta, financiamento e renda. A
implementação vazou dados e não permitia usar o recurso compartilhado, e é
tentador atribuir isso a bugs — `card_full_access_here()` sem chamador, o `400`
de `card.workspace_id != workspace_id`. Foram bugs, mas o motivo de eles serem
tão fáceis de cometer é de **modelagem**:

> O vínculo era `recurso → workspace`. A pergunta que o usuário faz é
> `recurso → pessoa`.

As consequências disso encadeavam:

1. **O nível de acesso não tinha onde ser respeitado.** Um cartão "compartilhado
   com o workspace X" é visível a todos de X, então `use` × `full` teria de ser
   verificado em cada leitura, uma a uma. Uma esquecida vaza — e foi o que houve,
   em todas.
2. **A unidade errada.** Ninguém quer dar o cartão "para a Casa". Quer dar para o
   Bruno. Se o Bruno sair do workspace, o acesso deveria acabar; se ele entrar
   noutro workspace comum, deveria continuar. Vínculo por espaço não expressa
   nenhuma das duas coisas.
3. **Sem co-propriedade não há rateio.** Renda "da casa" era creditada 100% a
   quem cadastrou, porque não havia onde dizer que 50% é da outra pessoa.

## O modelo proposto: co-proprietários

Uma tabela de vínculo por domínio, ligando **recurso a PESSOA** — nunca a
workspace:

```
CardCoOwner(card_id, user_id, access, share_bp)
AccountCoOwner(account_id, user_id, access, share_bp)
IncomeCoOwner(income_id, user_id, share_bp)
FinancingCoOwner(financing_id, user_id, access, share_bp)
```

- **`access`**: `use` (lançar e ver o próprio subtotal) ou `full` (limite, fatura
  inteira, ciclo). O dono original é sempre `full` e não é removível.
- **`share_bp`**: participação em **pontos-base** (1/10.000), para renda e
  financiamento. Inteiro, não decimal — é a mesma escolha do ADR 0001 para
  dinheiro, e pela mesma razão: fração binária não fecha soma.

A regra de leitura vira uma só, e é a que faltava:

```python
def personal_scope(column, user_id, *, min_access=None):
    """Meu, ou co-meu com acesso suficiente."""
```

Nenhum endpoint decide nível de acesso por conta própria; ele declara o mínimo
que precisa (`full` para fatura e limite, `use` para o seletor do formulário) e
a política responde. É o que impede o retorno do `card_full_access_here()` órfão.

## O que precisa ser resolvido junto

Estas são as perguntas em aberto — não detalhes de implementação:

1. **Rateio de renda.** `share_bp` distribui a renda entre co-proprietários, e a
   soma tem de fechar 10.000 exatos. O rateio em centavos usa
   `_allocate_proportional` (piso + resto de 1 centavo por vez), o mesmo do ADR
   0001. `/me/overview` passa a somar **a fatia** de cada um, não o valor cheio.

2. **Quem fecha a fatura?** Um cartão com dois `full` tem duas pessoas podendo
   fechar, pagar e reabrir. Ou o ciclo continua sendo só do dono original (mais
   simples, e a co-propriedade vira "eu uso e vejo"), ou vira ação concorrente
   com trava — decisão do dono.

3. **Consentimento.** Compartilhar não pode ser unilateral: receber um
   financiamento no seu painel de Compromissos muda os SEUS números. O convite de
   co-propriedade precisa ser aceito, com a mesma mecânica do convite de
   workspace (ADR 0018 já tem o precedente de consentimento).

4. **Revogação e histórico.** Ao remover um co-proprietário, os lançamentos que
   ele já fez no cartão continuam existindo — são despesas reais de workspaces.
   O acesso acaba; o passado não é reescrito. A fatura antiga precisa continuar
   legível para o dono.

5. **Moeda.** Dois co-proprietários podem ter `report_currency` diferente. O
   recurso mantém a sua moeda e cada painel converte na leitura, com a política
   de exclusão do ADR 0006 — nunca uma conversão inventada.

## Ordem sugerida

1. **Conta e cartão com `access` e sem `share_bp`.** Resolve "usamos o mesmo
   cartão" sem tocar em rateio. É o caso que o dono descreveu primeiro.
2. **Renda com `share_bp`.** Exige o rateio e muda `/me/overview`; é a metade
   difícil e não deve vir junto.
3. **Financiamento.** O mais raro, e o que mais depende das decisões 2 e 4.

## O que continua valendo enquanto isso

O padrão é e continua sendo **individual** (ADR 0021). Um casal que divide tudo
hoje registra os gastos num workspace comum e usa o rateio de despesa, que já
existe e funciona — o que não dá para compartilhar é o **instrumento** (o cartão,
a conta), não o gasto.
