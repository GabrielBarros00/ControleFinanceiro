# ADR 0025 — Data civil e instante são coisas diferentes, e o backend precisa saber escrever as duas

**Status:** aceito (2026-08-10)
**Relacionado:** [0022](0022-caixa-efetivo.md) (caixa efetivo),
[0023](0023-saldo-de-fatura-arquivo-e-data-efetiva.md) (data efetiva),
[0012](0012-recorrencia-com-snapshot-e-meses-de-calendario.md) (recorrência)

## Contexto

A Onda 7 introduziu `APP_TIMEZONE` e o par `local_day`/`month_key_local` para
**ler** instantes no fuso do usuário. Resolveu o lado da leitura e deixou o da
escrita implícito — e foi ali que o defeito seguinte nasceu.

Há dois tipos de data neste domínio, e eles não se comportam igual:

- **Instante**: "o pagamento saiu às 14h32". Tem hora, é um ponto na linha do
  tempo, e cada fuso o lê num dia possivelmente diferente.
- **Data civil**: "todo dia 1", "vencimento em 05/08", "a linha do extrato é de
  01/08". Não tem hora. É a mesma data em qualquer fuso.

Guardar as duas na mesma coluna `datetime` é aceitável — o que não é aceitável é
converter uma data civil em instante **sem escolher a âncora**. Todo produtor do
backend escolheu a mesma âncora ruim por omissão: meia-noite.

```python
transaction_date=datetime(occ.year, occ.month, occ.day, tzinfo=UTC)
```

`2026-08-01 00:00Z` lido em São Paulo é **31 de julho, 21h**. A recorrência do
dia 1º passava a pertencer ao mês anterior:

- `/me/income?month=2026-08` (que recorta por `month_bounds_utc`) não a devolvia;
- `/me/overview` mostrava renda **zero**;
- o caixa não registrava a entrada;
- e o `billing_month` gravado na MESMA linha dizia `2026-08`.

Duas fontes de verdade discordando dentro de um registro só. O mesmo valia para
a linha de CSV do dia 1º, que `strptime` entrega à meia-noite.

O projeto já tinha a resposta — do outro lado. Todo formulário do frontend faz
`new Date("${data}T12:00:00").toISOString()`. O backend tinha **zero** ocorrências
de meio-dia e **seis** de meia-noite. A convenção existia e nunca foi escrita.

## Decisão

**1. `civil_instant(dia)` é o par de `local_day`.** Um sabe ler um instante; o
outro sabe escrever uma data civil como instante. Ancora ao **meio-dia local** e
devolve UTC naive (nenhuma coluna do projeto usa `timezone=True`).

**2. Meio-dia porque ±12h nunca troca de dia.** De UTC-11 a UTC+11, `local_day` e
`.date()` devolvem a mesma data — um leitor que erre o helper ainda acerta o dia.
Meia-noite é o pior valor possível: erra em todo fuso negativo, sempre.

**3. Quem produz data civil usa o helper.** Materialização de recorrência
(despesa e renda) e parser de CSV. A âncora acontece na **fronteira** — no
`csv_parser`, onde ainda se sabe que aquilo veio de uma coluna de data —, e o
resto do caminho trata um instante de verdade.

**4. `/imports/commit` normaliza meia-noite crua.** A rota aceita linhas do
CLIENTE, e um script que monte o corpo à mão manda `2026-08-01T00:00:00` — a data
como o extrato do banco a mostra. Só `00:00:00` exato é tratado como data civil;
instante genuíno passa intacto.

**5. Dedup e previsão usam `occurrence_date`, não `transaction_date.date()`.** A
coluna já existia (com a unique `uq_recurring_occurrence`) e descreve a
ocorrência; o instante descreve quando o dinheiro se moveu e o usuário pode
editá-lo. Derivar a chave do instante fazia a materialização deixar de reconhecer
a própria instância assim que alguém corrigia a data — e criar uma segunda.

**6. O que NÃO é ancorado:** `closing_date`/`due_date` da fatura. São dias de
calendário que o frontend lê com `parseApiDay`, e ancorá-los moveria a data
exibida. A regra é a proveniência, não a coluna.

**7. `month_bounds` (a janela sem fuso) foi REMOVIDA.** Não tinha um único
chamador e era exatamente a armadilha que este módulo existe para fechar. Deixá-la
disponível era convidar o próximo caminho de leitura a reintroduzir o bug.

**8. `tests/conftest.py` fixa `APP_TIMEZONE=America/Sao_Paulo`.** Toda a suíte de
fronteira dependia do default de `core/config.py` — passava por acidente. Fuso
negativo de propósito: é o que expõe a diferença entre instante e data civil.

## Consequências

- A migração `c7e3b81f04a9` reancora o que já estava gravado, linha a linha em
  Python. Não é um `INTERVAL` fixo porque o deslocamento é `12h − offset do fuso
  NAQUELA data`, e o offset muda com o horário de verão.
- `compute_fingerprint` do import passa a usar `local_day`. Continua compatível
  com o que está gravado: para linha de import a âncora cai no meio do dia.
- A dedup do import compara dia LOCAL dos dois lados, com a janela alargada em um
  dia de cada lado — a comparação é entre um dia de calendário (o CSV) e um
  instante (a coluna), e sem folga os extremos do arquivo escapavam.
- Fica de fora: uma coluna `date` canônica para a renda (a despesa já tem
  `occurrence_date`). A âncora resolve o defeito; a coluna seria mais fiel ao
  domínio e exigiria mexer na unique `(recurring_income_id, received_at)`.
