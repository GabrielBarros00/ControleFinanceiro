"""Datas na fronteira do MCP — explícitas, nunca inferidas no servidor.

O modelo resolve "hoje", "ontem", "mês passado" ANTES de chamar, usando o
`today` e o `timezone` que `profile_get` informa (o fuso do app,
`APP_TIMEZONE`). O servidor só aceita a forma normalizada:

- dia civil `YYYY-MM-DD` → gravado pelo `civil_instant` do domínio (meio-dia
  local), a mesma âncora do formulário do app — então a competência e a fatura
  saem idênticas às de um lançamento feito pela tela;
- mês `YYYY-MM` → competência (`billing_month`).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BeforeValidator, WithJsonSchema

_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _dia(valor: Any) -> date:
    if isinstance(valor, date):
        return valor
    if not isinstance(valor, str) or not _DIA.match(valor.strip()):
        raise ValueError("use a data no formato YYYY-MM-DD, ex.: \"2026-09-22\"")
    try:
        return date.fromisoformat(valor.strip())
    except ValueError as exc:
        raise ValueError("data inexistente no calendário") from exc


def _mes(valor: Any) -> str:
    if not isinstance(valor, str) or not _MES.match(valor.strip()):
        raise ValueError("use o mês no formato YYYY-MM, ex.: \"2026-09\"")
    return valor.strip()


CivilDate = Annotated[
    date,
    BeforeValidator(_dia),
    WithJsonSchema({
        "type": "string",
        "format": "date",
        "description": "Dia civil no fuso da conta (ver profile_get.timezone), formato YYYY-MM-DD.",
    }),
]

MonthKey = Annotated[
    str,
    BeforeValidator(_mes),
    WithJsonSchema({
        "type": "string",
        "pattern": r"^\d{4}-(0[1-9]|1[0-2])$",
        "description": "Mês de competência no formato YYYY-MM.",
    }),
]
