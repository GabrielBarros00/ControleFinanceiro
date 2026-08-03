from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select
from typing import List, Any, Dict, Optional
from datetime import date

from app.db.session import get_session
from app.domain.access_policy import has_full_access
from app.domain.dates import InvalidMonth, parse_month, today_local
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.estimate import MonthlyEstimate
from app.schemas.estimate import MonthlyEstimateCreate, MonthlyEstimateRead
from app.core.rate_limit import rate_limit_outbound
from app.domain.query_policy import (
    InvalidCurrencyCode,
    normalize_currency_code,
    workspace_base_currency,
)
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.forecast_service import ForecastService
from app.services.report_service import ReportService
from app.services.recurring_service import RecurringMaterializationService
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/analytics", tags=["analytics"])


def _parse_month(month: Optional[str]) -> date:
    """`YYYY-MM` → primeiro dia do mês; vazio → hoje. 400 no formato errado."""
    try:
        return parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/summary", response_model=Dict[str, Any])
def get_summary(
    workspace_id: int,
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    target_date = _parse_month(month)

    # Recorrências vencidas do mês corrente entram sozinhas (lazy accrual),
    # sempre no mês real — visualizar outro mês não materializa retroativo.
    RecurringMaterializationService.ensure_and_commit(
        session, workspace_id, role=membership.role
    )
    return ReportService.get_summary(
        session,
        workspace_id,
        target_date,
        user_id=membership.user_id,
        full_access=has_full_access(membership),
    )


@router.get("/reports", response_model=Dict[str, Any])
def get_reports(
    workspace_id: int,
    month: Optional[str] = None,  # YYYY-MM
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    """Relatórios ancorados no mês pedido: as 6 barras terminam nele e o resumo
    é o dele. Sem o parâmetro, o mês corrente (comportamento antigo)."""
    target_date = _parse_month(month)
    RecurringMaterializationService.ensure_and_commit(
        session, workspace_id, role=membership.role
    )
    acesso_completo = has_full_access(membership)
    return {
        "monthly_history": ReportService.get_last_6_months(
            session,
            workspace_id,
            user_id=membership.user_id,
            ref_month=target_date,
            full_access=acesso_completo,
        ),
        "current_summary": ReportService.get_summary(
            session,
            workspace_id,
            target_date,
            user_id=membership.user_id,
            full_access=acesso_completo,
        ),
    }


@router.get("/forecast", response_model=Dict[str, Any])
def get_forecast(
    workspace_id: int,
    month: Optional[str] = None, # YYYY-MM
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    target_date = _parse_month(month)

    # user_id: a previsão devolve TAMBÉM a meta pessoal de quem pediu (my_budget),
    # que é a que o Início compara com "sua despesa". Os totais seguem sendo da casa.
    projection = ForecastService.get_monthly_projection(
        session,
        workspace_id,
        target_date,
        user_id=membership.user_id,
        full_access=has_full_access(membership),
    )
    return projection


@router.get("/exchange-rate", response_model=Dict[str, Any])
def get_exchange_rate(
    workspace_id: int,
    from_currency: str,
    to_currency: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Taxa de câmbio de referência + fonte: PTAX (oficial) para as majores → BRL,
    senão fonte de mercado. Nunca 500: indisponível responde 422.

    Sem `to_currency`, o alvo é a MOEDA-BASE do workspace — não "BRL" fixo: este
    endpoint alimenta a dica "≈ tanto" do formulário, e num workspace em outra
    moeda a dica mostrava a conversão para um real que não é usado em lugar
    nenhum. Passa pelo `ExchangeRateStore` (mesma taxa cruzada que a criação do
    lançamento vai aplicar), então dica e valor gravado não divergem.

    Os dois códigos são validados como ISO-3 ANTES de qualquer I/O: eles descem
    até a URL da fonte de mercado (`.../v1/currencies/{codigo}.json`), então sem
    validação um parâmetro de query escolheria o caminho de uma requisição que o
    servidor faz para fora. `preview_base_currency_change` já validava; esta rota
    tinha ficado para trás.
    """
    try:
        from_currency = normalize_currency_code(from_currency)
        target = (
            normalize_currency_code(to_currency)
            if to_currency
            else workspace_base_currency(session, workspace_id)
        )
    except InvalidCurrencyCode as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Teto de chamadas ANTES do I/O: esta é a única rota do app que ainda vai à
    # rede de forma síncrona (o resto migrou para allow_fetch=False justamente
    # por isso). Cada par de moedas novo é um cache miss garantido, e o pior caso
    # do PTAX são ~10 requisições de saída — sem teto, algumas chamadas
    # concorrentes esgotam o threadpool de um backend que roda com 1 worker.
    rate_limit_outbound(f"{workspace_id}:exchange-rate")
    try:
        rate, source = ExchangeRateStore.rate_between(
            session, from_currency, target, today_local()
        )
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # O store grava a cotação buscada com `flush`, e `get_session` não comita: sem
    # este commit a taxa era descartada no fim do request e TODA sessão nova
    # repetia a chamada à fonte externa. Cotação de um dia passado é fato
    # imutável, e o `_save` é idempotente pela unique (moeda, data).
    session.commit()
    return {
        "from_currency": from_currency.upper(),
        "to_currency": target.upper(),
        "rate": str(rate),
        "source": source,
    }


def _validate_estimate_category(session: Session, workspace_id: int, category_id) -> None:
    if category_id is None:
        return
    from app.models.category import Category
    category = session.get(Category, category_id)
    if not category or category.workspace_id != workspace_id or category.deleted_at:
        raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")


def _ensure_estimate_owner(estimate: MonthlyEstimate, membership: WorkspaceMembership) -> None:
    """Meta PESSOAL só o próprio dono altera ou remove.

    Não é uma questão de papel: é a meta de gasto de uma pessoa, não um número
    do workspace. Admin manda no orçamento da casa; na meta pessoal de outro
    membro, não.
    """
    if estimate.owner_user_id is not None and estimate.owner_user_id != membership.user_id:
        raise HTTPException(
            status_code=403, detail="Esta é a meta pessoal de outro membro"
        )


def _estimate_owner(estimate_in: MonthlyEstimateCreate, membership: WorkspaceMembership):
    """Escopo → dono. `personal` é sempre do PRÓPRIO usuário: ninguém define a
    meta pessoal de outra pessoa (nem admin — é dado dela, não do workspace)."""
    return membership.user_id if estimate_in.scope == "personal" else None


@router.post("/estimates", response_model=MonthlyEstimateRead)
def create_estimate(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    estimate_in: MonthlyEstimateCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    _validate_estimate_category(session, workspace_id, estimate_in.category_id)
    owner_user_id = _estimate_owner(estimate_in, membership)
    campos = estimate_in.model_dump(exclude={"scope"})

    # Idempotente por (workspace, DONO, category_id, mês). A chave é o
    # category_id (FK), não o rótulo de texto: com o texto, um `category`
    # vazio/constante colapsava TODOS os orçamentos do mês num só, e dois textos
    # diferentes para a mesma categoria criavam duplicatas. O dono entrou junto
    # quando o orçamento ganhou escopo — senão definir a minha meta sobrescreveria
    # a da casa. (`== None` vira `IS NULL` no SQLAlchemy.)
    existing = session.exec(
        select(MonthlyEstimate)
        .where(MonthlyEstimate.workspace_id == workspace_id)
        .where(MonthlyEstimate.owner_user_id == owner_user_id)
        .where(MonthlyEstimate.category_id == estimate_in.category_id)
        .where(MonthlyEstimate.month == estimate_in.month)
        .where(MonthlyEstimate.deleted_at.is_(None))
    ).first()
    if existing:
        for key, value in campos.items():
            setattr(existing, key, value)
        session.add(existing)
        publish_event(session, workspace_id, "estimate.updated", "estimate", existing.id, membership.user_id)
        session.commit()
        session.refresh(existing)
        return existing

    db_estimate = MonthlyEstimate(
        **campos,
        workspace_id=workspace_id,
        user_id=membership.user_id,
        owner_user_id=owner_user_id,
    )
    session.add(db_estimate)
    session.flush()
    publish_event(session, workspace_id, "estimate.created", "estimate", db_estimate.id, membership.user_id)
    session.commit()
    session.refresh(db_estimate)
    return db_estimate


@router.put("/estimates/{estimate_id}", response_model=MonthlyEstimateRead)
def update_estimate(
    workspace_id: int,
    estimate_id: int,
    *,
    session: Session = Depends(get_session),
    estimate_in: MonthlyEstimateCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    estimate = session.get(MonthlyEstimate, estimate_id)
    if not estimate or estimate.workspace_id != workspace_id or estimate.deleted_at:
        raise HTTPException(status_code=404, detail="Estimativa não encontrada")
    _ensure_estimate_owner(estimate, membership)

    _validate_estimate_category(session, workspace_id, estimate_in.category_id)
    for key, value in estimate_in.model_dump(exclude={"scope"}).items():
        setattr(estimate, key, value)
    session.add(estimate)
    publish_event(session, workspace_id, "estimate.updated", "estimate", estimate.id, membership.user_id)
    session.commit()
    session.refresh(estimate)
    return estimate


@router.get("/estimates", response_model=List[MonthlyEstimateRead])
def list_estimates(
    workspace_id: int,
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    # Metas da CASA + as PESSOAIS de quem está pedindo. A meta pessoal de outro
    # membro nunca sai daqui: é o gasto que ele planeja para si, não um número do
    # workspace (mesma linha do e-mail mascarado em `members.list_members`).
    #
    # NÃO trocar por `shared_or_mine_scope`: este filtro é INCONDICIONAL, mais
    # estrito que a política de ADR 0018 de propósito — nem owner nem admin veem
    # a meta pessoal de outro membro (ADR 0017). Unificar aqui abriria um
    # vazamento em nome da consistência.
    statement = (
        select(MonthlyEstimate)
        .where(MonthlyEstimate.workspace_id == workspace_id)
        .where(MonthlyEstimate.deleted_at.is_(None))
        .where(
            or_(
                MonthlyEstimate.owner_user_id.is_(None),
                MonthlyEstimate.owner_user_id == membership.user_id,
            )
        )
    )
    if month:
        statement = statement.where(MonthlyEstimate.month == month)

    estimates = session.exec(statement).all()
    return estimates


@router.delete("/estimates/{estimate_id}")
def delete_estimate(
    workspace_id: int,
    estimate_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    from datetime import datetime, UTC
    estimate = session.get(MonthlyEstimate, estimate_id)
    if not estimate or estimate.workspace_id != workspace_id or estimate.deleted_at:
        raise HTTPException(status_code=404, detail="Estimativa não encontrada")
    _ensure_estimate_owner(estimate, membership)

    estimate.deleted_at = datetime.now(UTC)
    session.add(estimate)
    publish_event(session, workspace_id, "estimate.deleted", "estimate", estimate_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
