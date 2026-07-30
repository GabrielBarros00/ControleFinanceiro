"""Registro central dos models.

Importar QUALQUER model traz todos os outros com ele. Isso não é conveniência:
os `Relationship` do SQLModel referenciam as classes por NOME (string), e o
SQLAlchemy resolve esses nomes na primeira query — configurando de uma vez todos
os mappers do registry, não só o da tabela consultada. Um entrypoint que importe
meia dúzia de models (um script de cron, por exemplo) estoura com

    InvalidRequestError: ... expression 'RecurringExpense' failed to locate a name

na primeira `select()`, ainda que a query não tenha nada a ver com recorrência.
Também é o que garante que `SQLModel.metadata` esteja completo para o Alembic e
que as FKs resolvam no flush (senão: `NoReferencedTableError`).

Ou seja: ao criar um model novo, adicione-o aqui — é o único lugar que precisa
saber da lista.
"""
from app.models import (  # noqa: F401
    attachment,
    audit,
    category,
    credit_card,
    estimate,
    exchange_rate,
    financing,
    import_batch,
    income,
    notification,
    payment_account,
    recurring,
    refresh_session,
    settlement,
    sync_event,
    tag,
    transaction,
    user,
    workspace,
)
