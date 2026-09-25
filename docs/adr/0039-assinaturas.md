# ADR 0039 — Assinatura é uma recorrência marcada, com plano, teste grátis e o custo por mês

**Status:** aceito (2026-09-25)
**Relacionado:** [0012](0012-recorrencia-com-snapshot-e-meses-de-calendario.md) e [0030](0030-recorrencia-revisada-e-com-fim.md)
(recorrência), [0038](0038-estabelecimento.md) (estabelecimento), [0035](0035-integracao-com-agentes-de-ia-mcp.md) (MCP)

## Contexto

Netflix, academia, domínio, software: a pergunta "quanto eu pago de assinaturas por
mês?" não tinha resposta. A tela de recorrências somava tudo o que se repete,
aluguel junto com streaming, e nada dizia quando um teste grátis ia virar cobrança.

Uma assinatura já é quase inteira uma recorrência: valor, frequência, próxima
cobrança, cartão, divisão. O que falta é pouco, e duplicar o resto num modelo novo
criaria duas verdades sobre quando se paga.

## Decisão

1. **Assinatura é uma recorrência marcada** (`RecurringExpense.is_subscription`), com
   três campos opcionais: `plan` ("Premium Família"), `trial_ends_on` (fim do teste
   grátis) e `notes` (benefícios). As `notes` não vão para as ocorrências; a
   `description` continua indo.
2. **O que já existe não ganha coluna:**
   - o período e a renovação são a frequência e a próxima ocorrência;
   - o provedor é o estabelecimento (`merchant_id`, ADR 0038). A recorrência nova sem
     estabelecimento escolhido se liga ao de apelido igual ao título, como o
     lançamento novo. Pelo nome (`merchant_name`), acha ou cria.
3. **Teste grátis sem início declarado:** a primeira cobrança é no fim do teste
   (`start_date = trial_ends_on`), e nada nasce cobrado antes dele.
4. **Custo por mês calculado no servidor** (`RecurringService.monthly_equivalent`):
   - anual ÷ 12, semanal × 52 ÷ 12, diária × 365 ÷ 12;
   - "a cada N" divide por N;
   - centavos com arredondamento half-up.

   A leitura traz `monthly_equivalent` (cheio) e `my_monthly_equivalent` (a sua
   parte, pela divisão de cada ocorrência, o mesmo cálculo da materialização), além
   de `next_occurrence`. A tela e o agente somam com esses números. A cópia da conta
   que a tela tinha saiu, porque divergiria no arredondamento.
5. **Esquema:** colunas opcionais em `recurringexpense` (`is_subscription` com padrão
   falso). Sem tabela nova.

## Tela

- Recorrência › quadro **Assinaturas**:
  - a sua parte por mês, somada por moeda, com o valor cheio nomeado;
  - cada assinatura com o plano, a próxima cobrança e "teste grátis até…".
- Selo "Assinatura" na lista e o recorte "Só assinaturas".
- No formulário:
  - Estabelecimento, com os do espaço como sugestão;
  - "É uma assinatura", com plano, fim do teste e benefícios. Desmarcar apaga os
    três.

## MCP

- `recurring_create`/`_update` ganham `subscription`, `plan`, `trial_ends_on`,
  `notes` e `merchant`.
  - `plan` ou `trial_ends_on` já implicam assinatura.
  - Na edição, `""` apaga o plano e as notas, e `merchant: ""` desvincula.
  - Provedor com nome parecido volta AMBIGUOUS, como no lançamento.
  - Renda recorrente recusa esses campos.
- `recurring_list` ganha `subscriptions_only`, e cada item traz `subscription`,
  `merchant` e `my_monthly`. O total `monthly_my_share` passa a usar a mesma conta
  do servidor.
- O componente separa as assinaturas num grupo com o total por mês e mostra plano,
  teste grátis e benefícios.

## Consequências

- Não há aviso ativo de fim de teste (notificação). O dado existe e a tela o
  destaca; o aviso pode reaproveitar o do [ADR 0033](0033-aviso-de-vencimento.md) depois.
- A assinatura de um espaço é do espaço, como toda recorrência: "minhas
  assinaturas" em todos os espaços é a lista do agente (`recurring_list` sem
  espaço), não uma tela nova.
