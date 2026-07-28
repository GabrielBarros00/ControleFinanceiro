import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlmodel import SQLModel

from alembic import context

# Adiciona o diretório backend ao sys.path para importar app
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
# Importar todos os modelos aqui para o autogenerate detectá-los
from app.models.user import User  # noqa: F401,E402
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceInvite  # noqa: F401,E402
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit, TransactionItem, TransactionItemShare  # noqa: F401,E402
from app.models.recurring import RecurringExpense, RecurringIncome  # noqa: F401,E402
from app.models.audit import AuditLog  # noqa: F401,E402
from app.models.income import Income  # noqa: F401,E402
from app.models.credit_card import CreditCard, CardStatement  # noqa: F401,E402
from app.models.estimate import MonthlyEstimate  # noqa: F401,E402
from app.models.financing import Financing, AmortizationInstallment  # noqa: F401,E402
from app.models.category import Category  # noqa: F401,E402
from app.models.sync_event import SyncEvent  # noqa: F401,E402
from app.models.settlement import Settlement  # noqa: F401,E402
from app.models.attachment import Attachment  # noqa: F401,E402
from app.models.tag import Tag, TransactionTagLink  # noqa: F401,E402
from app.models.payment_account import PaymentAccount  # noqa: F401,E402
from app.models.import_batch import ImportBatch, ImportRow  # noqa: F401,E402
from app.models.refresh_session import RefreshSession  # noqa: F401,E402
from app.models.exchange_rate import ExchangeRate  # noqa: F401,E402
from app.models.notification import Notification  # noqa: F401,E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Define a URL do banco de dados a partir das configurações do app
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
