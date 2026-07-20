from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.domain.money import Money, MoneyError
from app.models.category import Category
from app.models.payment_account import PaymentAccount
from app.models.transaction import (
    SplitMethod,
    SplitMode,
    Transaction,
    TransactionAdjustment,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.workspace import WorkspaceMembership
from app.schemas.transaction import (
    TransactionAdjustmentCreate,
    TransactionItemCreate,
    TransactionPayerBase,
    TransactionSplitBase,
)
from app.services.item_split_service import ItemSplitService
from app.services.split_service import SplitService


# Máquina de estados (ADR 0003): draft→pending→confirmed→paid, *→cancelled
# (exceto paid, que exige reabertura), paid→confirmed = reabrir. Cancelled é
# terminal. Timestamps são carimbados por listener no modelo.
ALLOWED_STATUS_TRANSITIONS = {
    TransactionStatus.draft: {
        TransactionStatus.pending, TransactionStatus.confirmed, TransactionStatus.cancelled,
    },
    TransactionStatus.pending: {
        TransactionStatus.confirmed, TransactionStatus.cancelled,
    },
    TransactionStatus.confirmed: {
        TransactionStatus.paid, TransactionStatus.cancelled,
    },
    TransactionStatus.paid: {TransactionStatus.confirmed},
    TransactionStatus.cancelled: set(),
}


def validate_status_transition(
    current: TransactionStatus, new: TransactionStatus
) -> None:
    """Levanta ValueError (PT-BR) para transições fora da máquina de estados."""
    if new == current:
        return
    if new not in ALLOWED_STATUS_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Transição de status inválida: {current.value} → {new.value}"
        )


def _workspace_member_ids(session: Session, workspace_id: int) -> set:
    rows = session.exec(
        select(WorkspaceMembership.user_id).where(
            WorkspaceMembership.workspace_id == workspace_id
        )
    ).all()
    return set(rows)


def _ensure_members(session: Session, workspace_id: int, user_ids: set) -> None:
    outsiders = user_ids - _workspace_member_ids(session, workspace_id)
    if outsiders:
        raise ValueError(
            f"Usuário(s) {sorted(outsiders)} não pertence(m) a este workspace"
        )


def _validate_categories(
    session: Session, workspace_id: int, items: List[TransactionItemCreate]
) -> None:
    for item in items:
        if item.category_id is None:
            continue
        category = session.get(Category, item.category_id)
        if not category or category.workspace_id != workspace_id or category.deleted_at:
            raise ValueError(f"Categoria inválida para este workspace (item '{item.title}')")


def _validate_payer_accounts(
    session: Session, workspace_id: int, payers: List[TransactionPayerBase]
) -> None:
    """Conta informada por um pagador precisa existir, ser deste workspace e
    estar ativa (ADR 0004). Cartão de crédito não usa conta — validado no
    schema (validate_payer_origins)."""
    account_ids = {p.account_id for p in payers if p.account_id is not None}
    for account_id in sorted(account_ids):
        account = session.get(PaymentAccount, account_id)
        if not account or account.workspace_id != workspace_id or account.deleted_at:
            raise ValueError("Conta inválida para este workspace")
        if not account.active:
            raise ValueError(f"Conta '{account.name}' está desativada")


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value())


def _allocate_proportional(amount_cents: int, weights: Dict[int, int]) -> Dict[int, int]:
    """Rateia amount_cents (qualquer sinal) proporcionalmente aos pesos, em
    centavos inteiros: piso por participante e resto 1 centavo por vez aos
    primeiros em ordem de user_id (mesmo princípio do ADR 0001)."""
    total_weight = sum(weights.values())
    ordered = sorted(weights)
    floors = {
        uid: (amount_cents * weights[uid]) // total_weight
        for uid in ordered
    }
    remainder = amount_cents - sum(floors.values())  # 0 <= resto < N (piso)
    for uid in ordered:
        if remainder <= 0:
            break
        floors[uid] += 1
        remainder -= 1
    return floors


