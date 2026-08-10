# Architecture Decision Records (ADRs)

Cada ADR registra **uma decisão** relevante do projeto: o contexto, a decisão tomada e as consequências. Servem para não re-discutir o que já foi decidido e para explicar *por que* o código é como é. São imutáveis — uma decisão que muda vira um novo ADR que supersede o anterior.

## Índice

| # | Decisão | Tema |
|---|---|---|
| [0001](0001-alocacao-monetaria-em-centavos.md) | Alocação monetária em centavos, resto aos primeiros participantes | Integridade de dinheiro |
| [0002](0002-statement-id-derivado-no-servidor.md) | `statement_id` é exclusivamente derivado no servidor | Segurança / faturas |
| [0003](0003-politica-de-status-financeiros.md) | Política de status e imutabilidade de despesa paga | Máquina de estados |
| [0004](0004-origem-de-pagamento-por-pagador.md) | Origem do pagamento é por pagador, não global | Modelo de pagamento |
| [0005](0005-alembic-unica-interface-de-schema.md) | Alembic é a única interface de evolução de schema | Migrações |
| [0006](0006-moeda-base-brl-sem-soma-mista.md) | Moeda-base por workspace; sem soma de moedas diferentes | Consultas / moeda |
| [0007](0007-anexos-fora-do-banco-com-hash.md) | Anexos: metadados + hash no banco; conteúdo fora do banco em prod | Anexos |
| [0008](0008-importacao-em-lote-auditavel.md) | Importação CSV em lote auditável, decisão por linha | Importação |
| [0009](0009-acertos-sem-sobrepagamento.md) | Acertos sem sobrepagamento; terceiros só admin+ | Dívidas |
| [0010](0010-commit-unico-por-request.md) | Serviços fazem `flush()`; commit único na rota | Transações |
| [0011](0011-ciclo-de-fatura-e-pagamento.md) | Ciclo da fatura (aberta→fechada→paga) e pagamento fora da Transaction | Cartões |
| [0012](0012-recorrencia-com-snapshot-e-meses-de-calendario.md) | Recorrência materializa despesa completa; meses de calendário | Recorrência |
| [0013](0013-sessoes-de-refresh-e-hardening-de-producao.md) | Sessões de refresh persistidas e hardening de produção | Segurança |
| [0014](0014-consultas-moeda-e-experiencia.md) | Consultas financeiras, moeda-base e experiência | Relatórios / UX |
| [0015](0015-conversao-na-entrada-e-taxa-cruzada.md) | Conversão na entrada pela taxa cruzada da moeda-base (supersede 0006) | Consultas / moeda |
| [0016](0016-armazenamento-de-anexos-em-volume.md) | Armazenamento de anexos em volume: endereçado por conteúdo, com dedup (implementa 0007) | Anexos |
| [0017](0017-orcamento-com-escopo-casa-ou-pessoal.md) | Orçamento tem escopo: meta da casa ou meta pessoal (privada) | Orçamento / UX |
| [0018](0018-privacidade-papel-e-acesso-financeiro.md) | Papel (o que faço) separado de acesso financeiro (o que vejo); invisível responde 404 | Privacidade / segurança |
| [0019](0019-propriedade-pessoal-com-compartilhamento.md) | ~~Renda/cartão/conta/financiamento são da PESSOA; workspace só por compartilhamento explícito~~ (superseded por 0021) | Propriedade / privacidade |
| [0020](0020-visao-global-e-quatro-numeros.md) | Início global e pessoal; consumo × caixa × a pagar × resultado; workspace na URL | Informação / navegação |
| [0021](0021-recurso-pessoal-sem-workspace.md) | Recurso pessoal não tem `workspace_id`; acesso financeiro completo não o alcança (supersede 0019) | Propriedade / privacidade |
| [0022](0022-caixa-efetivo.md) | Caixa é quando o dinheiro se move; o `cash_out` antigo vira `paid_in_transactions` | Relatórios / caixa |
| [0023](0023-saldo-de-fatura-arquivo-e-data-efetiva.md) | Fatura tem saldo cumulativo; arquivar preserva o histórico; caixa converte pela data efetiva e o app tem um fuso único | Integridade financeira |
| [0024](0024-fatura-na-moeda-do-cartao.md) | Fatura é denominada na moeda do CARTÃO; o lançamento tem perna contábil e perna de fatura | Cartões / moeda |
| [0025](0025-data-civil-e-instante.md) | Data civil vira instante ancorado ao MEIO-DIA local (`civil_instant`), par de `local_day` | Datas / fuso |

## Escrevendo um novo ADR

1. Crie `docs/adr/NNNN-titulo-curto.md` (próximo número disponível).
2. Estrutura: **título** (a decisão em uma frase), **contexto** (o problema/força), **decisão** (o que foi escolhido), **consequências** (o que muda e o que fica de fora).
3. Se substituir um ADR anterior, referencie-o e marque o antigo como *superseded*.
