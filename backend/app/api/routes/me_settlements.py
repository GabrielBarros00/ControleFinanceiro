"""Acertos entre pessoas SEM workspace no caminho (ADR 0027).

O par global de `/{ws}/debts` e `/{ws}/settlements`. Mesmo gate das outras rotas
pessoais — só `get_current_user` —, porque não há workspace de que ser membro: o
recorte é o próprio usuário, e cada linha devolvida tem ele como uma das pontas.

**Só leitura.** Registrar e desfazer acerto continua em
`/workspaces/{ws}/settlements`, onde moram a direção e o teto do ADR 0009, o
`trava_workspace` contra sobrepagamento concorrente e o `publish_event`. A tela
global manda o `workspace_id` da linha em que a pessoa clicou — o que a distingue
do "Nova despesa" ausente na Visão global (ADR 0020): lá o workspace seria
ambíguo, aqui ele vem da própria linha.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.dates import InvalidMonth, parse_month
from app.domain.query_policy import InvalidCurrencyCode, normalize_currency_code
from app.models.user import User
from app.schemas.overview import (
    PersonalDebtsRead,
    PersonalMonthlyDebtsRead,
    PersonalSettlementsRead,
)
from app.services.personal_debt_service import (
    LIMITE_MAXIMO,
    LIMITE_PADRAO,
    PersonalDebtService,
)

router = APIRouter(prefix="/me", tags=["me-settlements"])


def _mes(month: Optional[str]) -> str:
    try:
        return parse_month(month).strftime("%Y-%m")
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _moeda(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    try:
        return normalize_currency_code(valor)
    except InvalidCurrencyCode as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O redirecionamento automático de barra do Starlette responde 307, e nesse
    salto o **cookie de sessão não acompanha** — a URL com a barra "errada"
    devolveria 401 em vez de funcionar. Mesmo helper de `me_financing.py`.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


@_colecao("get", "/debts", response_model=PersonalDebtsRead)
def get_personal_debts(
    currency: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Com quem eu me acerto, somando todas as casas.

    Agrupado por workspace e **nunca compensado entre eles**: dever 100 na Casa e
    ter 100 a receber na Viagem não é estar quitado. Cada grupo vem na moeda-base
    da própria casa; só os totais convertem, e o que não converte aparece em
    `excluded_workspaces` com o valor na moeda dele.
    """
    return PersonalDebtService.get_personal_debts(
        session, current_user.id, currency=_moeda(currency)
    )


@router.get("/debts/monthly", response_model=PersonalMonthlyDebtsRead)
def get_personal_monthly_debts(
    month: Optional[str] = None,  # YYYY-MM; default: mês atual
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """O retrato do mês (por `billing_month`), uma seção por casa.

    Parcelas aparecem só no mês delas. Casa sem movimento no mês não vira seção —
    senão quem tem várias casas recebe uma pilha de cards vazios.

    Sem `?currency=`: cada seção é uma casa, na moeda-base dela, e não há total
    agregado a converter (ver o serviço).
    """
    return PersonalDebtService.get_personal_monthly(session, current_user.id, _mes(month))


@_colecao("get", "/settlements", response_model=PersonalSettlementsRead)
def list_personal_settlements(
    limit: int = Query(LIMITE_PADRAO, ge=1, le=LIMITE_MAXIMO),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Histórico de acertos da pessoa, em todas as casas.

    Só os acertos em que ela é uma das pontas. O acerto entre TERCEIROS de uma
    casa em que ela é admin **não** aparece: quem mostra aquilo é a tela do
    workspace, e a camada `/me/*` é a visão da pessoa.
    """
    return PersonalDebtService.list_personal_settlements(
        session, current_user.id, limit=limit, offset=offset
    )