def compute_transaction_breakdown(
    session: Session,
    workspace_id: int,
    *,
    total_amount: Decimal,
    split_mode: SplitMode,
    payers: List[TransactionPayerBase],
    splits: List[TransactionSplitBase],
    items: Optional[List[TransactionItemCreate]],
    adjustments: Optional[List[TransactionAdjustmentCreate]] = None,
) -> Dict[str, Any]:
    """Valida invariantes e calcula a divisão SEM persistir nada.

    Fonte única de verdade do cálculo: o persist grava exatamente este
    resultado e o endpoint de preview o devolve ao cliente. Levanta
    ValueError com mensagem PT-BR em qualquer inconsistência.
    """
    adjustments = adjustments or []

    # 1) Pagadores fecham o total
    payer_total = sum(p.amount for p in payers)
    if payer_total != total_amount:
        raise ValueError(
            f"Soma dos pagadores ({payer_total}) difere do total ({total_amount})"
        )

    # 2) Reconciliação com o documento: total = itens + ajustes (ADR de ajustes)
    adjustments_total = sum(a.amount for a in adjustments)
    if adjustments and not items:
        raise ValueError(
            "Ajustes reconciliam itens com o total — informe os itens da despesa"
        )
    if items:
        items_total = sum(i.amount for i in items)
        if items_total + adjustments_total != total_amount:
            if adjustments:
                raise ValueError(
                    f"Itens ({items_total}) + ajustes ({adjustments_total}) "
                    f"não fecham o total ({total_amount})"
                )
            raise ValueError(
                f"Soma dos itens ({items_total}) difere do total ({total_amount})"
            )
        _validate_categories(session, workspace_id, items)

    # 3) Todos os envolvidos são membros do workspace
    involved = {p.user_id for p in payers} | {s.user_id for s in splits}
    for item in items or []:
        involved |= {sh.user_id for sh in item.shares or []}
    _ensure_members(session, workspace_id, involved)

    # 3b) Origem do dinheiro por pagador (ADR 0004)
    _validate_payer_accounts(session, workspace_id, payers)

    result: Dict[str, Any] = {
        "payers": [p.model_dump() for p in payers],
        "adjustments": [a.model_dump() for a in adjustments],
        "items": [],
        "splits": [],
    }

    if split_mode == SplitMode.transaction:
        method = splits[0].split_method
        try:
            computed = SplitService.calculate_splits(
                total_amount=Money(total_amount),
                method=method,
                user_ids=[s.user_id for s in splits] if method == SplitMethod.equal else None,
                input_data=[{"user_id": s.user_id, "value": s.input_value} for s in splits],
            )
        except (MoneyError, ValueError) as exc:
            raise ValueError(f"Divisão inválida: {exc}") from exc

        input_by_user = {s.user_id: s.input_value for s in splits}
        result["items"] = [
            {**item.model_dump(exclude={"shares"}), "shares": []}
            for item in items or []
        ]
        result["splits"] = [
            {
                "user_id": c["user_id"],
                "split_method": method,
                "input_value": input_by_user[c["user_id"]],
                "computed_amount": c["amount"],
            }
            for c in computed
        ]
        return result

    # ------- split_mode == item: shares por item + splits derivados -------
    for item_in in items or []:
        shares = [sh.model_dump() for sh in item_in.shares or []]
        try:
            computed_shares = ItemSplitService.compute_item_shares(
                item_title=item_in.title,
                item_amount=Money(item_in.amount),
                shares=shares,
            )
        except (MoneyError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

        by_user = {sh["user_id"]: sh for sh in shares}
        result["items"].append({
            **item_in.model_dump(exclude={"shares"}),
            "shares": [
                {
                    "user_id": c["user_id"],
                    "split_method": by_user[c["user_id"]]["split_method"],
                    "input_value": by_user[c["user_id"]]["input_value"],
                    "computed_amount": c["amount"],
                }
                for c in computed_shares
            ],
        })

    derived = ItemSplitService.derive_transaction_splits([
        [
            {"user_id": sh["user_id"], "amount": sh["computed_amount"]}
            for sh in item["shares"]
        ]
        for item in result["items"]
    ])

    # Ajustes (desconto/frete/etc.) são rateados proporcionalmente ao
    # subtotal de itens de cada participante, em centavos exatos
    if adjustments:
        weights = {d["user_id"]: _cents(d["amount"]) for d in derived}
        if sum(weights.values()) <= 0:
            raise ValueError("Com ajustes, os itens devem somar mais que zero")
        allocation = _allocate_proportional(_cents(adjustments_total), weights)
        derived = [
            {
                "user_id": d["user_id"],
                "amount": d["amount"] + Decimal(allocation[d["user_id"]]) / 100,
            }
            for d in derived
        ]
        if any(d["amount"] < 0 for d in derived):
            raise ValueError(
                "Ajustes deixariam um participante com valor negativo — revise os valores"
            )

    # Invariante por construção; check defensivo
    derived_total = sum(d["amount"] for d in derived)
    if derived_total != total_amount:
        raise ValueError(
            f"Divisão por itens somou {derived_total}, difere do total ({total_amount})"
        )

    # Derivados persistem como 'fixed' com input==computed: o DebtService lê só
    # computed_amount e o frontend distingue derivados via split_mode='item'
    result["splits"] = [
        {
            "user_id": d["user_id"],
            "split_method": SplitMethod.fixed,
            "input_value": d["amount"],
            "computed_amount": d["amount"],
        }
        for d in derived
    ]
    return result


def persist_transaction_children(
    session: Session,
    workspace_id: int,
    db_transaction: Transaction,
    *,
    total_amount: Decimal,
    split_mode: SplitMode,
    payers: List[TransactionPayerBase],
    splits: List[TransactionSplitBase],
    items: Optional[List[TransactionItemCreate]],
    adjustments: Optional[List[TransactionAdjustmentCreate]] = None,
) -> None:
    """Grava payers/splits/items(+shares)/ajustes calculados pelo
    compute_transaction_breakdown (mesma fonte de verdade do preview).

    Pressupõe db_transaction já com id (flush prévio) e a estrutura já
    validada (validate_split_structure). O chamador converte ValueError em
    400 e faz rollback — criação/edição atômica (ADR 0010).
    """
    breakdown = compute_transaction_breakdown(
        session,
        workspace_id,
        total_amount=total_amount,
        split_mode=split_mode,
        payers=payers,
        splits=splits,
        items=items,
        adjustments=adjustments,
    )

    for p in breakdown["payers"]:
        session.add(TransactionPayer(**p, transaction_id=db_transaction.id))

    for a in breakdown["adjustments"]:
        session.add(TransactionAdjustment(**a, transaction_id=db_transaction.id))

    db_items: List[TransactionItem] = []
    for item in breakdown["items"]:
        db_item = TransactionItem(
            **{k: v for k, v in item.items() if k != "shares"},
            transaction_id=db_transaction.id,
        )
        session.add(db_item)
        db_items.append(db_item)

    if any(item["shares"] for item in breakdown["items"]):
        session.flush()  # ids dos itens para as FKs das shares
        for item, db_item in zip(breakdown["items"], db_items):
            for share in item["shares"]:
                session.add(TransactionItemShare(**share, item_id=db_item.id))

    for split in breakdown["splits"]:
        session.add(
            TransactionSplit(**split, transaction_id=db_transaction.id)
        )


def delete_transaction_children(session: Session, transaction_id: int) -> None:
    """Remove shares → items → payers → splits → ajustes via ORM (preserva a
    trilha de auditoria — os listeners são de Mapper, bulk delete os pularia)."""
    items = session.exec(
        select(TransactionItem).where(TransactionItem.transaction_id == transaction_id)
    ).all()
    item_ids = [i.id for i in items]
    if item_ids:
        for share in session.exec(
            select(TransactionItemShare).where(TransactionItemShare.item_id.in_(item_ids))
        ).all():
            session.delete(share)
    for item in items:
        session.delete(item)
    for payer in session.exec(
        select(TransactionPayer).where(TransactionPayer.transaction_id == transaction_id)
    ).all():
        session.delete(payer)
    for split in session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)
    ).all():
        session.delete(split)
    for adjustment in session.exec(
        select(TransactionAdjustment).where(
            TransactionAdjustment.transaction_id == transaction_id
        )
    ).all():
        session.delete(adjustment)
