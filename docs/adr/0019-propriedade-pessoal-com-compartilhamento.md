# ADR 0019 — O que é da pessoa pertence à pessoa; ao workspace, só por escolha

**Status:** ~~aceito~~ **superseded** por [0021](0021-recurso-pessoal-sem-workspace.md) (2026-07-30)

> O diagnóstico deste ADR está certo — renda, cartão, conta e financiamento são
> da pessoa. O remédio não: manter o recurso ancorado num workspace e estendê-lo
> por tabelas de vínculo produziu um vazamento (o nível `use` nunca chegou a ser
> consultado, e todo cartão compartilhado entregava limite e fatura inteira) e um
> recurso que ainda assim não podia ser usado no destino. O ADR 0021 remove o
> `workspace_id` desses domínios.
**Relacionado:** [0006](0006-moeda-base-brl-sem-soma-mista.md) (moeda-base),
[0015](0015-conversao-na-entrada-e-taxa-cruzada.md) (conversão na entrada),
[0018](0018-privacidade-papel-e-acesso-financeiro.md) (privacidade),
[0020](0020-visao-global-e-quatro-numeros.md) (visão global)

## Contexto

Todo o domínio financeiro nascia com `workspace_id NOT NULL`. Em consequência,
**salário pertencia a um espaço de colaboração**, o que é falso: renda é de quem
recebe. O relato do dono foi direto — *"a renda não está global; criei um novo
workspace e não contou"*. Duas causas somadas:

1. `Income.workspace_id` era obrigatório, então cada workspace via só as rendas
   cadastradas nele;
2. `ReportService.get_summary` calculava `my_income` com
   `.where(Income.workspace_id == workspace_id)` — mesmo o dado existindo, o
   recorte pessoal o escondia.

O custo prático: quem participa de duas casas cadastra o mesmo salário duas
vezes, e as cópias divergem na primeira correção. Pior no caminho recorrente — a
materialização preguiçosa era escopada por workspace e o curto-circuito
`_tem_template_ativo` devolvia `False` num workspace recém-criado (ele não tem
template nenhum), então o salário global nunca era gerado ali.

O mesmo vale para cartão, conta de pagamento e financiamento. Usar o mesmo cartão
em dois workspaces exigia dois cadastros, **cada um gerando a sua fatura** — a
mesma dívida contada duas vezes no Endividamento e na Previsão.

## Decisão

Recurso pessoal deixa de pertencer a um workspace e passa a **pertencer à
pessoa**, com compartilhamento explícito para os workspaces dela.

1. **`workspace_id` anulável** em `Income` e `RecurringIncome`. `NULL` = pessoal
   (global, aparece em todos os meus workspaces); preenchido = renda **da casa**
   (aluguel de imóvel compartilhado, receita conjunta). O default de criação é
   pessoal, porque é a verdade do caso comum.

2. **`my_income` deixa de filtrar por workspace.** A identidade da renda passa a
   ser só `Income.user_id`, e o mesmo salário aparece em todas as minhas casas.

3. **Global para MIM ≠ público para a casa.** Uma tabela de vínculo por domínio
   (`IncomeWorkspaceShare`, `RecurringIncomeWorkspaceShare`,
   `CardWorkspaceAccess`, `PaymentAccountWorkspaceShare`,
   `FinancingWorkspaceShare`) diz a quais orçamentos o recurso CONTRIBUI. Vazio é
   privado. Sem essa separação, tornar a renda global teria transformado "meu
   salário me acompanha" em "meu salário entra no orçamento de toda casa de que
   participo" — o vazamento do ADR 0018 reaberto por outra porta.

4. **A lista enviada é o estado final.** Revogar é a mesma operação de
   compartilhar, sem endpoint extra — e só com workspaces de que o usuário
   participa, senão um id arbitrário no corpo colocaria minha renda no orçamento
   de um desconhecido.

5. **O template propaga.** Cada ocorrência materializada de uma renda recorrente
   herda os compartilhamentos do template; senão compartilhar um salário valeria
   só para o mês do gesto, numa renda que por definição se repete.

6. **`CardWorkspaceAccess.access` separa usar de devassar.** Com `use`, o
   workspace lança compras no cartão e vê o subtotal DELE; limite e fatura
   inteira continuam do dono. É a granularidade que faltava no ADR 0018, em que
   enxergar o cartão (por ter uma compra nele) trazia o limite junto.

7. **Moeda do que é pessoal: `User.report_currency`.** O que não tem workspace não
   tem moeda-base de onde herdar. Converter pela base de quem por acaso disparou a
   leitura faria o MESMO salário valer números diferentes conforme a tela aberta.
   Renda **da casa** continua convertendo pela base do workspace (ADR 0015).

8. **Admin não manda em renda pessoal alheia.** Ele administra a casa, não o
   salário de quem mora nela. Renda da casa (`scope="workspace"`) continua sob a
   alçada dele.

## Consequências

- Migração `e1c9b482f57a` cria as tabelas de renda, torna as colunas anuláveis e
  **converte as rendas existentes em pessoais compartilhadas com o workspace de
  origem** — nessa ordem, porque é do `workspace_id` que sai o destino do
  compartilhamento; invertida, a informação se perderia. O dono passa a ver a
  própria renda em todos os workspaces (o que ele pediu) e nenhum total de casa
  muda (o compartilhamento repõe exatamente a visibilidade que a coluna dava).
  Deixar como estava faria a correção não valer para os dados que já existem —
  justamente os de quem reclamou.
- Migração `f3a7d21e08b4` cria os vínculos de cartão/conta/financiamento **sem
  backfill**: compartilhar é ato explícito, e semear vínculos ofereceria dados de
  uma pessoa a workspaces que ela nunca escolheu.
- O `downgrade` da renda devolve cada linha ao workspace com que está
  compartilhada (menor id quando há vários) e **apaga a renda pessoal nunca
  compartilhada**, que não tem para onde voltar sob `NOT NULL`. É perda assumida:
  desfazer "renda é da pessoa" custa as rendas que só existiam por serem dela.
- `_tem_template_ativo` e `generate_due_income` passam a receber `user_id`, e as
  quatro rotas de leitura que materializam o repassam. Sem isso, o salário global
  continuaria invisível em workspace novo — o sintoma original.
- Fica de fora, conscientemente: o cartão continua morando num workspace
  (`CreditCard.workspace_id` segue `NOT NULL`) e o compartilhamento estende o
  alcance. Torná-lo anulável exigiria mexer em `CardStatement`, roteamento de
  fatura e importação, por um ganho que o vínculo já entrega.
