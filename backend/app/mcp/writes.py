"""Peças comuns das tools de ESCRITA: chave de idempotência, papel no espaço e divisão.

A divisão é a parte delicada. O modelo fala em pessoas ("metade é do João"); o
comando do app fala em `payers`/`splits` com `user_id`. A tradução mora aqui, uma
vez, com três regras que não se negociam:

- **Quem pagou e quem divide são resolvidos por nome DENTRO do espaço** do
  lançamento. Nome ambíguo → `AMBIGUOUS` com candidatos; nunca um palpite.
- **O servidor calcula os centavos.** A tool recebe "partes iguais", valores ou
  percentuais; quem fatia o total é o mesmo `compute_transaction_breakdown` do
  app (ADR 0001) — o modelo nunca manda o resultado de uma conta.
- **Sem divisão informada, a despesa é de quem pagou — se foi você.** Quando
  outra pessoa pagou, "de quem é" não tem resposta óbvia, e a tool exige
  `split_with` ou `split` em vez de supor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, List, Optional

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlmodel import Session

from app.api.deps import get_workspace_membership
from app.mcp import resolve
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, PercentIn
from app.mcp.registry import ToolCall, ToolInput
from app.models.transaction import SplitMethod
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.schemas.transaction import TransactionPayerBase, TransactionSplitBase

IdempotencyKey = Annotated[
    str,
    Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description=(
            "UUID novo por pedido. Repita a MESMA chave só ao reenviar a mesma chamada após erro "
            "de rede: nada é criado em dobro."
        ),
    ),
]

ConfirmationToken = Annotated[
    str,
    Field(
        min_length=20,
        max_length=128,
        pattern=r"^cfm_cf_[A-Za-z0-9_-]+$",
        description="O `confirmation_token` devolvido pela prévia (transactions_bulk_preview).",
    ),
]


# --- Papel no espaço ------------------------------------------------------------

def assert_can_write_in(membership: WorkspaceMembership) -> None:
    """O `require_role(member)` das rotas de escrita: `viewer` só lê."""
    if role_level(membership.role) < role_level(WorkspaceRole.member):
        raise McpToolError(
            ErrorCode.PERMISSION_DENIED,
            "Seu papel neste espaço é somente leitura — peça a um administrador para mudar seu papel.",
        )


def membership_for_write(call: ToolCall, workspace_id: int) -> WorkspaceMembership:
    """Membership de quem chama no espaço, já com o papel de escrita conferido.

    Espaço de que a pessoa não participa responde NOT_FOUND (como o REST, que
    não distingue "não existe" de "não é seu").
    """
    try:
        membership = get_workspace_membership(workspace_id, session=call.session, current_user=call.user)
    except HTTPException:
        raise McpToolError(ErrorCode.NOT_FOUND, "Espaço não encontrado.", details={"space_id": workspace_id})
    assert_can_write_in(membership)
    return membership


# --- Divisão --------------------------------------------------------------------

class ShareIn(ToolInput):
    """A parte de UMA pessoa numa divisão desigual. Valor OU percentual."""

    person: Optional[str] = Field(None, max_length=120, description="Nome da pessoa (ou \"eu\").")
    person_id: Optional[int] = None
    amount: Optional[MoneyIn] = Field(None, description="Valor fixo da parte desta pessoa.")
    percent: Optional[PercentIn] = Field(None, description="Percentual do total desta pessoa.")

    @model_validator(mode="after")
    def _um_de_cada(self):
        if (self.person is None) == (self.person_id is None):
            raise ValueError("informe exatamente um de person ou person_id em cada parte")
        if (self.amount is None) == (self.percent is None):
            raise ValueError("informe exatamente um de amount ou percent em cada parte")
        return self


class DivisionIn(ToolInput):
    """Quem pagou e como a despesa se divide. Tudo opcional: sem nada, é sua e você pagou."""

    paid_by: Optional[str] = Field(
        None, max_length=120,
        description="Quem pagou (nome de um membro do espaço). Omitido = você.",
    )
    paid_by_id: Optional[int] = None
    account: Optional[str] = Field(
        None, max_length=120,
        description="Conta de onde saiu o dinheiro (só quando quem pagou foi você; não use para cartão).",
    )
    account_id: Optional[int] = None
    split_with: Optional[List[str]] = Field(
        None, max_length=20,
        description=(
            "Divide em partes IGUAIS entre você e estas pessoas (nomes de membros do espaço). "
            "Ex.: [\"João\"] = metade sua, metade do João."
        ),
    )
    split_with_ids: Optional[List[int]] = Field(None, max_length=20)
    split: Optional[List[ShareIn]] = Field(
        None, min_length=1, max_length=20,
        description=(
            "Divisão desigual: a parte de CADA participante (inclua você, se tiver parte). "
            "Todas por valor (somando o total) ou todas por percentual (somando 100)."
        ),
    )

    @model_validator(mode="after")
    def _divisao_coerente(self):
        if (self.split_with or self.split_with_ids) and self.split:
            raise ValueError("use split_with (partes iguais) OU split (partes desiguais), não os dois")
        if self.split:
            tipos = {"amount" if s.amount is not None else "percent" for s in self.split}
            if len(tipos) > 1:
                raise ValueError("em split, use valor em todas as partes ou percentual em todas")
        if self.paid_by is not None and self.paid_by_id is not None:
            raise ValueError("informe paid_by ou paid_by_id, não os dois")
        if self.account is not None and self.account_id is not None:
            raise ValueError("informe account ou account_id, não os dois")
        return self

    def mentions_division(self) -> bool:
        return any(
            v is not None
            for v in (self.paid_by, self.paid_by_id, self.split_with, self.split_with_ids, self.split)
        )

    def people_named(self) -> tuple[list[str], list[int]]:
        """Nomes e ids citados — o que decide o espaço implícito."""
        nomes = [n for n in (self.split_with or [])]
        ids = list(self.split_with_ids or [])
        for parte in self.split or []:
            if parte.person is not None:
                nomes.append(parte.person)
            else:
                ids.append(parte.person_id)
        if self.paid_by:
            nomes.append(self.paid_by)
        if self.paid_by_id is not None:
            ids.append(self.paid_by_id)
        return nomes, ids


@dataclass
class Division:
    payers: list[TransactionPayerBase]
    splits: list[TransactionSplitBase]
    payer: resolve.Match
    participants: list[resolve.Match] = field(default_factory=list)
    account: Optional[resolve.Match] = None


def build_division(
    session: Session, workspace_id: int, me_id: int, d: DivisionIn, total: Decimal,
    *, items_have_division: bool = False,
) -> Division:
    """Pagador e divisão do total.

    `items_have_division`: todos os itens da nota trazem a própria divisão, então
    o total não precisa de uma (e outra pessoa pode ter pago sem que a tool exija
    `split_with`). Os itens resolvem as partes em `app/mcp/items.py`.
    """
    membros = resolve.space_members(session, workspace_id)

    def pessoa(nome: Optional[str], pid: Optional[int]) -> resolve.Match:
        return resolve.resolve_person(
            session, workspace_id=workspace_id, me_id=me_id, person=nome, person_id=pid, members=membros
        )

    eu = next((m for m in membros if m.id == me_id), None)
    if eu is None:  # pragma: no cover — membership já conferido antes
        raise McpToolError(ErrorCode.NOT_FOUND, "Espaço não encontrado.")
    pagador = eu if (d.paid_by is None and d.paid_by_id is None) else pessoa(d.paid_by, d.paid_by_id)

    conta = None
    if d.account is not None or d.account_id is not None:
        if pagador.id != me_id:
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                "A conta só pode ser informada quando foi você quem pagou — a conta de outra pessoa é dela.",
            )
        c = resolve.resolve_account(session, me_id, account_id=d.account_id, account=d.account)
        conta = resolve.Match(c.id, c.name, {"currency": c.currency})

    participantes: list[resolve.Match] = []
    splits: list[TransactionSplitBase] = []
    if d.split_with or d.split_with_ids:
        vistos: dict[int, resolve.Match] = {eu.id: eu}
        for nome in d.split_with or []:
            m = pessoa(nome, None)
            vistos.setdefault(m.id, m)
        for pid in d.split_with_ids or []:
            m = pessoa(None, pid)
            vistos.setdefault(m.id, m)
        participantes = list(vistos.values())
        splits = [
            TransactionSplitBase(user_id=m.id, split_method=SplitMethod.equal, input_value=Decimal("0"))
            for m in participantes
        ]
    elif d.split:
        vistos_ids: set[int] = set()
        for parte in d.split:
            m = pessoa(parte.person, parte.person_id)
            if m.id in vistos_ids:
                raise McpToolError(ErrorCode.VALIDATION_ERROR, f"{m.name} aparece duas vezes na divisão.")
            vistos_ids.add(m.id)
            participantes.append(m)
            if parte.amount is not None:
                splits.append(TransactionSplitBase(user_id=m.id, split_method=SplitMethod.fixed, input_value=parte.amount))
            else:
                splits.append(TransactionSplitBase(user_id=m.id, split_method=SplitMethod.percentage, input_value=parte.percent))
    elif items_have_division:
        participantes, splits = [], []
    else:
        if pagador.id != me_id:
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{pagador.name} pagou: informe de quem é a despesa com `split_with` (partes iguais) "
                "ou `split` (partes desiguais). Pergunte ao usuário se não estiver claro.",
            )
        participantes = [eu]
        splits = [TransactionSplitBase(user_id=me_id, split_method=SplitMethod.equal, input_value=Decimal("0"))]

    payers = [TransactionPayerBase(user_id=pagador.id, amount=total, account_id=conta.id if conta else None)]
    return Division(payers=payers, splits=splits, payer=pagador, participants=participantes, account=conta)
