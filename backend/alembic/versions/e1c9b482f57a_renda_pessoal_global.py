"""Renda é da PESSOA, não do workspace (ADR 0019)

`Income.workspace_id` e `RecurringIncome.workspace_id` eram NOT NULL, então o
salário pertencia a um espaço de colaboração. Quem criava um workspace novo via a
própria receita zerada e tinha de recadastrar o salário — e ficava com N cópias do
mesmo salário, uma por workspace, que divergiam na primeira correção.

Agora `NULL` = renda PESSOAL (global, aparece em todos os workspaces do dono) e
preenchido = renda DA CASA daquele workspace (aluguel de imóvel compartilhado).
As duas tabelas de compartilhamento dizem a quais orçamentos uma renda pessoal
CONTRIBUI — vazio é privado, que é o default seguro.

**Migração dos dados existentes: as rendas viram PESSOAIS, compartilhadas com o
workspace de origem.** É o único caminho que satisfaz as duas coisas ao mesmo
tempo:

- o dono passa a ver a própria renda em todos os workspaces (o que ele pediu);
- o total da casa não muda em workspace nenhum, porque o compartilhamento repõe
  exatamente a visibilidade que o `workspace_id` dava.

A alternativa — deixar como estava — manteria o salário presos ao workspace de
origem e a correção não teria efeito sobre os dados que já existem, que são
justamente os do usuário reclamando.

Renda que já era da casa continua sendo: não há como distinguir, no dado
existente, "salário do fulano" de "aluguel do imóvel do casal", e tratar tudo
como pessoal-do-dono é o palpite certo — `Income.user_id` sempre apontou para
quem recebe. Quem tiver renda genuinamente da casa marca isso na tela (`scope`),
o que reverte a linha para o workspace.

Revision ID: e1c9b482f57a
Revises: d7f2b419ac36
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1c9b482f57a'
down_revision = 'd7f2b419ac36'
branch_labels = None
depends_on = None


def _tabelas(inspector) -> set:
    return set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tabelas = _tabelas(inspector)

    # 0. Moeda de relatório do usuário: destino de conversão do que é PESSOAL.
    # Sem ela, um salário pessoal em moeda estrangeira converteria pela base do
    # workspace que por acaso disparou a leitura — o MESMO salário valendo números
    # diferentes conforme a tela aberta.
    if 'user' in tabelas:
        colunas = {c['name'] for c in inspector.get_columns('user')}
        if 'report_currency' not in colunas:
            op.add_column(
                'user',
                sa.Column(
                    'report_currency',
                    sa.String(length=3),
                    nullable=False,
                    server_default='BRL',
                ),
            )

    # 1. Tabelas de compartilhamento
    if 'incomeworkspaceshare' not in tabelas:
        op.create_table(
            'incomeworkspaceshare',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('income_id', sa.Integer(), nullable=False),
            sa.Column('workspace_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['income_id'], ['income.id']),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id']),
            sa.UniqueConstraint(
                'income_id', 'workspace_id', name='uq_income_share_income_workspace'
            ),
        )
        op.create_index(
            'ix_incomeworkspaceshare_income_id', 'incomeworkspaceshare', ['income_id']
        )
        op.create_index(
            'ix_incomeworkspaceshare_workspace_id', 'incomeworkspaceshare', ['workspace_id']
        )

    if 'recurringincomeworkspaceshare' not in tabelas:
        op.create_table(
            'recurringincomeworkspaceshare',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('recurring_income_id', sa.Integer(), nullable=False),
            sa.Column('workspace_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['recurring_income_id'], ['recurringincome.id']),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id']),
            sa.UniqueConstraint(
                'recurring_income_id',
                'workspace_id',
                name='uq_recincome_share_template_workspace',
            ),
        )
        op.create_index(
            'ix_recurringincomeworkspaceshare_recurring_income_id',
            'recurringincomeworkspaceshare',
            ['recurring_income_id'],
        )
        op.create_index(
            'ix_recurringincomeworkspaceshare_workspace_id',
            'recurringincomeworkspaceshare',
            ['workspace_id'],
        )

    # 2. O compartilhamento é criado ANTES de anular a coluna: é dela que sai o
    # destino. Invertida, a ordem perderia a informação para sempre.
    op.execute(sa.text("""
        INSERT INTO incomeworkspaceshare (income_id, workspace_id, created_at)
        SELECT i.id, i.workspace_id, CURRENT_TIMESTAMP
        FROM income i
        WHERE i.workspace_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM incomeworkspaceshare s
              WHERE s.income_id = i.id AND s.workspace_id = i.workspace_id
          )
    """))
    op.execute(sa.text("""
        INSERT INTO recurringincomeworkspaceshare
            (recurring_income_id, workspace_id, created_at)
        SELECT r.id, r.workspace_id, CURRENT_TIMESTAMP
        FROM recurringincome r
        WHERE r.workspace_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM recurringincomeworkspaceshare s
              WHERE s.recurring_income_id = r.id AND s.workspace_id = r.workspace_id
          )
    """))

    # 3. Colunas passam a aceitar NULL (batch: ALTER no Postgres, recreate no SQLite)
    with op.batch_alter_table('income') as batch:
        batch.alter_column('workspace_id', existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table('recurringincome') as batch:
        batch.alter_column('workspace_id', existing_type=sa.Integer(), nullable=True)

    # 4. E as rendas existentes viram pessoais (o share do passo 2 preserva a casa)
    op.execute(sa.text("UPDATE income SET workspace_id = NULL"))
    op.execute(sa.text("UPDATE recurringincome SET workspace_id = NULL"))


def downgrade() -> None:
    bind = op.get_bind()

    # Devolve cada renda ao workspace com que está compartilhada. Com mais de um
    # compartilhamento, o menor id vence: a coluna comporta um só, e a alternativa
    # (recusar o downgrade) deixaria o banco travado num estado intermediário.
    op.execute(sa.text("""
        UPDATE income SET workspace_id = (
            SELECT MIN(s.workspace_id) FROM incomeworkspaceshare s
            WHERE s.income_id = income.id
        )
        WHERE workspace_id IS NULL
    """))
    op.execute(sa.text("""
        UPDATE recurringincome SET workspace_id = (
            SELECT MIN(s.workspace_id) FROM recurringincomeworkspaceshare s
            WHERE s.recurring_income_id = recurringincome.id
        )
        WHERE workspace_id IS NULL
    """))
    # Renda pessoal nunca compartilhada não tem para onde voltar: NOT NULL a
    # rejeitaria e a migração pararia no meio. Sai — é perda assumida do
    # downgrade, e é o preço de desfazer "renda é da pessoa".
    op.execute(sa.text("DELETE FROM incomeworkspaceshare WHERE income_id IN (SELECT id FROM income WHERE workspace_id IS NULL)"))
    op.execute(sa.text("DELETE FROM income WHERE workspace_id IS NULL"))
    op.execute(sa.text("DELETE FROM recurringincomeworkspaceshare WHERE recurring_income_id IN (SELECT id FROM recurringincome WHERE workspace_id IS NULL)"))
    op.execute(sa.text("UPDATE income SET recurring_income_id = NULL WHERE recurring_income_id IN (SELECT id FROM recurringincome WHERE workspace_id IS NULL)"))
    op.execute(sa.text("DELETE FROM recurringincome WHERE workspace_id IS NULL"))

    with op.batch_alter_table('income') as batch:
        batch.alter_column('workspace_id', existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table('recurringincome') as batch:
        batch.alter_column('workspace_id', existing_type=sa.Integer(), nullable=False)

    inspector = sa.inspect(bind)
    tabelas = _tabelas(inspector)
    if 'incomeworkspaceshare' in tabelas:
        op.drop_table('incomeworkspaceshare')
    if 'recurringincomeworkspaceshare' in tabelas:
        op.drop_table('recurringincomeworkspaceshare')

    if 'user' in tabelas:
        colunas = {c['name'] for c in sa.inspect(bind).get_columns('user')}
        if 'report_currency' in colunas:
            with op.batch_alter_table('user') as batch:
                batch.drop_column('report_currency')
