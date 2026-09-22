"""Quitação em lote não é movimento de caixa (ADR 0023)

`POST /me/financing/{id}/installments/settle-past` existe para quem cadastra um
financiamento **que já existia**: o app gera o cronograma inteiro, toda parcela
nasce em aberto, e o contrato entra no sistema com meses de "atraso" que na vida
real foram pagos. A rota marca essas parcelas como pagas e promete, no próprio
docstring, não criar despesa nem movimento de caixa.

Ela não cumpria a promessa. `is_paid=True` sem despesa vinculada é exatamente o
gatilho da fonte 4 do `CashFlowService` ("parcela paga SEM despesa que já a
conte"), então cada parcela quitada aqui virava uma saída de caixa no mês em que
venceu — quitar doze parcelas escrevia uma saída retroativa em cada um dos doze
meses fechados. As duas regras estão certas isoladamente e se contradizem juntas:
falta ao esquema a diferença entre "paguei e não lancei a despesa" e "isto
aconteceu antes de o app existir para mim".

`paid_outside_app` é essa diferença, e mora na parcela porque quem precisa dela é
uma leitura que acontece meses depois.

**O backfill.** A coluna nascer `false` deixaria intacto o caixa já inflado de
quem usou a rota — o dado errado está gravado, não é só comportamento futuro. As
quitadas em lote são reconhecíveis com precisão porque a rota é a ÚNICA que grava
`paid_at = due_date` (a meia-noite exata do vencimento): o pagamento individual
grava `datetime.now(UTC)`, e o frontend nunca envia `paid_at`. Somadas as outras
duas marcas da rota — ela não recebe conta e não cria despesa —, a assinatura é
`is_paid AND paid_at = meia-noite do due_date AND account_id IS NULL AND sem
Transaction viva vinculada`.

O risco residual é quem tenha chamado a API à mão com `paid_at` na meia-noite
exata do vencimento, sem conta e sem workspace: essa saída deixa o caixa. É
reversível pela interface (`unpay` e pagar de novo), e a alternativa — não fazer
backfill — deixa errado o caso comum para consertar o caso que ninguém fez.

A comparação roda em Python, não em SQL: `date(paid_at)` não existe no Postgres e
`paid_at = due_date` compara tipos diferentes em cada dialeto. Com as colunas
tipadas abaixo, o SQLAlchemy entrega `datetime`/`date` nos dois bancos — é a mesma
armadilha do `sa.text()`, que no SQLite devolveria string.

Revision ID: f2b6d41a9c03
Revises: d5a9e3c721b4
Create Date: 2026-09-22
"""
from datetime import time
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2b6d41a9c03'
down_revision: Union[str, Sequence[str], None] = 'd5a9e3c721b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Colunas TIPADAS: é o que faz o driver devolver `datetime`/`date` em vez das
#: strings que o SQLite entregaria por `sa.text()`.
_PARCELA = sa.table(
    'amortizationinstallment',
    sa.column('id', sa.Integer),
    sa.column('paid_at', sa.DateTime),
    sa.column('due_date', sa.Date),
    sa.column('is_paid', sa.Boolean),
    sa.column('account_id', sa.Integer),
    sa.column('paid_outside_app', sa.Boolean),
)

#: `transaction` é palavra reservada no SQLite; o dialeto cita sozinho.
_TRANSACAO = sa.table(
    'transaction',
    sa.column('financing_installment_id', sa.Integer),
    sa.column('deleted_at', sa.DateTime),
)

_MEIA_NOITE = time(0, 0)


def _colunas(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(nome_da_tabela)}


def _marca_as_quitadas_em_lote() -> None:
    """Backfill. Roda SEMPRE, não só quando a coluna acabou de nascer.

    Um banco que ganhou a coluna pelo `create_all` de outro ambiente a tem toda
    `false`, e é justamente o caso em que o caixa continuaria inflado.
    """
    bind = op.get_bind()

    ja_lancada = (
        sa.select(sa.literal(1))
        .where(_TRANSACAO.c.financing_installment_id == _PARCELA.c.id)
        .where(_TRANSACAO.c.deleted_at.is_(None))
        .exists()
    )
    candidatas = bind.execute(
        sa.select(_PARCELA.c.id, _PARCELA.c.paid_at, _PARCELA.c.due_date)
        .where(_PARCELA.c.is_paid.is_(True))
        .where(_PARCELA.c.paid_outside_app.is_(False))
        .where(_PARCELA.c.paid_at.is_not(None))
        .where(_PARCELA.c.account_id.is_(None))
        .where(~ja_lancada)
    ).all()

    alvos = [
        parcela_id
        for parcela_id, pago_em, vence_em in candidatas
        # A assinatura da rota: o carimbo é o vencimento, à meia-noite exata.
        if pago_em.date() == vence_em and pago_em.time() == _MEIA_NOITE
    ]
    if not alvos:
        return

    # Em fatias: um `IN` com dezenas de milhares de ids estoura o limite de
    # parâmetros do driver, e um contrato de 35 anos tem 420 parcelas.
    for inicio in range(0, len(alvos), 500):
        bind.execute(
            sa.update(_PARCELA)
            .where(_PARCELA.c.id.in_(alvos[inicio:inicio + 500]))
            .values(paid_outside_app=True)
        )


def upgrade() -> None:
    if 'paid_outside_app' not in _colunas('amortizationinstallment'):
        op.add_column(
            'amortizationinstallment',
            sa.Column(
                'paid_outside_app',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    _marca_as_quitadas_em_lote()


def downgrade() -> None:
    if 'paid_outside_app' in _colunas('amortizationinstallment'):
        op.drop_column('amortizationinstallment', 'paid_outside_app')
