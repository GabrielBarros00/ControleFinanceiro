from datetime import datetime, UTC
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.domain.access_policy import assert_can_read, assert_can_write, income_visible_to
from app.domain.dates import InvalidMonth, month_bounds, parse_month
from app.domain.query_policy import resolve_currency, workspace_base_currency
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.income import Income, IncomeWorkspaceShare
from app.schemas.income import IncomeCreate, IncomeRead, IncomeUpdate
from app.api.deps import get_workspace_membership, require_role
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.event_service import publish_event
from app.services.recurring_service import RecurringMaterializationService
from app.services.sharing_service import set_shares, share_ids

router = APIRouter(prefix="/workspaces/{workspace_id}/income", tags=["income"])


def _convert_income_fields(
    session: Session, workspace_id: int, amount: Decimal, currency: Optional[str], received_at: datetime
) -> dict:
    """Renda em moeda estrangeira → moeda-base do workspace na data de recebimento
    (sem IOF). Devolve os campos a gravar (amount e currency na base + original_*);
    {} se já for base."""
    base = workspace_base_currency(session, workspace_id)
    if not currency or currency == base:
        return {}
    occ = received_at.date() if hasattr(received_at, "date") else received_at
    try:
        # rate_between: a taxa precisa ser moeda→BASE, e o store só guarda X→BRL
        rate, source = ExchangeRateStore.rate_between(session, currency, base, occ)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "amount": converted,
        "currency": base,
        "original_amount": amount,
        "original_currency": currency,
        "exchange_rate": rate,
        "rate_source": source,
    }


def _serialize(session: Session, income: Income) -> dict:
    """`IncomeRead` com escopo e compartilhamentos derivados.

    A tela não deve ter que inferir "é pessoal?" de um `workspace_id` nulo — o
    tipo de inferência que envelhece mal e diverge entre componentes.
    """
    return {
        **income.model_dump(),
        "scope": "workspace" if income.workspace_id is not None else "personal",
        "shared_with_workspace_ids": share_ids(
            session, IncomeWorkspaceShare, IncomeWorkspaceShare.income_id, income.id
        ),
    }


def _get_income_or_404(
    session: Session, workspace_id: int, income_id: int, membership: WorkspaceMembership
) -> Income:
    income = session.get(Income, income_id)
    if not income or income.deleted_at:
        raise HTTPException(status_code=404, detail="Renda não encontrada")

    # Renda PESSOAL (workspace_id NULL) é alcançável a partir de qualquer
    # workspace do dono — é o ponto de ela ser global (ADR 0019). O gate é a
    # PROPRIEDADE, não a pertinência ao workspace da URL. Manter a checagem
    # `workspace_id != workspace_id` aqui tornaria a própria renda inalcançável.
    if income.workspace_id is None:
        if income.user_id != membership.user_id:
            raise HTTPException(status_code=404, detail="Renda não encontrada")
        return income

    # Renda DA CASA: tem de ser deste workspace...
    if income.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Renda não encontrada")
    # ...e salário é o dado mais sensível do sistema: sem acesso completo, a renda
    # de outro membro nem existe (404, não 403)
    assert_can_read(income.user_id, membership, detail="Renda não encontrada")
    return income


def _check_income_ownership(membership: WorkspaceMembership, income: Income):
    assert_can_write(
        income.user_id, membership, detail="Você só pode alterar as próprias rendas"
    )


