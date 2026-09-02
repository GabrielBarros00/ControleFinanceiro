from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlalchemy import Index, text
from sqlmodel import SQLModel, Field

class IncomeBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    currency: str = Field(default="BRL")
    #: A data de COMPETÊNCIA da renda: quando ela era para entrar (ADR 0034).
    #:
    #: O nome ficou por compatibilidade — a coluna está na unique de ocorrência, no
    #: filtro `?month`, no `api.gen.ts` e no frontend, e renomeá-la custaria tudo
    #: isso para ganhar só um nome melhor. Quando o dinheiro de fato caiu é
    #: `settled_at`, exatamente como `Transaction.transaction_date` (competência) e
    #: `Transaction.settled_at` (caixa) se dividem desde o ADR 0029.
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: Optional[str] = Field(default=None, index=True) # e.g., "Salary", "Freelance"

class Income(IncomeBase, table=True):
    # uq(recurring_income, received_at): uma entrada por ocorrência da renda
    # recorrente — espelha uq_recurring_occurrence do lado da despesa. Sem isto o
    # dedup era só lê-depois-escreve em Python, e a materialização preguiçosa
    # (que roda em ROTAS DE LEITURA) duplicava o salário sob concorrência.
    # A entrada excluída mantém a linha (tombstone) e ocupa a vaga → a unique
    # bloqueia recriação por natureza. Renda avulsa tem recurring_income_id NULL
    # e não colide (NULLs são distintos na unique).
    __table_args__ = (
        Index("uq_recurring_income_occurrence", "recurring_income_id", "received_at", unique=True),
        # Saldo por conta (ADR 0034): a varredura é sempre "as rendas DESTA conta".
        # Parcial porque a esmagadora maioria das linhas tem `account_id` nulo — um
        # índice cheio seria lido quase todo para nada, o mesmo argumento do
        # `ix_transaction_a_liquidar`.
        Index(
            "ix_income_conta",
            "account_id",
            "received_at",
            sqlite_where=text("account_id IS NOT NULL AND deleted_at IS NULL"),
            postgresql_where=text("account_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # Dono/destinatário — a identidade da renda, e o ÚNICO recorte que existe
    # (ADR 0021). Renda não tem workspace: é da pessoa, aparece no painel pessoal
    # dela e é cadastrada uma única vez para todos os workspaces.
    #
    # `workspace_id` existiu em duas encarnações erradas. NOT NULL fazia o salário
    # ter de ser recadastrado em cada workspace novo. Depois, nullable, marcava
    # "renda DA CASA" — mas sem modelo de beneficiários ela era creditada 100% a
    # quem cadastrou no resultado pessoal, então o aluguel recebido pelo casal
    # aparecia inteiro para um só. Sem rateio, renda compartilhada mente; com
    # renda estritamente pessoal, não há o que ratear.
    user_id: int = Field(foreign_key="user.id", index=True)

    # Origem recorrente (quando materializada por RecurringIncome) + mês de
    # competência para dedup/tombstone. None = renda avulsa.
    recurring_income_id: Optional[int] = Field(default=None, foreign_key="recurringincome.id", index=True)
    billing_month: Optional[str] = Field(default=None, index=True)  # YYYY-MM

    # Conversão de moeda: renda estrangeira é convertida para BRL na entrada (sem
    # IOF — IOF é de compra no cartão). None = renda nativa em BRL.
    original_amount: Optional[Decimal] = Field(default=None, decimal_places=2, max_digits=20)
    original_currency: Optional[str] = Field(default=None)
    exchange_rate: Optional[Decimal] = Field(default=None, decimal_places=6, max_digits=20)
    rate_source: Optional[str] = Field(default=None)

    # --- Caixa (ADR 0034), espelho do que o ADR 0029 fez com a despesa ---------
    #
    # `settled_at` é o dia em que o dinheiro CAIU. `None` = ainda não caiu: é a
    # renda prevista, que aparece em "A receber", participa da projeção e **não**
    # entra no saldo nem no `cash_in`. Antes desta coluna a renda tinha uma data só
    # e nenhum estado — o salário do dia 30 ou não existia, ou já contava como
    # recebido no dia 1º; não havia terceira opção.
    #
    # Coluna própria, e não um enum `expected|received`, pela mesma razão do ADR
    # 0029: competência e caixa são ortogonais, e um estado único que significasse
    # as duas coisas voltaria a amarrá-las.
    settled_at: Optional[datetime] = Field(default=None)
    # Prevista que NÃO veio. Diferente de `deleted_at`: a linha continua visível
    # como "cancelada" e segue ocupando a vaga da unique de ocorrência (tombstone),
    # então a materialização não a recria no mês seguinte.
    cancelled_at: Optional[datetime] = Field(default=None)
    # Em qual conta o dinheiro caiu (ADR 0034). `None` = não declarada: a renda
    # conta no caixa e no resultado, mas não move saldo de conta nenhuma, e entra
    # no contador de "movimentos sem conta" da tela de Contas.
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
