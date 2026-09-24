"""Dinheiro na fronteira do MCP: string decimal com ponto, 2 casas, sem float.

**Entrada.** O schema anuncia string (`"89.90"`), que é o que evita a perda de
precisão do JSON number. Modelo que mandar número (`89.9`) ainda é aceito — o
valor passa por `str()` antes de virar `Decimal`, nunca por aritmética de float —
e vírgula decimal sem ponto (`"89,90"`) também, porque é inequívoca. O que NÃO
se aceita é ambiguidade: mais de 2 casas, separador de milhar, notação
científica. Aí volta `VALIDATION_ERROR` explicando o formato — arredondar em
silêncio seria decidir pelo usuário quanto ele gastou.

**Saída.** Sempre string com exatamente 2 casas (`"487.90"`), mais a moeda ao lado.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

from app.schemas.common import MAX_MONEY

_FORMATO = re.compile(r"^\d{1,16}(\.\d{1,2})?$")
_CENTAVO = Decimal("0.01")


def _parse(valor: Any, *, allow_zero: bool, allow_negative: bool = False) -> Decimal:
    if isinstance(valor, bool):
        raise ValueError("valor monetário inválido")
    if isinstance(valor, (int, float)):
        texto = repr(valor) if isinstance(valor, float) else str(valor)
    elif isinstance(valor, Decimal):
        texto = format(valor, "f")
    elif isinstance(valor, str):
        texto = valor.strip()
    else:
        raise ValueError("valor monetário deve ser string decimal, ex.: \"89.90\"")
    negativo = texto.startswith("-")
    if negativo:
        if not allow_negative:
            raise ValueError("valor não pode ser negativo")
        texto = texto[1:]
    if "," in texto and "." not in texto and texto.count(",") == 1:
        texto = texto.replace(",", ".")
    if not _FORMATO.match(texto):
        raise ValueError(
            "use string decimal com ponto e no máximo 2 casas, ex.: \"89.90\" "
            "(sem separador de milhar)"
        )
    try:
        numero = Decimal(texto)
    except InvalidOperation as exc:
        raise ValueError("valor monetário inválido") from exc
    if negativo:
        numero = -numero
    if not allow_zero and numero == 0:
        raise ValueError("valor deve ser maior que zero")
    if abs(numero) > MAX_MONEY:
        raise ValueError("valor acima do máximo aceito")
    return numero.quantize(_CENTAVO)


def _positivo(valor: Any) -> Decimal:
    return _parse(valor, allow_zero=False)


def _nao_negativo(valor: Any) -> Decimal:
    return _parse(valor, allow_zero=True)


def _com_sinal(valor: Any) -> Decimal:
    return _parse(valor, allow_zero=True, allow_negative=True)


_SCHEMA_ENTRADA = {
    "type": "string",
    "pattern": r"^\d{1,16}([.,]\d{1,2})?$",
    "description": "Valor em string decimal com ponto e até 2 casas.",
    "examples": ["89.90", "3000", "0.99"],
}

#: Valor > 0 (preço, total, parcela).
MoneyIn = Annotated[Decimal, BeforeValidator(_positivo), WithJsonSchema(_SCHEMA_ENTRADA)]
#: Valor >= 0 (percentual de divisão, filtro de valor mínimo).
MoneyInOrZero = Annotated[Decimal, BeforeValidator(_nao_negativo), WithJsonSchema(_SCHEMA_ENTRADA)]
#: Valor com sinal (saldo real de conta pode ser negativo).
SignedMoneyIn = Annotated[
    Decimal,
    BeforeValidator(_com_sinal),
    WithJsonSchema({
        "type": "string",
        "pattern": r"^-?\d{1,16}([.,]\d{1,2})?$",
        "description": "Valor em string decimal, pode ser negativo, ex.: \"-120.50\".",
    }),
]


def _percentual(valor: Any) -> Decimal:
    numero = _parse(valor, allow_zero=False)
    if numero > 100:
        raise ValueError("percentual deve ficar entre 0 e 100")
    return numero


#: Percentual de divisão: 0 < p <= 100, até 2 casas.
PercentIn = Annotated[
    Decimal,
    BeforeValidator(_percentual),
    WithJsonSchema({
        "type": "string",
        "pattern": r"^\d{1,3}([.,]\d{1,2})?$",
        "description": "Percentual entre 0 e 100 em string decimal, ex.: \"50\" ou \"33.33\".",
    }),
]


def to_str(valor: Decimal | None) -> str | None:
    if valor is None:
        return None
    return format(Decimal(valor).quantize(_CENTAVO, rounding=ROUND_HALF_UP), "f")


#: Saída: sempre string com 2 casas.
MoneyOut = Annotated[
    Decimal,
    PlainSerializer(lambda v: to_str(v), return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "description": "Valor decimal com 2 casas."}),
]


def fmt_brl(valor: Decimal | None, moeda: str = "BRL") -> str:
    """Formato de leitura para o texto-resumo (não para o JSON): `R$ 1.234,56`."""
    if valor is None:
        return "—"
    numero = Decimal(valor).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    sinal = "-" if numero < 0 else ""
    inteiro, _, centavos = format(abs(numero), "f").partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    prefixo = "R$ " if moeda == "BRL" else f"{moeda} "
    return f"{sinal}{prefixo}{'.'.join(grupos)},{centavos or '00'}"
