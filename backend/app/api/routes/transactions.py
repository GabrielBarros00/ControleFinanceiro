from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from typing import List, Optional
from decimal import Decimal
import math
import datetime
import uuid

from app.db.session import get_session
from app.domain.dates import add_months
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionItem,
    TransactionStatus,
    SplitMethod,
    SplitMode,
    PaymentMethod,
)
from app.schemas.transaction import (
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
    TransactionListResponse,
    normalize_payment_method,
    validate_payer_origins,
    validate_split_structure,
)
from app.api.deps import get_workspace_membership, require_role
from app.domain.money import Money
from app.models.tag import Tag, TransactionTagLink
from app.services.event_service import publish_event
from app.services.transaction_service import (
    compute_transaction_breakdown,
    delete_transaction_children,
    persist_transaction_children,
    validate_status_transition,
)
from app.services.credit_card_service import CreditCardService
from app.models.credit_card import CreditCard

router = APIRouter(prefix="/workspaces/{workspace_id}/transactions", tags=["transactions"])

# Campos do TransactionUpdate que disparam a edição COMPLETA da divisão
FULL_EDIT_KEYS = {"payers", "splits", "items", "split_mode", "adjustments"}


def _set_transaction_tags(
    session: Session, workspace_id: int, transaction_id: int, tag_ids: List[int]
) -> None:
    """Substitui os vínculos de tag da transação (valida workspace)."""
    unique_ids = list(dict.fromkeys(tag_ids))
    tags = []
    if unique_ids:
        tags = session.exec(
            select(Tag).where(
                Tag.id.in_(unique_ids),
                Tag.workspace_id == workspace_id,
                Tag.deleted_at.is_(None),
            )
        ).all()
        if len(tags) != len(unique_ids):
            raise HTTPException(status_code=400, detail="Tag inválida para este workspace")

    for link in session.exec(
        select(TransactionTagLink).where(TransactionTagLink.transaction_id == transaction_id)
    ).all():
        session.delete(link)
    for tag in tags:
        session.add(TransactionTagLink(transaction_id=transaction_id, tag_id=tag.id))


def _add_months(dt: datetime.datetime, months: int) -> datetime.datetime:
    """Avança meses de calendário (util compartilhado — ADR 0012)."""
    return add_months(dt, months)


def _ensure_not_paid(db_transaction: Transaction, update_keys: Optional[set] = None):
    """Despesa paga é imutável até ser reaberta (PUT contendo apenas status)."""
    if db_transaction.status != TransactionStatus.paid:
        return
    if update_keys is not None and not (update_keys - {"status"}):
        return  # reabertura: só muda o status
    raise HTTPException(
        status_code=409,
        detail="Despesa paga não pode ser alterada: reabra antes (altere apenas o status)",
    )


def _ensure_not_cancelled(db_transaction: Transaction):
    """Cancelada é terminal (ADR 0003): nenhuma edição, nenhuma transição."""
    if db_transaction.status == TransactionStatus.cancelled:
        raise HTTPException(
            status_code=409,
            detail="Despesa cancelada é definitiva e não pode ser alterada",
        )


