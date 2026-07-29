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

## Escrevendo um novo ADR

1. Crie `docs/adr/NNNN-titulo-curto.md` (próximo número disponível).
2. Estrutura: **título** (a decisão em uma frase), **contexto** (o problema/força), **decisão** (o que foi escolhido), **consequências** (o que muda e o que fica de fora).
3. Se substituir um ADR anterior, referencie-o e marque o antigo como *superseded*.
