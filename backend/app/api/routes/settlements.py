from datetime import datetime, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, StatusRead
from sqlmodel import Session, select

from app.db.locks import trava_workspace
from app.db.session import get_session
from app.domain.access_policy import assert_can_write, can_write, participant_scope
from app.domain.query_policy import workspace_base_currency
from app.models.settlement import Settlement
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.services.debt_service import DebtService
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/settlements", tags=["settlements"])


class SettlementCreate(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: Decimal = Field(gt=0, le=MAX_MONEY)
    note: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    # YYYY-MM: quando vem do ledger mensal, quita a dívida daquele mês
    billing_month: Optional[str] = None
    settled_at: Optional[datetime] = None


class SettlementRead(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount: Decimal
    note: Optional[str]
    billing_month: Optional[str]
    settled_at: datetime
    created_by_user_id: Optional[int]


def _ensure_members(session: Session, workspace_id: int, user_ids: set) -> None:
    members = set(session.exec(
        select(WorkspaceMembership.user_id).where(
            WorkspaceMembership.workspace_id == workspace_id
        )
    ).all())
    outsiders = user_ids - members
    if outsiders:
        raise HTTPException(
            status_code=400,
            detail=f"Usuário(s) {sorted(outsiders)} não pertence(m) a este workspace",
        )


@router.post("", response_model=SettlementRead)
def create_settlement(
    workspace_id: int,
    settlement_in: SettlementCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    if settlement_in.from_user_id == settlement_in.to_user_id:
        raise HTTPException(status_code=400, detail="Pagador e recebedor devem ser pessoas diferentes")
    _ensure_members(session, workspace_id, {settlement_in.from_user_id, settlement_in.to_user_id})

    # Autorização (ADR 0009): member registra apenas acertos em que ELE é o
    # pagador; registrar por terceiros exige admin/owner
    if not can_write(settlement_in.from_user_id, membership):
        raise HTTPException(
            status_code=403,
            detail="Você só pode registrar acertos em que você é o pagador",
        )

    # ANTES de ler o saldo (ver `db/locks.py`): o teto abaixo é uma soma sobre
    # várias linhas conferida por um `if`, e sem trava duas quitações simultâneas
    # da dívida inteira leem o mesmo saldo e passam as duas. Medido antes da
    # correção: 8 acertos de R$ 500 numa dívida de R$ 500 — R$ 3.500 de crédito
    # artificial para o devedor, que é a exata inversão de relação que o ADR 0009
    # proíbe. A linha travada é a do WORKSPACE porque o saldo deriva dele inteiro
    # (pagos − devidos − acertos de todos os membros), não de um par de pessoas.
    trava_workspace(session, workspace_id)

    # Direção e teto (ADR 0009): o acerto segue a dívida líquida e não pode
    # excedê-la — sobrepagamento inverteria a relação (crédito artificial).
    #
    # A referência é a MESMA que o usuário está vendo: com billing_month, o
    # ledger daquele mês; sem ele, o balanço global. Antes o teto era sempre o
    # global, então quitar julho era recusado ("não há dívida nessa direção")
    # sempre que agosto invertia o saldo líquido.
    if settlement_in.billing_month:
        ledger = DebtService.get_monthly_ledger(
            session, workspace_id, settlement_in.billing_month
        )
        debts = ledger["net_debts"]
        escopo = f"do mês {settlement_in.billing_month}"
    else:
        debts = DebtService.get_workspace_debts(session, workspace_id)
        escopo = "atual"

    debt = next(
        (
            d for d in debts
            if d["debtor_id"] == settlement_in.from_user_id
            and d["creditor_id"] == settlement_in.to_user_id
        ),
        None,
    )
    if debt is None:
        raise HTTPException(
            status_code=400,
            detail=f"Não há dívida nessa direção para acertar ({escopo})",
        )
    if settlement_in.amount > debt["amount"]:
        # Moeda do workspace, não "R$" fixo: num workspace em outra moeda a
        # mensagem contradizia todos os valores exibidos na mesma tela.
        moeda = workspace_base_currency(session, workspace_id)
        raise HTTPException(
            status_code=400,
            detail=f"Valor excede a dívida {escopo} ({moeda} {debt['amount']})",
        )

    db_settlement = Settlement(
        workspace_id=workspace_id,
        from_user_id=settlement_in.from_user_id,
        to_user_id=settlement_in.to_user_id,
        amount=settlement_in.amount,
        note=settlement_in.note,
        billing_month=settlement_in.billing_month,
        settled_at=settlement_in.settled_at or datetime.now(UTC),
        created_by_user_id=membership.user_id,
    )
    session.add(db_settlement)
    session.flush()
    publish_event(session, workspace_id, "settlement.created", "settlement", db_settlement.id, membership.user_id)
    session.commit()
    session.refresh(db_settlement)
    return db_settlement


@router.get("", response_model=List[SettlementRead])
def list_settlements(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(Settlement)
        .where(Settlement.workspace_id == workspace_id)
        .where(Settlement.deleted_at.is_(None))
        # Acerto tem DOIS lados: vejo aquele em que eu pago ou recebo (ADR 0018)
        .where(participant_scope(
            (Settlement.from_user_id, Settlement.to_user_id), membership
        ))
        .order_by(Settlement.settled_at.desc())
    ).all()


@router.delete("/{settlement_id}", response_model=StatusRead)
def delete_settlement(
    workspace_id: int,
    settlement_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    db_settlement = session.get(Settlement, settlement_id)
    if not db_settlement or db_settlement.workspace_id != workspace_id or db_settlement.deleted_at:
        raise HTTPException(status_code=404, detail="Acerto não encontrado")

    # Member desfaz apenas os próprios registros; admin+ desfaz qualquer um
    assert_can_write(
        db_settlement.created_by_user_id,
        membership,
        detail="Você só pode desfazer os próprios acertos",
    )

    db_settlement.deleted_at = datetime.now(UTC)
    session.add(db_settlement)
    publish_event(session, workspace_id, "settlement.deleted", "settlement", settlement_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
