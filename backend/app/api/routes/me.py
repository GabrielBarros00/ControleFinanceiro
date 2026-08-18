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
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.dates import InvalidMonth, parse_month
from app.domain.query_policy import InvalidCurrencyCode, normalize_currency_code
from app.models.user import User
from app.schemas.common import OptionalCurrencyCode
from app.schemas.overview import (
    ReportCurrencyRead,
    ActivityRead,
    CommitmentsRead,
    LedgerRead,
    OverviewRead,
    SeriesRead,
)
from app.services.cashflow_service import CASH_SOURCES
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


@router.get("/overview", response_model=OverviewRead)
def get_overview(
    month: Optional[str] = None,
    currency: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """O mês da pessoa somando TODOS os workspaces dela.

    Distingue consumo (minha parte), o que ela adiantou nos lançamentos, a
    pagar/receber (a diferença, por workspace), resultado (renda − consumo) e o
    caixa efetivo — entrada e saída de dinheiro de verdade, com pagamento de
    fatura, acerto e parcela de financiamento (ADR 0022). Números que o Início
    antigo colapsava num só.
    """
    return OverviewService.get_overview(
        session, current_user.id, _mes(month), currency=_moeda(currency)
    )


@router.get("/reports", response_model=SeriesRead)
def get_reports(
    # Teto de 12, não 24: a tela pede 6, e o custo é LINEAR no número de meses —
    # medido com 2.160 lançamentos em 2 workspaces, 6 meses custam ~100 ms e 24
    # custavam ~400 ms. Num backend de UM worker (o ConnectionManager do
    # WebSocket é in-process, ver Dockerfile) meio segundo de CPU bloqueia todos
    # os outros usuários, e o parâmetro é de quem chama. 12 dá o dobro do que a
    # UI usa e mantém o pior caso em ~200 ms.
    months: int = Query(6, ge=1, le=12),
    currency: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Relatório da PESSOA: vários meses somando todos os workspaces.

    Os Relatórios de `/w/:id/reports` continuam existindo e são de outra
    pergunta — "quanto esta casa gastou". Este responde "como está o meu
    período": renda × consumo, resultado mês a mês, caixa efetivo e quanto do
    meu consumo foi para cada casa.
    """
    return OverviewService.get_series(
        session, current_user.id, months=months, currency=_moeda(currency)
    )


@router.get("/ledger", response_model=LedgerRead)
def get_ledger(
    month: Optional[str] = None,
    # Múltiplos: `?source=income&source=settlement_received`
    source: Optional[List[str]] = Query(default=None),
    workspace_id: Optional[int] = Query(default=None),
    card_id: Optional[int] = Query(default=None),
    counterparty_id: Optional[int] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Extrato global: cada movimento de caixa do mês, em todos os workspaces.

    É o detalhe de `/me/overview` — mesma origem de dados, então o extrato SEMPRE
    fecha com os totais. Sem ele a Visão global respondia "saiu R$ 4.200" e não
    tinha como explicar de onde.
    """
    if source:
        invalidas = set(source) - set(CASH_SOURCES)
        if invalidas:
            raise HTTPException(
                status_code=400,
                detail=f"Origem inválida: {', '.join(sorted(invalidas))}",
            )
    return OverviewService.get_ledger(
        session,
        current_user.id,
        _mes(month),
        currency=_moeda(currency),
        sources=source,
        workspace_id=workspace_id,
        card_id=card_id,
        counterparty_id=counterparty_id,
        limit=limit,
        offset=offset,
    )


@router.get("/commitments", response_model=CommitmentsRead)
def get_commitments(
    currency: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Faturas e financiamentos MEUS a vencer, em todos os workspaces."""
    return OverviewService.get_commitments(
        session, current_user.id, currency=_moeda(currency)
    )


@router.get("/activity", response_model=List[ActivityRead])
def get_activity(
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Lançamentos recentes em que eu estou envolvido, em qualquer workspace."""
    return OverviewService.get_activity(session, current_user.id, limit=limit)


@router.patch("/report-currency", response_model=ReportCurrencyRead)
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
