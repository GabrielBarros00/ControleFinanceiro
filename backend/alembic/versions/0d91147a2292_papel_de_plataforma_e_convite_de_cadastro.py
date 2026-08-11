"""Papel de plataforma, configuração em runtime e convite de cadastro (ADR 0026)

Três coisas que só fazem sentido juntas, porque nenhuma delas funciona sozinha:

- `user.platform_role` — quem opera o SITE. Até aqui o sistema só sabia falar de
  papéis DENTRO de um workspace (`WorkspaceMembership.role`), o que respondia
  "quem manda nesta casa" e deixava "quem manda no servidor" sem resposta: a
  única forma de desativar uma conta ou ler a trilha de auditoria inteira era
  `docker compose exec` com SQL na mão.
- `appsetting` — o comportamento do site alterável sem reiniciar. Antes, mudar de
  cadastro aberto para cadastro por convite seria editar `.env` e derrubar o
  container.
- `registrationinvite` — o convite de CRIAR CONTA, que não existia. O
  `workspaceinvite` convida para uma casa e pressupõe que a pessoa possa existir;
  quem responde se ela pode existir é esta tabela.

Sem o papel, não há quem administre; sem a configuração, o modo de cadastro é
imutável; sem o convite, fechar o cadastro tranca todo mundo do lado de fora.

**`platform_role` é texto, não enum nativo.** Segue `workspacemembership.role`
pelo motivo registrado na revisão `e9b2c50d7a14`: acrescentar valor a um enum do
Postgres exige `ALTER TYPE` à mão, e as três redes que deveriam pegar a omissão
são cegas para ela — a suíte roda em SQLite (sem tipo enum), o `alembic check`
compara tabelas e colunas mas não os rótulos de um enum já criado, e o
`create_all` dos testes não recria um tipo que já existe. Foi assim que uma
recorrência diária chegou quebrada em produção.

**`server_default='user'` é o valor fechado.** Conta que já existe — e, num banco
novo, toda conta que nascer — recebe o papel sem poder nenhum. Promover é ato
explícito, feito pela tela de Admin e registrado na auditoria. O primeiro
superadmin nasce pelo `SUPERADMIN_EMAIL` (ver `app/main.py` e a exceção de
bootstrap em `app/api/routes/auth.py`), não por esta migração: gravar um papel
privilegiado a partir de um e-mail que a migração não tem como validar seria
conceder acesso com base num palpite.

Nenhuma linha de `appsetting` é semeada aqui, de propósito. A ausência de linha
significa "vale o padrão" (`app/services/app_settings.py` resolve
`AppSetting → Settings → embutido`), então semear congelaria na tabela valores
que hoje acompanham o `.env` — e um `attachment_quota_bytes` gravado em julho
continuaria valendo depois de o operador mudar a variável de ambiente, sem que
nada na tela explicasse por quê.

Revision ID: 0d91147a2292
Revises: e9b2c50d7a14
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0d91147a2292'
down_revision: Union[str, Sequence[str], None] = 'e9b2c50d7a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'appsetting',
        sa.Column('key', sa.String(length=64), nullable=False),
        # JSON serializado, não uma coluna por chave: o conjunto de chaves cresce
        # com o produto, e uma coluna nova a cada botão da tela de administração
        # seria uma migração a cada botão.
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('key'),
    )

    op.create_table(
        'registrationinvite',
        sa.Column('id', sa.Integer(), nullable=False),
        # Nulo = convite por LINK; preenchido = nominal.
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('uses', sa.Integer(), nullable=False),
        sa.Column('accepted_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['accepted_by_user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_registrationinvite_created_by_user_id'),
        'registrationinvite', ['created_by_user_id'], unique=False,
    )
    op.create_index(
        op.f('ix_registrationinvite_email'),
        'registrationinvite', ['email'], unique=False,
    )
    # ÚNICO: o token é a credencial do convite e é por ele que o cadastro o
    # resolve. Duas linhas com o mesmo token fariam a resolução depender de qual
    # o `.first()` devolvesse — o mesmo defeito não-determinístico que a
    # `uq_membership_workspace_user` fechou em membership.
    op.create_index(
        op.f('ix_registrationinvite_token'),
        'registrationinvite', ['token'], unique=True,
    )

    op.add_column(
        'user',
        sa.Column('platform_role', sa.String(length=20), server_default='user', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('user', 'platform_role')
    op.drop_index(op.f('ix_registrationinvite_token'), table_name='registrationinvite')
    op.drop_index(op.f('ix_registrationinvite_email'), table_name='registrationinvite')
    op.drop_index(op.f('ix_registrationinvite_created_by_user_id'), table_name='registrationinvite')
    op.drop_table('registrationinvite')
    op.drop_table('appsetting')
