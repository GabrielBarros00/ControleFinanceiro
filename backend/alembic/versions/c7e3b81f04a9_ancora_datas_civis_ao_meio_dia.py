"""Reancora ao meio-dia local as datas CIVIS gravadas à meia-noite

Recorrência e import de CSV gravavam a data da ocorrência como
`datetime(ano, mês, dia)` — meia-noite. Só que essas colunas guardam INSTANTES,
e todo leitor de mês/dia as converte para o fuso do aplicativo: em São Paulo,
`2026-08-01 00:00` é 31 de julho às 21h. A consequência era a recorrência do dia
1º desaparecer do próprio mês — `/me/income?month=2026-08` não a devolvia,
`/me/overview` mostrava renda zero e o caixa não registrava a entrada — enquanto
o `billing_month` gravado na MESMA linha dizia `2026-08`.

O código passou a ancorar essas datas ao meio-dia local (`domain.dates.civil_instant`),
que é a âncora que o formulário sempre usou do outro lado (`T12:00:00`). Esta
migração move o que já está gravado, senão o histórico continua um mês atrás.

A conversão é feita em Python, linha a linha, e não com um `INTERVAL` fixo: o
deslocamento é `12h − offset do fuso NAQUELA data`, e o offset muda com o
horário de verão. Um `+15 hours` cravado erraria as linhas do outro semestre.

Só toca linhas cuja hora é exatamente `00:00:00`. Um instante de verdade que por
acaso caia na meia-noite é indistinguível de uma data civil aqui, mas as três
populações filtradas (ocorrência de recorrência, linha de CSV) só nascem por
esses caminhos — nenhum deles produz hora do dia.

Revision ID: c7e3b81f04a9
Revises: b6d4f0a72e91
Create Date: 2026-08-10
"""
from datetime import time
from typing import Optional

from alembic import op
import sqlalchemy as sa

from app.domain.dates import civil_instant

revision = 'c7e3b81f04a9'
down_revision = 'b6d4f0a72e91'
branch_labels = None
depends_on = None


def _reancora(bind, tabela: str, coluna: str, filtro: str, chave: Optional[str] = None) -> None:
    """Move para o meio-dia local as linhas civis de uma coluna de data.

    `chave` é a coluna IRMÃ que compõe o índice único da tabela, quando existe um
    que envolva `coluna`. Só `income` tem: `uq_recurring_income_occurrence` é
    `(recurring_income_id, received_at)`, então duas rendas da MESMA recorrência
    no mesmo dia não cabem no mesmo instante e uma delas tem de ficar onde está.

    Passar `chave=None` é afirmação, não descuido:

    - `transaction` tem `uq_recurring_occurrence`, mas sobre
      `(recurring_expense_id, occurrence_date)` — `transaction_date` não participa
      dele, e mover essa coluna não pode colidir com nada;
    - `importrow` não tem índice único nenhum.

    A versão anterior mantinha um conjunto de instantes GLOBAL por chamada, sem
    olhar a que recorrência a linha pertencia. O efeito era o oposto do
    pretendido: a primeira despesa do dia 1º reancorava e as demais linhas
    daquele mesmo dia — de OUTRAS recorrências, sem relação nenhuma com ela —
    ficavam bloqueadas na meia-noite, isto é, com o bug que a migração existe
    para corrigir. Em `transaction` e `importrow` a barreira não protegia nem
    isso, porque ali não há unique que ela pudesse violar.
    """
    # `.columns(...)` não é enfeite: sem tipo declarado o SQLAlchemy não aplica
    # processador de resultado, e o driver do SQLite devolve a coluna DATETIME
    # como `str` ('2026-08-01 00:00:00.000000'). O `.time()` abaixo estourava
    # `AttributeError: 'str' object has no attribute 'time'` em qualquer banco
    # com dados — passava só no banco vazio do CI, onde não há linha para ler.
    colunas = [sa.column("id", sa.Integer), sa.column(coluna, sa.DateTime())]
    if chave:
        colunas.append(sa.column(chave, sa.Integer))
    selecao = ", ".join(["id", coluna] + ([chave] if chave else []))
    linhas = bind.execute(
        sa.text(
            f'SELECT {selecao} FROM "{tabela}" WHERE {filtro} AND {coluna} IS NOT NULL'
        ).columns(*colunas)
    ).fetchall()

    def _slot(linha):
        """A vaga que a linha ocupa no índice único — `None` quando não há um."""
        return None if chave is None else (linha[2], linha[1])

    # Já ancoradas (a coluna pode ter valores dos dois formatos se a aplicação
    # nova rodou antes da migração) servem de barreira: reancorar uma linha em
    # cima de outra violaria `uq_recurring_income_occurrence`.
    ocupados = {_slot(r) for r in linhas if chave and r[1].time() != time.min}

    # `bindparam` tipado pela mesma razão do `.columns()`, do outro lado: um
    # `datetime` cru vai parar no adaptador padrão do `sqlite3`, que está
    # *deprecated* no Python 3.12 e some numa versão futura.
    update = sa.text(f'UPDATE "{tabela}" SET {coluna} = :alvo WHERE id = :id').bindparams(
        sa.bindparam("alvo", type_=sa.DateTime())
    )

    for linha in linhas:
        row_id, valor = linha[0], linha[1]
        if valor.time() != time.min:
            continue
        alvo = civil_instant(valor.date())
        if chave is not None:
            vaga = (linha[2], alvo)
            if vaga in ocupados:
                # Duas ocorrências da mesma recorrência no mesmo dia: só uma cabe
                # na vaga. Avisa em vez de sumir calada — a linha que fica para
                # trás continua com a data civil errada e é caso para o operador.
                print(
                    f"  [c7e3b81f04a9] {tabela}#{row_id} não reancorada: "
                    f"{chave}={linha[2]} já ocupa {alvo.isoformat()}"
                )
                continue
            ocupados.add(vaga)
        bind.execute(update, {"alvo": alvo, "id": row_id})


def upgrade() -> None:
    bind = op.get_bind()

    # `transaction` é palavra reservada nos dois dialetos — daí as aspas.
    _reancora(bind, "transaction", "transaction_date", "recurring_expense_id IS NOT NULL")
    _reancora(
        bind,
        "transaction",
        "transaction_date",
        "id IN (SELECT transaction_id FROM importrow WHERE transaction_id IS NOT NULL)",
    )
    _reancora(
        bind, "income", "received_at", "recurring_income_id IS NOT NULL",
        chave="recurring_income_id",
    )
    # A linha do lote de import é o espelho auditável do CSV (ADR 0008): se ela
    # ficasse na meia-noite, o relatório do lote mostraria um dia a menos que o
    # lançamento que ele mesmo criou.
    _reancora(bind, "importrow", "transaction_date", "1 = 1")


def downgrade() -> None:
    # Voltar para a meia-noite seria reintroduzir o bug — a data civil erra o mês
    # de novo. E a hora original é irrecuperável de qualquer forma: era 00:00
    # justamente por não carregar informação nenhuma.
    pass
