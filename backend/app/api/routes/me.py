"""Rotas PESSOAIS — sem `workspace_id` no caminho (ADR 0020).

Todo o resto da API vive sob `/workspaces/{workspace_id}/...`, o que embutia uma
premissa: tudo pertence a um espaço de colaboração. Renda, cartão e compromisso
são da PESSOA, e a pergunta "como está o meu mês, somando tudo?" não tinha onde
ser feita.

O gate aqui é só `get_current_user`: não há workspace de que ser membro, porque o
recorte é o próprio usuário. Cada consulta filtra por `user_id` — nunca por
workspace — e a agregação varre os workspaces de que ele participa.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.dates import InvalidMonth, parse_month
from app.domain.query_policy import InvalidCurrencyCode, normalize_currency_code
from app.models.user import User
from app.schemas.common import OptionalCurrencyCode
from app.services.overview_service import OverviewService
from sqlmodel import Session

router = APIRouter(prefix="/me", tags=["me"])


def _mes(month: Optional[str]) -> date:
    try:
        return parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _moeda(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    try:
        return normalize_currency_code(valor)
    except InvalidCurrencyCode as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ReportCurrencyUpdate(BaseModel):
    report_currency: OptionalCurrencyCode = None


@router.get("/overview", response_model=Dict[str, Any])
def get_overview(
    month: Optional[str] = None,
    currency: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """O mês da pessoa somando TODOS os workspaces dela.

    Distingue consumo (minha parte), saída de caixa (o que saiu do meu bolso),
    a pagar/receber (a diferença, por workspace) e resultado (renda − consumo) —
    quatro números que o Início antigo colapsava num só.
    """
    return OverviewService.get_overview(
        session, current_user.id, _mes(month), currency=_moeda(currency)
    )


@router.get("/commitments", response_model=Dict[str, Any])
def get_commitments(
    currency: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Faturas e financiamentos MEUS a vencer, em todos os workspaces."""
    return OverviewService.get_commitments(
        session, current_user.id, currency=_moeda(currency)
    )


@router.get("/activity", response_model=List[Dict[str, Any]])
def get_activity(
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Lançamentos recentes em que eu estou envolvido, em qualquer workspace."""
    return OverviewService.get_activity(session, current_user.id, limit=limit)


@router.patch("/report-currency", response_model=Dict[str, Any])
def set_report_currency(
    data: ReportCurrencyUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Moeda em que os números pessoais são expressos.

    Existe porque o que é da pessoa não tem workspace de onde herdar a moeda-base,
    e a visão global soma workspaces que podem ter bases diferentes — somar sem
    uma moeda de destino declarada é o que o ADR 0006 proíbe.
    """
    if data.report_currency:
        current_user.report_currency = data.report_currency
        session.add(current_user)
        session.commit()
        session.refresh(current_user)
    return {"report_currency": current_user.report_currency}
