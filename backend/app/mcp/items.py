"""Itens da nota e ajustes na fronteira do MCP (ADR 0035 §10).

O app já sabe o que o relatório do ChatGPT pediu: cada lançamento tem itens
(`TransactionItem`, com quantidade, unitário e categoria), cada item pode ter a
SUA divisão entre pessoas (`TransactionItemShare`, o `split_mode=item`) e a nota
fecha com ajustes (desconto, frete, taxa, gorjeta, cashback, arredondamento). Quem
garante as contas é `compute_transaction_breakdown`: itens + ajustes = total, cada
item fecha nas partes, ajustes rateados em centavos pela proporção de cada pessoa.

Esta camada só traduz o que o modelo diz ("arroz só do Gabriel, refrigerante
dividido") para a entrada daquele comando. Três decisões moram aqui:

- **Item com divisão própria ⇒ divisão por item.** Os itens sem divisão própria
  herdam a divisão do lançamento (partes iguais ou percentual; valor fixo no total
  não se distribui por item e é recusado com explicação).
- **Parcelado com itens ⇒ divisão por item.** O parcelamento do app, no modo
  "divisão pela despesa", guarda só UM item por parcela: os outros se perderiam em
  silêncio. No modo por item cada item é fatiado pelos meses e continua existindo.
- **Parcelado com ajustes é recusado.** O parcelamento do app não leva os ajustes
  (desconto, frete) para as parcelas; aceitar seria perder o desconto sem aviso.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import Field, model_validator
from sqlmodel import Session

from app.mcp import resolve
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyInOrZero, QuantityIn, fmt_brl
from app.mcp.registry import ToolInput
from app.mcp.writes import Division, ShareIn
from app.models.transaction import AdjustmentType, SplitMethod, SplitMode
from app.schemas.common import DESCRIPTION_MAX, TITLE_MAX
from app.schemas.transaction import (
    TransactionAdjustmentCreate,
    TransactionItemCreate,
    TransactionItemShareBase,
)

AdjustmentKind = Literal["discount", "tax", "tip", "shipping", "cashback", "rounding", "other"]
_REDUZEM = {"discount", "cashback"}
_AUMENTAM = {"tax", "tip", "shipping"}
_CENTAVO = Decimal("0.01")


class ItemIn(ToolInput):
    """Uma linha da nota."""

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    amount: Optional[MoneyInOrZero] = Field(None, description="Total da linha (ou quantity × unit_amount).")
    quantity: Optional[QuantityIn] = None
    unit_amount: Optional[MoneyInOrZero] = None
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)
    category: Optional[str] = Field(None, max_length=120, description="Omitida: a do lançamento.")
    category_id: Optional[int] = None
    owner: Optional[str] = Field(None, max_length=120, description="Item todo de uma pessoa (nome, ou \"eu\").")
    owner_id: Optional[int] = None
    split_with: Optional[List[str]] = Field(None, max_length=20, description="Partes iguais: você + estas pessoas.")
    split: Optional[List[ShareIn]] = Field(None, min_length=1, max_length=20, description="Divisão desigual do item.")

    @model_validator(mode="after")
    def _coerente(self):
        if self.category is not None and self.category_id is not None:
            raise ValueError("em cada item, informe category ou category_id, não os dois")
        if self.owner is not None and self.owner_id is not None:
            raise ValueError("em cada item, informe owner ou owner_id, não os dois")
        formas = sum(x is not None for x in (self.owner or self.owner_id, self.split_with, self.split))
        if formas > 1:
            raise ValueError("em cada item, use só uma forma de divisão: owner, split_with ou split")
        if self.amount is None and (self.quantity is None or self.unit_amount is None):
            raise ValueError(f"item \"{self.title}\": informe amount, ou quantity e unit_amount")
        if self.split:
            tipos = {"amount" if s.amount is not None else "percent" for s in self.split}
            if len(tipos) > 1:
                raise ValueError(f"item \"{self.title}\": use valor em todas as partes ou percentual em todas")
        return self

    def has_division(self) -> bool:
        return any(v is not None for v in (self.owner, self.owner_id, self.split_with, self.split))

    def line_amount(self) -> Decimal:
        if self.amount is not None:
            return self.amount
        bruto = self.quantity * self.unit_amount
        if bruto != bruto.quantize(_CENTAVO):
            # Nunca arredondar o que a pessoa gastou: quem decide o centavo é a nota.
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                f"Item \"{self.title}\": {self.quantity} × {self.unit_amount} não fecha em centavos. "
                "Informe o total da linha em `amount`, como está na nota.",
            )
        return bruto.quantize(_CENTAVO)

    def people_named(self) -> tuple[list[str], list[int]]:
        nomes = list(self.split_with or [])
        ids: list[int] = []
        if self.owner:
            nomes.append(self.owner)
        if self.owner_id is not None:
            ids.append(self.owner_id)
        for parte in self.split or []:
            if parte.person is not None:
                nomes.append(parte.person)
            else:
                ids.append(parte.person_id)
        return nomes, ids


class AdjustmentIn(ToolInput):
    """Diferença entre a soma dos itens e o total da nota."""

    type: AdjustmentKind = Field(description="discount e cashback reduzem; tax, tip e shipping aumentam.")
    amount: MoneyIn = Field(description="Positivo; o sinal vem do tipo.")
    reduces: Optional[bool] = Field(None, description="rounding/other: true = reduz o total.")
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)

    @model_validator(mode="after")
    def _sinal(self):
        if self.reduces is not None and self.type not in ("rounding", "other"):
            raise ValueError("`reduces` só vale para ajustes rounding ou other; o tipo já diz o sinal")
        return self

    def signed(self) -> Decimal:
        if self.type in _REDUZEM or (self.type not in _AUMENTAM and self.reduces):
            return -self.amount
        return self.amount


def items_total(items: List[ItemIn], adjustments: Optional[List[AdjustmentIn]]) -> Decimal:
    return sum((i.line_amount() for i in items), Decimal("0")) + sum(
        (a.signed() for a in adjustments or []), Decimal("0")
    )


def items_people(items: Optional[List[ItemIn]]) -> tuple[list[str], list[int]]:
    nomes: list[str] = []
    ids: list[int] = []
    for item in items or []:
        n, i = item.people_named()
        nomes += n
        ids += i
    return nomes, ids


@dataclass
class ItemsPlan:
    split_mode: SplitMode
    items: List[TransactionItemCreate]
    adjustments: List[TransactionAdjustmentCreate]


def _shares_do_item(
    session: Session, workspace_id: int, me_id: int, item: ItemIn, members: list[resolve.Match],
) -> List[TransactionItemShareBase]:
    def pessoa(nome: Optional[str], pid: Optional[int]) -> resolve.Match:
        return resolve.resolve_person(
            session, workspace_id=workspace_id, me_id=me_id, person=nome, person_id=pid, members=members,
        )

    if item.owner is not None or item.owner_id is not None:
        dono = pessoa(item.owner, item.owner_id)
        return [TransactionItemShareBase(user_id=dono.id, split_method=SplitMethod.equal, input_value=Decimal("0"))]
    if item.split_with:
        vistos: dict[int, resolve.Match] = {me_id: pessoa(None, me_id)}
        for nome in item.split_with:
            m = pessoa(nome, None)
            vistos.setdefault(m.id, m)
        return [
            TransactionItemShareBase(user_id=uid, split_method=SplitMethod.equal, input_value=Decimal("0"))
            for uid in vistos
        ]
    partes: List[TransactionItemShareBase] = []
    vistos_ids: set[int] = set()
    for parte in item.split or []:
        m = pessoa(parte.person, parte.person_id)
        if m.id in vistos_ids:
            raise McpToolError(ErrorCode.VALIDATION_ERROR, f"{m.name} aparece duas vezes na divisão de \"{item.title}\".")
        vistos_ids.add(m.id)
        if parte.amount is not None:
            partes.append(TransactionItemShareBase(user_id=m.id, split_method=SplitMethod.fixed, input_value=parte.amount))
        else:
            partes.append(TransactionItemShareBase(user_id=m.id, split_method=SplitMethod.percentage, input_value=parte.percent))
    return partes


def _herdada(division: Division, item_title: str) -> List[TransactionItemShareBase]:
    """A divisão do lançamento repetida no item (partes iguais ou percentual)."""
    if not division.splits:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"O item \"{item_title}\" não tem divisão própria e o lançamento não tem uma divisão do total "
            "para ele seguir: informe `owner`, `split_with` ou `split` neste item.",
        )
    metodos = {s.split_method for s in division.splits}
    if SplitMethod.fixed in metodos:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"A divisão por valores fixos vale para o total e não se distribui pelo item \"{item_title}\". "
            "Informe a divisão de cada item (owner, split_with ou split no item) ou use partes iguais/percentual.",
        )
    return [
        TransactionItemShareBase(user_id=s.user_id, split_method=s.split_method, input_value=s.input_value)
        for s in division.splits
    ]


def plan_items(
    session: Session,
    workspace_id: int,
    me_id: int,
    *,
    items: List[ItemIn],
    adjustments: Optional[List[AdjustmentIn]],
    division: Division,
    total: Decimal,
    default_category_id: Optional[int],
    installments: Optional[int],
) -> ItemsPlan:
    """Traduz itens e ajustes para a entrada do comando do app (sem gravar nada)."""
    if not items:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Informe ao menos um item.")
    if adjustments and installments:
        raise McpToolError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "O app não parcela compra com ajustes (desconto, frete, taxa): as parcelas não levam o ajuste. "
            "Lance os itens já com o desconto aplicado, ou registre sem parcelar.",
        )
    soma = items_total(items, adjustments)
    if soma != total:
        itens = sum((i.line_amount() for i in items), Decimal("0"))
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"Itens ({fmt_brl(itens)}) + ajustes ({fmt_brl(soma - itens)}) = {fmt_brl(soma)}, mas o total "
            f"informado é {fmt_brl(total)}. Confira a nota: a diferença costuma ser desconto, frete ou taxa "
            "(informe em `adjustments`).",
            details={"items_total": str(itens), "adjustments_total": str(soma - itens), "amount": str(total)},
        )

    membros = resolve.space_members(session, workspace_id)
    por_item = any(i.has_division() for i in items) or bool(installments)
    linhas: List[TransactionItemCreate] = []
    for posicao, item in enumerate(items):
        categoria = resolve.resolve_category(
            session, workspace_id, category_id=item.category_id, category=item.category,
        ) if (item.category is not None or item.category_id is not None) else None
        partes = None
        if por_item:
            partes = (
                _shares_do_item(session, workspace_id, me_id, item, membros)
                if item.has_division() else _herdada(division, item.title)
            )
        linhas.append(TransactionItemCreate(
            title=item.title,
            description=item.description,
            amount=item.line_amount(),
            quantity=item.quantity or Decimal("1"),
            unit_amount=item.unit_amount,
            position=posicao,
            category_id=categoria.id if categoria else default_category_id,
            shares=partes,
        ))
    ajustes = [
        TransactionAdjustmentCreate(type=AdjustmentType(a.type), amount=a.signed(), description=a.description)
        for a in adjustments or []
    ]
    return ItemsPlan(
        split_mode=SplitMode.item if por_item else SplitMode.transaction,
        items=linhas,
        adjustments=ajustes,
    )