@router.post("/", response_model=TransactionRead)
def create_transaction(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    # Fatura SEMPRE derivada no servidor a partir de cartão + data (ADR 0002)
    statement_id = None
    card = None
    if transaction_in.credit_card_id:
        card = session.get(CreditCard, transaction_in.credit_card_id)
        if not card or card.workspace_id != workspace_id or card.deleted_at:
            raise HTTPException(status_code=400, detail="Cartão de crédito inválido para este workspace")

    # Parcelamento: N transações irmãs, uma por mês/fatura
    if transaction_in.installments_count and transaction_in.installments_count > 1:
        return _create_installments(session, workspace_id, transaction_in, membership, card)

    if card:
        statement = CreditCardService.get_or_create_statement(session, card, transaction_in.transaction_date)
        statement_id = statement.id

    # Create Transaction
    transaction_data = transaction_in.model_dump(
        exclude={"payers", "splits", "items", "adjustments", "tag_ids", "installments_count"}
    )
    if not transaction_data.get("billing_month"):
        transaction_data["billing_month"] = transaction_in.transaction_date.strftime("%Y-%m")

    db_transaction = Transaction(
        **transaction_data,
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
        statement_id=statement_id
    )
    session.add(db_transaction)
    # flush (não commit): mantém a criação ATÔMICA — se payers/splits/itens
    # falharem na validação, o rollback descarta tudo, sem transação órfã
    session.flush()

    try:
        persist_transaction_children(
            session,
            workspace_id,
            db_transaction,
            total_amount=transaction_in.total_amount,
            split_mode=transaction_in.split_mode,
            payers=transaction_in.payers,
            splits=transaction_in.splits,
            items=transaction_in.items,
            adjustments=transaction_in.adjustments,
        )
    except ValueError as exc:
        # Divisão/somas inválidas é erro do cliente — nunca 500. Rollback
        # descarta a transação inteira (atômica).
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    if transaction_in.tag_ids is not None:
        _set_transaction_tags(session, workspace_id, db_transaction.id, transaction_in.tag_ids)

    publish_event(session, workspace_id, "transaction.created", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


def _create_installments(
    session: Session,
    workspace_id: int,
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership,
    card: Optional[CreditCard],
):
    """Cria N transações irmãs (i/N) com valores split_equal do total, cada uma
    roteada para a fatura do seu mês. Atômico: qualquer falha descarta tudo."""
    count = transaction_in.installments_count
    amounts = Money(transaction_in.total_amount).split_equal(count)
    group_id = uuid.uuid4().hex
    payer = transaction_in.payers[0]

    base_data = transaction_in.model_dump(exclude={
        "payers", "splits", "items", "adjustments", "tag_ids", "installments_count",
        "title", "total_amount", "transaction_date", "billing_month",
    })

    first_tx = None
    try:
        for i in range(count):
            inst_amount = amounts[i].amount
            inst_date = _add_months(transaction_in.transaction_date, i)

            statement_id = None
            if card:
                statement = CreditCardService.get_or_create_statement(session, card, inst_date)
                statement_id = statement.id

            db_transaction = Transaction(
                **base_data,
                title=f"{transaction_in.title} ({i + 1}/{count})",
                total_amount=inst_amount,
                transaction_date=inst_date,
                billing_month=inst_date.strftime("%Y-%m"),
                workspace_id=workspace_id,
                created_by_user_id=membership.user_id,
                statement_id=statement_id,
                installment_no=i + 1,
                installments_of=count,
                installment_group_id=group_id,
            )
            session.add(db_transaction)
            session.flush()

            # Item-categoria único (se houver) escala junto com a parcela
            items = None
            if transaction_in.items:
                template = transaction_in.items[0]
                items = [template.model_copy(update={
                    "title": db_transaction.title,
                    "amount": inst_amount,
                    "quantity": Decimal("1"),
                    "unit_amount": None,
                })]

            persist_transaction_children(
                session,
                workspace_id,
                db_transaction,
                total_amount=inst_amount,
                split_mode=transaction_in.split_mode,
                payers=[payer.model_copy(update={"amount": inst_amount})],
                splits=transaction_in.splits,  # equal/percentage escalam por natureza
                items=items,
            )

            if transaction_in.tag_ids is not None:
                _set_transaction_tags(session, workspace_id, db_transaction.id, transaction_in.tag_ids)

            if first_tx is None:
                first_tx = db_transaction
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    # Evento ÚNICO agregado — N parcelas não podem virar N refetches
    publish_event(session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id)
    session.commit()
    session.refresh(first_tx)
    return first_tx

@router.post("/preview")
def preview_transaction(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Dry-run da criação: devolve a divisão calculada (splits, shares por
    item, rateio de ajustes) SEM persistir — mesma fonte de verdade do POST
    (compute_transaction_breakdown), então o que o preview mostra é
    exatamente o que será gravado."""
    try:
        breakdown = compute_transaction_breakdown(
            session,
            workspace_id,
            total_amount=transaction_in.total_amount,
            split_mode=transaction_in.split_mode,
            payers=transaction_in.payers,
            splits=transaction_in.splits,
            items=transaction_in.items,
            adjustments=transaction_in.adjustments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return breakdown


@router.get("/", response_model=TransactionListResponse)
def list_transactions(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
    limit: int = Query(10, ge=1, le=100),
    page: int = Query(1, ge=1),
    month: Optional[str] = None, # Formato YYYY-MM
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    payment_method: Optional[PaymentMethod] = None,
    tag_id: Optional[int] = None
):
    offset = (page - 1) * limit

    # Base query
    statement = select(Transaction).where(
        Transaction.workspace_id == workspace_id,
        Transaction.deleted_at.is_(None)
    )

    # Filtering by month
    if month:
        statement = statement.where(Transaction.billing_month == month)

    # Filtering by search
    if search:
        statement = statement.where(Transaction.title.contains(search))

    # Filtering by category (via items)
    if category_id:
        statement = statement.join(TransactionItem).where(TransactionItem.category_id == category_id)

    # Filtering by payment method
    if payment_method:
        statement = statement.where(Transaction.payment_method == payment_method)

    # Filtering by tag
    if tag_id:
        statement = statement.join(TransactionTagLink).where(TransactionTagLink.tag_id == tag_id)

    # Count total
    count_statement = select(func.count()).select_from(statement.subquery())
    total = session.exec(count_statement).one()

    # Final statement with ordering and pagination
    statement = statement.order_by(Transaction.transaction_date.desc()).offset(offset).limit(limit)
    transactions = session.exec(statement).all()

    return {
        "items": transactions,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": math.ceil(total / limit) if total > 0 else 1
    }

@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    transaction = session.get(Transaction, transaction_id)
    if not transaction or transaction.workspace_id != workspace_id or transaction.deleted_at:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return transaction

@router.put("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    workspace_id: int,
    transaction_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionUpdate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    db_transaction = session.get(Transaction, transaction_id)
    if not db_transaction or db_transaction.workspace_id != workspace_id or db_transaction.deleted_at:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Member edita apenas os próprios lançamentos; admin+ edita qualquer um
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and db_transaction.created_by_user_id not in (None, membership.user_id)
    ):
        raise HTTPException(status_code=403, detail="Você só pode editar os próprios lançamentos")

    update_data = transaction_in.model_dump(exclude_unset=True)

    _ensure_not_cancelled(db_transaction)
    _ensure_not_paid(db_transaction, set(update_data.keys()))

    # Máquina de estados (ADR 0003)
    if "status" in update_data:
        try:
            validate_status_transition(db_transaction.status, update_data["status"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    # Tags: substituição dos vínculos vale nos dois caminhos (parcial e full)
    tag_ids = update_data.pop("tag_ids", None)
    if tag_ids is not None:
        _set_transaction_tags(session, workspace_id, db_transaction.id, tag_ids)

    # Mudou a data sem informar billing_month explicitamente? Recalcula —
    # senão a transação some do filtro do mês novo e continua no antigo
    if "transaction_date" in update_data and "billing_month" not in update_data:
        update_data["billing_month"] = update_data["transaction_date"].strftime("%Y-%m")

    # Coerência método de pagamento × cartão contra o estado EFETIVO
    if "payment_method" in update_data or "credit_card_id" in update_data:
        effective_card = update_data.get("credit_card_id", db_transaction.credit_card_id)
        effective_method = update_data.get("payment_method", db_transaction.payment_method)
        try:
            update_data["payment_method"] = normalize_payment_method(effective_method, effective_card)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Reroteamento da fatura (ADR 0002): mudou data ou cartão, a fatura é
    # rederivada no servidor; sem cartão, o vínculo é removido
    if "transaction_date" in update_data or "credit_card_id" in update_data:
        effective_card_id = update_data.get("credit_card_id", db_transaction.credit_card_id)
        if effective_card_id is not None:
            card = session.get(CreditCard, effective_card_id)
            if not card or card.workspace_id != workspace_id or card.deleted_at:
                raise HTTPException(status_code=400, detail="Cartão de crédito inválido para este workspace")
            effective_date = update_data.get("transaction_date", db_transaction.transaction_date)
            statement = CreditCardService.get_or_create_statement(session, card, effective_date)
            update_data["statement_id"] = statement.id
        else:
            update_data["statement_id"] = None

    if FULL_EDIT_KEYS & update_data.keys():
        return _full_edit(session, workspace_id, db_transaction, transaction_in, update_data, membership)

    # ------- Caminho parcial (compatível com clientes antigos) -------

    # Alterar o valor total precisa manter payers/splits consistentes —
    # senão o cálculo de dívidas diverge do total. No caso simples
    # (1 pagador, ≤1 divisão) escala junto; com múltiplos, exige recriar.
    if "total_amount" in update_data and update_data["total_amount"] != db_transaction.total_amount:
        if db_transaction.split_mode == SplitMode.item:
            raise HTTPException(
                status_code=400,
                detail="Despesa dividida por itens: altere o valor editando os itens (edição completa)"
            )
        if db_transaction.adjustments:
            raise HTTPException(
                status_code=400,
                detail="Despesa com ajustes de total: use a edição completa (itens + ajustes)"
            )
        new_total = update_data["total_amount"]
        payers = session.exec(
            select(TransactionPayer).where(TransactionPayer.transaction_id == db_transaction.id)
        ).all()
        splits = session.exec(
            select(TransactionSplit).where(TransactionSplit.transaction_id == db_transaction.id)
        ).all()
        if len(payers) > 1 or len(splits) > 1:
            raise HTTPException(
                status_code=400,
                detail="Transação dividida entre várias pessoas: use a edição completa da divisão"
            )
        for payer in payers:
            payer.amount = new_total
            session.add(payer)
        for split in splits:
            split.computed_amount = new_total
            if split.split_method == SplitMethod.fixed:
                split.input_value = new_total
            session.add(split)

    # Categoria: upsert do item único (modelo simplificado de 1 categoria/transação)
    if "category_id" in update_data:
        category_id = update_data.pop("category_id")
        if category_id is not None:
            from app.models.category import Category
            category = session.get(Category, category_id)
            if not category or category.workspace_id != workspace_id or category.deleted_at:
                raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")
        existing_item = session.exec(
            select(TransactionItem).where(TransactionItem.transaction_id == db_transaction.id)
        ).first()
        if existing_item:
            existing_item.category_id = category_id
            session.add(existing_item)
        elif category_id is not None:
            session.add(TransactionItem(
                transaction_id=db_transaction.id,
                title=update_data.get("title", db_transaction.title),
                amount=update_data.get("total_amount", db_transaction.total_amount),
                category_id=category_id,
            ))

    for key, value in update_data.items():
        setattr(db_transaction, key, value)

    session.add(db_transaction)
    publish_event(session, workspace_id, "transaction.updated", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


def _full_edit(
    session: Session,
    workspace_id: int,
    db_transaction: Transaction,
    transaction_in: TransactionUpdate,
    update_data: dict,
    membership: WorkspaceMembership,
):
    """Substitui payers/splits/items atomicamente (mesmo padrão flush/commit do
    create: qualquer 400 dá rollback e os filhos antigos permanecem)."""
    if transaction_in.payers is None:
        raise HTTPException(
            status_code=400,
            detail="Edição da divisão exige o conjunto completo: payers e splits (ou items)"
        )

    effective_mode = transaction_in.split_mode if transaction_in.split_mode is not None else db_transaction.split_mode
    effective_total = transaction_in.total_amount if transaction_in.total_amount is not None else db_transaction.total_amount
    splits = transaction_in.splits if transaction_in.splits is not None else []
    items = transaction_in.items
    # Conjunto completo: sem o campo, os ajustes anteriores são descartados
    adjustments = transaction_in.adjustments

    try:
        validate_split_structure(effective_mode, splits, items)
        validate_payer_origins(
            transaction_in.payers,
            update_data.get("credit_card_id", db_transaction.credit_card_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    delete_transaction_children(session, db_transaction.id)

    for key, value in update_data.items():
        if key in ("payers", "splits", "items", "adjustments", "category_id"):
            continue
        setattr(db_transaction, key, value)
    db_transaction.split_mode = effective_mode
    session.add(db_transaction)
    session.flush()

    try:
        persist_transaction_children(
            session,
            workspace_id,
            db_transaction,
            total_amount=effective_total,
            split_mode=effective_mode,
            payers=transaction_in.payers,
            splits=splits,
            items=items,
            adjustments=adjustments,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    publish_event(session, workspace_id, "transaction.updated", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


@router.delete("/{transaction_id}")
def delete_transaction(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    db_transaction = session.get(Transaction, transaction_id)
    if not db_transaction or db_transaction.workspace_id != workspace_id or db_transaction.deleted_at:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Member exclui apenas os próprios lançamentos; admin+ exclui qualquer um
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and db_transaction.created_by_user_id not in (None, membership.user_id)
    ):
        raise HTTPException(status_code=403, detail="Você só pode excluir os próprios lançamentos")

    _ensure_not_paid(db_transaction)

    db_transaction.deleted_at = datetime.datetime.now(datetime.UTC)
    session.add(db_transaction)
    publish_event(session, workspace_id, "transaction.deleted", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    return {"status": "ok"}


def _load_group_siblings(
    session: Session, workspace_id: int, anchor: Transaction
) -> List[Transaction]:
    """Todas as parcelas irmãs vivas do grupo (ou só a âncora, se não for grupo)."""
    if not anchor.installment_group_id:
        return [anchor]
    return session.exec(
        select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.installment_group_id == anchor.installment_group_id,
            Transaction.deleted_at.is_(None),
        )
    ).all()


def _get_group_anchor(
    session: Session, workspace_id: int, transaction_id: int, membership: WorkspaceMembership
) -> Transaction:
    anchor = session.get(Transaction, transaction_id)
    if not anchor or anchor.workspace_id != workspace_id or anchor.deleted_at:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Grupo é coeso: as irmãs compartilham o mesmo criador, então o gate de
    # propriedade vale pela âncora (member só mexe no que é seu; admin+ em tudo)
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and anchor.created_by_user_id not in (None, membership.user_id)
    ):
        raise HTTPException(status_code=403, detail="Você só pode alterar os próprios lançamentos")
    return anchor


@router.post("/{transaction_id}/installment-group/cancel")
def cancel_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Cancela TODAS as parcelas vivas do grupo de uma vez (mantém histórico).
    Parcelas já pagas são preservadas — só reabrindo antes."""
    anchor = _get_group_anchor(session, workspace_id, transaction_id, membership)
    siblings = _load_group_siblings(session, workspace_id, anchor)

    cancelled = 0
    skipped_paid = 0
    for tx in siblings:
        if tx.status == TransactionStatus.paid:
            skipped_paid += 1
            continue
        if tx.status == TransactionStatus.cancelled:
            continue
        tx.status = TransactionStatus.cancelled
        session.add(tx)
        cancelled += 1

    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    return {"status": "ok", "cancelled": cancelled, "skipped_paid": skipped_paid}


@router.delete("/{transaction_id}/installment-group")
def delete_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Exclui (soft) todas as parcelas vivas do grupo atomicamente. Parcelas
    pagas são preservadas para não corromper acertos já feitos."""
    anchor = _get_group_anchor(session, workspace_id, transaction_id, membership)
    siblings = _load_group_siblings(session, workspace_id, anchor)

    now = datetime.datetime.now(datetime.UTC)
    deleted = 0
    skipped_paid = 0
    for tx in siblings:
        if tx.status == TransactionStatus.paid:
            skipped_paid += 1
            continue
        tx.deleted_at = now
        session.add(tx)
        deleted += 1

    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    return {"status": "ok", "deleted": deleted, "skipped_paid": skipped_paid}


@router.post("/bulk")
def bulk_create_transactions(
    workspace_id: int,
    transactions_in: List[dict],
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    created_count = 0
    skipped = []
    for index, tx_data in enumerate(transactions_in):
        # Linha inválida (valor não-numérico, data malformada, valor <= 0)
        # é pulada COM MOTIVO (ADR 0008) — nunca derruba o import com 500
        title = str(tx_data.get("title") or "Imported Transaction")[:200]
        try:
            amount = Decimal(str(tx_data.get("total_amount", "0.00")))
        except (ArithmeticError, TypeError):
            skipped.append({"index": index, "title": title, "reason": "valor não é um número válido"})
            continue
        if amount <= 0:
            skipped.append({"index": index, "title": title, "reason": "valor deve ser positivo"})
            continue
        try:
            dt_str = tx_data.get("transaction_date")
            dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00")) if dt_str else datetime.datetime.now(datetime.UTC)
        except (ValueError, AttributeError, TypeError):
            skipped.append({"index": index, "title": title, "reason": "data inválida"})
            continue

        db_transaction = Transaction(
            title=title,
            total_amount=amount,
            transaction_date=dt,
            # Sem billing_month a transação some do histórico filtrado por mês
            billing_month=dt.strftime("%Y-%m"),
            workspace_id=workspace_id,
            created_by_user_id=membership.user_id,
            currency="BRL",
            status="confirmed"
        )
        session.add(db_transaction)
        session.flush() # Get ID

        # Default Payer: Current User
        db_payer = TransactionPayer(
            transaction_id=db_transaction.id,
            user_id=membership.user_id,
            amount=amount
        )
        session.add(db_payer)

        # Default Split: 100% to Current User
        db_split = TransactionSplit(
            transaction_id=db_transaction.id,
            user_id=membership.user_id,
            split_method=SplitMethod.equal,
            input_value=Decimal("100"),
            computed_amount=amount
        )
        session.add(db_split)
        created_count += 1

    # Import em massa emite UM evento agregado (evita tempestade de refetch)
    if created_count:
        publish_event(session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id)
    session.commit()
    return {
        "status": "ok",
        "created": created_count,
        "skipped": len(skipped),
        "skipped_details": skipped,
    }
