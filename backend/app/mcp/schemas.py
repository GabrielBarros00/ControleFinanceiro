"""Modelos de SAÍDA compartilhados pelas tools (o `outputSchema` delas).

Compactos de propósito: o resultado de uma tool entra no contexto do modelo, e
cada campo a mais é custo em toda conversa. IDs sempre presentes (o modelo
reutiliza em chamadas seguintes sem garimpar texto), nomes resolvidos (o modelo
não precisa de outra chamada para saber quem é o `user_id` 7), dinheiro em string.

Texto vindo do banco (título, descrição, nome) é DADO do usuário. Ele aparece
aqui dentro de campos JSON — nunca concatenado nas instruções do servidor.
"""
from __future__ import annotations

import datetime as dt

from typing import List, Optional

from pydantic import BaseModel, Field

from app.mcp.money import MoneyOut


class Ref(BaseModel):
    id: int
    name: str


class PersonAmount(BaseModel):
    person: Ref
    amount: MoneyOut
    is_me: bool = False


class InstallmentInfo(BaseModel):
    number: int
    of: int
    group_id: Optional[str] = None


class StatementRef(BaseModel):
    id: int
    month: str = Field(description="Mês da fatura (YYYY-MM).")


class ForeignInfo(BaseModel):
    original_amount: MoneyOut
    original_currency: str
    exchange_rate: Optional[str] = None
    iof_rate: Optional[str] = None


class ItemOut(BaseModel):
    """Uma linha da nota."""

    title: str
    description: Optional[str] = None
    quantity: str = Field(description="Quantidade em texto decimal (\"1\", \"1.250\").")
    unit_amount: Optional[MoneyOut] = None
    amount: MoneyOut = Field(description="Total da linha.")
    category: Optional[Ref] = None
    shares: List[PersonAmount] = Field(
        default_factory=list, description="Divisão DESTE item (só quando a despesa é dividida por item).",
    )
    my_share: Optional[MoneyOut] = Field(None, description="Sua parte neste item (divisão por item).")


class AdjustmentOut(BaseModel):
    type: str = Field(description="discount | cashback | tax | tip | shipping | rounding | other")
    amount: MoneyOut = Field(description="Com sinal: negativo reduz o total.")
    description: Optional[str] = None


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: Optional[Ref] = None
    uploaded_on: Optional[dt.date] = None


class PurchaseOut(BaseModel):
    """A compra INTEIRA de um lançamento parcelado: os itens aparecem uma vez só."""

    group_id: str
    title: str
    amount: MoneyOut = Field(description="Total da compra (soma das parcelas vivas).")
    currency: str
    installments: int
    paid_installments: int = Field(description="Parcelas já pagas.")
    split: List[PersonAmount] = Field(default_factory=list, description="Quem deve quanto da compra inteira.")
    my_share: MoneyOut
    items: List[ItemOut] = Field(default_factory=list)


class TransactionOut(BaseModel):
    id: int
    space: Ref
    title: str
    description: Optional[str] = None
    date: dt.date
    billing_month: Optional[str] = Field(None, description="Competência (YYYY-MM).")
    amount: MoneyOut
    currency: str
    status: str = Field(description="draft | pending | confirmed | paid | cancelled")
    settled: bool = Field(description="O dinheiro já saiu (ADR 0029). Compra no cartão se paga pela fatura.")
    settled_on: Optional[dt.date] = None
    payment_method: Optional[str] = None
    card: Optional[Ref] = None
    statement: Optional[StatementRef] = None
    category: Optional[Ref] = Field(None, description="Categoria única; ver `categories` quando há várias.")
    categories: List[Ref] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    installment: Optional[InstallmentInfo] = None
    split_mode: str = Field("transaction", description="transaction = divisão do total; item = cada item tem a sua.")
    payers: List[PersonAmount] = Field(default_factory=list)
    split: List[PersonAmount] = Field(default_factory=list, description="Quem deve quanto desta despesa.")
    my_share: MoneyOut = Field(description="A sua parte nesta despesa.")
    items: List[ItemOut] = Field(default_factory=list, description="Itens da nota. Vazio = sem itens detalhados.")
    adjustments: List[AdjustmentOut] = Field(default_factory=list, description="Desconto, frete, taxa… da nota.")
    purchase: Optional[PurchaseOut] = Field(None, description="Parcelado: a compra inteira.")
    created_by: Optional[Ref] = None
    foreign: Optional[ForeignInfo] = None
    attachments: int = 0
    files: List[AttachmentOut] = Field(default_factory=list, description="Anexos (recibos). Conteúdo: attachments_get.")
    version: str = Field("", description="Versão do estado; mande em `expected_version` ao editar.")
    app_url: str


class TransactionBrief(BaseModel):
    """Linha de listagem: o essencial para reconhecer e agir sobre o lançamento."""

    id: int
    space: Ref
    date: dt.date
    title: str
    amount: MoneyOut
    currency: str
    my_share: MoneyOut
    status: str
    settled: bool
    payment_method: Optional[str] = None
    card: Optional[str] = None
    category: Optional[str] = None
    installment: Optional[str] = Field(None, description="\"3/10\" quando parcelado.")
    tags: List[str] = Field(default_factory=list)


class MoneyTotal(BaseModel):
    currency: str
    amount: MoneyOut
    count: int


class SpaceOut(BaseModel):
    id: int
    name: str
    base_currency: str
    my_role: str = Field(description="viewer | member | admin | owner")
    full_access: bool = Field(description="Vê os números da casa inteira (senão, só o que te envolve).")
    members: int
    personal: bool = Field(description="Só você é membro.")
