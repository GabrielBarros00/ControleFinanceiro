"""O que o COMPONENTE precisa além dos dados: opções do editor, permissão, desfazer.

Vai no `_meta` do resultado, que o modelo não lê: o catálogo e as respostas
continuam enxutos para ele, e o componente ganha o que precisa para a pessoa editar
ali mesmo sem outra chamada.

- `form`: o vocabulário do espaço do lançamento — categorias, tags, cartões e
  contas DA PESSOA, as pessoas do espaço e as formas de pagamento. É a mesma
  resolução das tools (`resolve`), então o componente nunca oferece o que a tool
  recusaria.
- `can_edit`: o papel no espaço, a regra de quem edita o quê (`can_write`) e o
  escopo da conexão. O componente esconde o botão em vez de deixar a pessoa
  descobrir pelo erro.
- `undo`: a tool e os argumentos que desfazem a ação. O componente só chama; a
  permissão e a regra continuam no servidor, na hora do clique.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import select

from app.api.deps import get_workspace_membership
from app.domain.access_policy import can_write
from app.mcp import resolve
from app.mcp.registry import ToolCall
from app.models.credit_card import CreditCard
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceRole, role_level
from app.services.oauth import scopes as escopos

FORMAS = ("credit_card", "debit_card", "pix", "cash", "bank_transfer", "boleto", "other")


def form_for_space(call: ToolCall, workspace_id: int) -> dict[str, Any]:
    me = call.identity.user_id
    return {
        "space_id": workspace_id,
        "categories": [{"id": c.id, "name": c.name} for c in resolve.space_categories(call.session, workspace_id)],
        "tags": [{"id": t.id, "name": t.name} for t in resolve.space_tags(call.session, workspace_id)],
        "cards": [
            {"id": c.id, "name": c.name}
            for c in call.session.exec(
                select(CreditCard).where(CreditCard.owner_user_id == me, CreditCard.deleted_at.is_(None))
                .order_by(CreditCard.name)
            ).all()
        ],
        "accounts": [
            {"id": a.id, "name": a.name, "currency": a.currency}
            for a in call.session.exec(
                select(PaymentAccount).where(
                    PaymentAccount.owner_user_id == me, PaymentAccount.deleted_at.is_(None), PaymentAccount.active.is_(True),
                ).order_by(PaymentAccount.name)
            ).all()
        ],
        "people": [{"id": m.id, "name": m.name, "me": m.id == me} for m in resolve.space_members(call.session, workspace_id)],
        "payment_methods": list(FORMAS),
    }


def my_accounts(call: ToolCall) -> list[dict[str, Any]]:
    return [
        {"id": a.id, "name": a.name, "currency": a.currency}
        for a in call.session.exec(
            select(PaymentAccount).where(
                PaymentAccount.owner_user_id == call.identity.user_id,
                PaymentAccount.deleted_at.is_(None), PaymentAccount.active.is_(True),
            ).order_by(PaymentAccount.name)
        ).all()
    ]


def can_edit_transaction(call: ToolCall, tx: Transaction) -> bool:
    if not call.identity.has(escopos.TRANSACTIONS_WRITE):
        return False
    try:
        membership = get_workspace_membership(tx.workspace_id, session=call.session, current_user=call.user)
    except Exception:  # noqa: BLE001 — sem membership, sem edição
        return False
    if role_level(membership.role) < role_level(WorkspaceRole.member):
        return False
    return can_write(tx.created_by_user_id, membership)


def undo(tool: str, args: dict[str, Any], label: str = "Desfazer") -> dict[str, Any]:
    return {"tool": tool, "args": args, "label": label}


def transaction_meta(
    call: ToolCall, tx: Transaction, *, mode: str, app_url: str, undo_action: Optional[dict] = None,
) -> dict[str, Any]:
    """O `_meta` de um lançamento desenhado (lido, criado, editado, excluído, restaurado)."""
    pode = can_edit_transaction(call, tx)
    meta: dict[str, Any] = {"view": "transaction", "mode": mode, "app_url": app_url, "can_edit": pode}
    if pode and mode != "deleted":
        meta["form"] = form_for_space(call, tx.workspace_id)
    if undo_action and pode:
        meta["undo"] = undo_action
    return meta
