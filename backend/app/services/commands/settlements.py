"""Comandos de ACERTO entre membros de um espaço (ADR 0009/0031).

Movidos de `api/routes/settlements.py` sem mudança de regra (ADR 0035): só o
`commit` saiu — quem chama (rota REST ou pipeline do MCP) comanda a transação.
"""
from datetime import datetime, UTC

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.locks import trava_workspace
from app.domain.access_policy import assert_can_write, can_write
from app.domain.account_policy import AccountCurrencyMismatch, assert_conta_na_moeda
from app.domain.query_policy import workspace_base_currency
from app.models.payment_account import PaymentAccount
from app.models.settlement import Settlement
from app.models.workspace import WorkspaceMembership
from app.schemas.settlement import SettlementCreate
from app.services.debt_service import DebtService
from app.services.event_service import publish_event


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


def create_settlement(
    session: Session,
    workspace_id: int,
    settlement_in: SettlementCreate,
    membership: WorkspaceMembership,
) -> Settlement:
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

    # A conta é do PAGADOR e só pode ser declarada por ELE (ADR 0004/0034): um
    # `admin` pode registrar o acerto de outra pessoa, mas não afirmar de qual
    # conta bancária dela o dinheiro saiu.
    #
    # AQUI, junto do gate de autoria e ANTES da trava e da checagem de dívida:
    # é autorização, e não depende de haver o que acertar. Depois da checagem,
    # a recusa por conta alheia chegava mascarada de 'não há dívida'.
    conta_id = None
    if settlement_in.from_account_id is not None:
        if settlement_in.from_user_id != membership.user_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Você não pode declarar de qual conta de outra pessoa saiu o "
                    "dinheiro — deixe a conta em branco"
                ),
            )
        conta = session.get(PaymentAccount, settlement_in.from_account_id)
        if not conta or conta.deleted_at or conta.owner_user_id != membership.user_id:
            raise HTTPException(status_code=400, detail="Conta inválida")
        # O acerto vale na moeda-base do espaço — é assim que
        # `CashFlowService._acertos` o expressa.
        try:
            assert_conta_na_moeda(conta, workspace_base_currency(session, workspace_id))
        except AccountCurrencyMismatch as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        conta_id = conta.id


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
        from_account_id=conta_id,
        created_by_user_id=membership.user_id,
    )
    session.add(db_settlement)
    session.flush()
    publish_event(session, workspace_id, "settlement.created", "settlement", db_settlement.id, membership.user_id)
    return db_settlement


def delete_settlement(
    session: Session,
    workspace_id: int,
    settlement_id: int,
    membership: WorkspaceMembership,
) -> dict:
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
    return {"status": "ok"}
