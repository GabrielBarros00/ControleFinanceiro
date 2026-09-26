# ADR 0040 — O item da nota tem medida: quantidade, unidade e preço unitário, conferidos com a tolerância da balança

**Status:** aceito (2026-09-26)
**Relacionado:** [0001](0001-alocacao-monetaria-em-centavos.md) (centavos), [0015](0015-conversao-na-entrada-e-taxa-cruzada.md)
(conversão na entrada), [0035](0035-integracao-com-agentes-de-ia-mcp.md) (MCP)

## Contexto

A auditoria de 2026-09-26 (achado C10) partiu de uma observação do dono: ao lançar
uma nota pela IA, cada item chegava só com o total da linha. As causas não eram só
de instrução — o sistema empurrava para isso:

- não havia **unidade**: "1,235" não dizia se era kg, litro ou unidade;
- o preço unitário tinha **2 casas**: o MCP recusava "5.899" (o litro de
  combustível) e o banco gravava 5,90 em silêncio pela API;
- a conferência exigia `total == ROUND_HALF_UP(qtd × unitário)` **exato**, e
  recusava a nota verdadeira de uma balança que trunca (1,235 kg × R$ 39,90 =
  R$ 49,27);
- a tela calculava a linha em ponto flutuante e a travava: 2,050 × R$ 19,90 virava
  R$ 40,79 e o servidor recusava;
- conversão de moeda e edição parcial transformavam `1,235 × 39,90` em `1 × 49,28`.

Diante de qualquer recusa, o caminho que sempre funcionava era mandar só o total.

## Decisão

1. **Unidade** (`TransactionItem.unit`), anulável, com vocabulário fixo: `un`, `kg`,
   `g`, `l`, `ml`, `m` (decisão do dono; ampliar é decisão deliberada). Conferida na
   aplicação, não por enum do Postgres.
2. **Preço unitário com até 4 casas** (`unit_amount`, `Numeric(20,4)`). É preço de
   referência, não lançamento: o **total da linha** (`amount`) continua em centavos,
   e é ele que soma, divide e entra em fatura (ADR 0001 intacto).
3. **O total impresso é a verdade, com tolerância de 1 centavo.** A linha fecha se
   `|qtd × unitário − total| ≤ R$ 0,01`, com o produto EXATO. Balanças e caixas
   arredondam de formas diferentes; diferença maior é leitura errada e é recusada com
   uma mensagem que diz o que conferir. Uma regra só: `app/domain/item_da_nota.py`,
   replicada na tela com um teste de equivalência.
4. **Obrigatório só ao ADICIONAR item** (decisão do dono). A exigência de
   quantidade, unidade e preço unitário mora nas portas de entrada — o editor de
   itens da tela e o `items` das tools do MCP —, não no validador genérico. Assim ficam
   de fora: o lançamento sem itens ("mercado, 150 reais"), o **item-sombra** que só
   guarda a categoria de um lançamento simples, e as **linhas antigas** sem medida
   (editar não obriga a inventar uma).
5. **A medida sobrevive às reescritas do total.** Conversão de moeda (na entrada e na
   troca de moeda-base) e rateio da edição parcial mantêm quantidade e unidade e
   recalculam o unitário com 4 casas — ou o anulam, se nem assim ele fechar.
6. **Parcelado:** cada fatia guarda a quantidade e a unidade da compra, **sem** o
   preço unitário; a conferência quantidade × unitário acontece na compra inteira,
   antes do fatiamento, e a "compra inteira" remontada devolve a medida. O unitário
   não vai para a fatia porque, ao editar uma parcela sozinha, a tela recalcularia o
   total da parcela a partir dele.

## Consequências

- Migração `f4b8d2c6a1e3`: `unit` e a escala de `unit_amount`. Ampliar a escala não
  perde dado; itens antigos ficam sem unidade (nenhum preenchimento retroativo — "1
  un" afirmaria uma medida que ninguém informou).
- O preço unitário de uma compra parcelada não é guardado (item 6).
- MCP: `ItemIn` ganha `unit` e unitário com 4 casas, e passa a exigir os três campos
  para item novo; a instrução de dinheiro ganha a exceção da nota; skill
  `registrar-nota` e casos de avaliação.
