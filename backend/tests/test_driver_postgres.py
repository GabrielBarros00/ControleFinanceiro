"""Contratos de conexão e adaptação do driver PostgreSQL (ADR 0043)."""
import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Column, Date, DateTime, Integer, MetaData, Numeric, Table, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

from app.core.config import Settings
from app.core.database_url import normalizar_url_banco
from app.domain.dates import local_day, month_key_local
from app.models.audit import AuditLog
from app.models.user import User


@pytest.mark.parametrize("prefixo", ["postgres://", "postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://"])
def test_url_legada_preserva_credenciais_e_opcoes(prefixo):
    restante = "pessoa:p%40ss%2F%25@db:5432/controle?sslmode=require&application_name=cron"
    url = prefixo + restante
    esperado = "postgresql+psycopg://" + restante
    assert normalizar_url_banco(url) == esperado
    config = Settings(_env_file=None, APP_ENV="test", DATABASE_URL=url, SECRET_KEY="teste-driver")
    assert config.DATABASE_URL == esperado


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "sqlite:///./dev.db", "sqlite:////tmp/teste.db"])
def test_sqlite_preserva_url(url):
    assert normalizar_url_banco(url) == url


def test_url_generica_carrega_psycopg3_mesmo_com_sqlalchemy20():
    engine = create_engine(normalizar_url_banco("postgresql://teste:teste@localhost/teste"))
    try:
        assert engine.dialect.driver == "psycopg"
        assert engine.dialect.dbapi.__name__ == "psycopg"
    finally:
        engine.dispose()


somente_postgres = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="Adaptação e transações do Psycopg são conferidas no leg Postgres.",
)


@pytest.fixture
def tabela_driver(db_session):
    engine = db_session.get_bind()
    assert engine.dialect.driver == "psycopg"
    tabela = Table(
        "prova_driver", MetaData(),
        Column("id", Integer, primary_key=True),
        Column("valor", Numeric(18, 2)),
        Column("unitario", Numeric(18, 4)),
        Column("quantidade", Numeric(18, 3)),
        Column("instante", DateTime(timezone=False)),
        Column("com_fuso", DateTime(timezone=True)),
        Column("dia", Date),
        Column("dados", JSONB),
        prefixes=["TEMPORARY"], postgresql_on_commit="DROP",
    )
    with engine.begin() as conexao:
        tabela.create(conexao)
        yield conexao, tabela


@somente_postgres
@pytest.mark.parametrize("valor", [Decimal("999999999999.99"), Decimal("-0.01")])
def test_decimal_datas_e_json_fazem_ida_e_volta_sem_perda(tabela_driver, valor):
    conexao, tabela = tabela_driver
    instante = datetime(2026, 11, 1, 15, 4, 5, 123456)
    valores = {
        "id": 1, "valor": valor, "unitario": Decimal("5.8990"),
        "quantidade": Decimal("0.125"), "instante": instante,
        "com_fuso": instante.replace(tzinfo=UTC), "dia": date(2026, 11, 1),
        "dados": {"descricao": "Pão e café ☕", "nulo": None, "itens": [1, True]},
    }
    conexao.execute(tabela.insert().values(**valores))
    linha = conexao.execute(select(tabela)).mappings().one()
    assert dict(linha) == valores
    assert isinstance(linha["valor"], Decimal)
    assert linha["unitario"].as_tuple().exponent == -4
    assert linha["quantidade"].as_tuple().exponent == -3
    assert linha["instante"].tzinfo is None
    assert local_day(linha["instante"]) == date(2026, 11, 1)
    assert month_key_local(linha["instante"]) == "2026-11"


@somente_postgres
def test_savepoint_desfaz_escrita_e_recupera_conexao_apos_erro(tabela_driver):
    conexao, tabela = tabela_driver
    conexao.execute(tabela.insert().values(id=1, valor=Decimal("10.00")))
    ponto = conexao.begin_nested()
    conexao.execute(tabela.insert().values(id=2, valor=Decimal("20.00")))
    ponto.rollback()
    with pytest.raises(IntegrityError) as erro:
        with conexao.begin_nested():
            conexao.execute(tabela.insert().values(id=1, valor=Decimal("99.00")))
    assert erro.value.orig.sqlstate == "23505"
    conexao.execute(tabela.insert().values(id=3, valor=Decimal("30.00")))
    assert conexao.execute(select(tabela.c.id).order_by(tabela.c.id)).scalars().all() == [1, 3]


@somente_postgres
def test_rollback_da_sessao_desfaz_tambem_a_auditoria(db_session):
    pessoa = User(name="Rollback", email="rollback-driver@example.com", password_hash="teste")
    db_session.add(pessoa)
    db_session.flush()
    identificador = pessoa.id
    assert identificador is not None
    assert db_session.exec(select(AuditLog).where(
        AuditLog.resource_type == "User", AuditLog.resource_id == identificador,
    )).first() is not None
    db_session.rollback()
    with Session(db_session.get_bind()) as outra:
        assert outra.get(User, identificador) is None
        assert outra.exec(select(AuditLog).where(
            AuditLog.resource_type == "User", AuditLog.resource_id == identificador,
        )).first() is None