@router.post("/", response_model=IncomeRead)
def create_income(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    income_in: IncomeCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    data = income_in.model_dump(exclude={"scope", "shared_with_workspace_ids"})
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    data["currency"] = resolve_currency(session, workspace_id, income_in.currency)
    # Renda estrangeira: converte para a moeda-base na entrada, guardando o original
    data.update(_convert_income_fields(session, workspace_id, income_in.amount, data["currency"], income_in.received_at))
    # `workspace_id=None` por padrão: renda nasce PESSOAL e vale em todos os meus
    # workspaces (ADR 0019). `scope="workspace"` marca a exceção — renda DA CASA,
    # como aluguel de um imóvel do casal.
    db_income = Income(
        **data,
        workspace_id=workspace_id if income_in.scope == "workspace" else None,
        user_id=membership.user_id,
    )
    session.add(db_income)
    session.flush()
    # Renda da CASA já pertence ao workspace; compartilhar é coisa de renda pessoal
    if income_in.scope == "personal":
        set_shares(
            session,
            IncomeWorkspaceShare,
            "income_id",
            db_income.id,
            income_in.shared_with_workspace_ids,
            user_id=membership.user_id,
        )
    publish_event(session, workspace_id, "income.created", "income", db_income.id, membership.user_id)
    session.commit()
    session.refresh(db_income)
    return _serialize(session, db_income)


@router.get("/", response_model=List[IncomeRead])
def list_income(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
    month: Optional[str] = None,  # YYYY-MM: recorta pela competência (received_at)
):
    # Materializa recorrências vencidas só quando o mês pedido é o corrente: a
    # materialização é sempre restrita ao mês de hoje, então em mês fechado seria
    # trabalho perdido (e não casaria com o filtro). Sem mês = comportamento antigo.
    now = datetime.now(UTC)
    current_month = f"{now.year:04d}-{now.month:02d}"
    if month is None or month == current_month:
        RecurringMaterializationService.ensure_and_commit(
            session, workspace_id, role=membership.role, user_id=membership.user_id
        )

    # A MINHA renda (global, ADR 0019) + a da casa quando o acesso é completo
    # (ADR 0018). O filtro `Income.workspace_id == workspace_id` que estava aqui
    # era o que fazia o salário sumir num workspace recém-criado.
    statement = select(Income).where(
        Income.deleted_at.is_(None),
        income_visible_to(workspace_id, membership),
    )

    # Filtro por mês pela DATA DE RECEBIMENTO — mesma competência do
    # ReportService.get_summary (o "Sua receita" do Início). received_at é a fonte
    # de verdade da renda; a avulsa não tem billing_month.
    if month:
        # Mês inválido é ERRO, não "sem filtro". Antes o except engolia e a rota
        # devolvia o histórico INTEIRO como se fosse o mês pedido — com o total
        # do cabeçalho errado e nenhum sinal para o usuário.
        try:
            ref = parse_month(month)
        except InvalidMonth as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        start, end = month_bounds(ref)
        statement = statement.where(
            Income.received_at >= start,
            Income.received_at <= end,
        )

    statement = statement.order_by(Income.received_at.desc())
    return [_serialize(session, i) for i in session.exec(statement).all()]


@router.put("/{income_id}", response_model=IncomeRead)
def update_income(
    workspace_id: int,
    income_id: int,
    income_in: IncomeUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    income = _get_income_or_404(session, workspace_id, income_id, membership)
    _check_income_ownership(membership, income)

    fields_set = income_in.model_dump(exclude_unset=True)
    # Escopo e compartilhamento não são colunas do model — tratados à parte
    escopo = fields_set.pop("scope", None)
    compartilhar = fields_set.pop("shared_with_workspace_ids", None)
    for key, value in fields_set.items():
        setattr(income, key, value)

    if escopo is not None:
        # Virar renda da casa DESFAZ os compartilhamentos: a renda passa a ser do
        # workspace, e manter as duas coisas a somaria duas vezes no total dele.
        income.workspace_id = workspace_id if escopo == "workspace" else None
        if escopo == "workspace":
            compartilhar = []

    # Moeda: só re-converte se o PUT mexeu em valor OU moeda. Um PUT parcial que
    # NÃO toca em amount/currency preserva o original congelado — senão editar só
    # o título apagaria a proveniência ("era USD 100 @ 5,00"). Pela UI o form
    # sempre reenvia amount+currency do original, então o round-trip segue igual;
    # edição efetiva em BRL (currency=base) limpa o original.
    if "amount" in fields_set or "currency" in fields_set:
        conv = _convert_income_fields(session, workspace_id, income.amount, income.currency, income.received_at)
        if conv:
            for k, v in conv.items():
                setattr(income, k, v)
        else:
            income.original_amount = None
            income.original_currency = None
            income.exchange_rate = None
            income.rate_source = None

    if compartilhar is not None:
        set_shares(
            session,
            IncomeWorkspaceShare,
            "income_id",
            income.id,
            compartilhar,
            user_id=income.user_id,
        )

    income.updated_at = datetime.now(UTC)
    session.add(income)
    publish_event(session, workspace_id, "income.updated", "income", income.id, membership.user_id)
    session.commit()
    session.refresh(income)
    return _serialize(session, income)


@router.delete("/{income_id}")
def delete_income(
    workspace_id: int,
    income_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    income = _get_income_or_404(session, workspace_id, income_id, membership)
    _check_income_ownership(membership, income)

    income.deleted_at = datetime.now(UTC)
    session.add(income)
    publish_event(session, workspace_id, "income.deleted", "income", income.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
