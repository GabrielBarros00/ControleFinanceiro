"""Nenhuma coluna de data do schema é `timezone=True` (ADR 0025).

O projeto guarda instantes como UTC SEM tzinfo, e o `civil_instant` escreve
datas civis do mesmo jeito. Até o sqlmodel 0.0.42 isso era o padrão de qualquer
campo `datetime`. Da 0.0.48 em diante o padrão virou `UTCDateTime`: coluna
TIMESTAMPTZ que RECUSA valor sem tzinfo na escrita (`ValueError: Datetime values
must have timezone information`) e devolve tudo com tzinfo na leitura. Bastaria
um campo novo sem `sa_type=DateTime` para essa semântica entrar no schema calada
— o `alembic check` só acusa depois que alguém gerar a migração.
"""
from sqlalchemy import DateTime
from sqlmodel import SQLModel
from sqlmodel.sql.sqltypes import UTCDateTime

from app import models  # noqa: F401  (registra todas as tabelas na metadata)


def _colunas_de_data():
    for tabela in SQLModel.metadata.sorted_tables:
        for coluna in tabela.columns:
            if isinstance(coluna.type, (DateTime, UTCDateTime)):
                yield f"{tabela.name}.{coluna.name}", coluna.type


def test_ha_colunas_de_data_para_conferir():
    """Denominador: uma varredura que não acha nada passa vazia."""
    assert len(list(_colunas_de_data())) >= 100


def test_nenhuma_coluna_de_data_tem_fuso():
    com_fuso = [
        nome
        for nome, tipo in _colunas_de_data()
        if isinstance(tipo, UTCDateTime) or tipo.timezone
    ]
    assert com_fuso == [], (
        "colunas de data com timezone=True (faltou `sa_type=DateTime` no Field): "
        f"{com_fuso}"
    )
