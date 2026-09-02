"""Acertos entre pessoas SEM workspace no caminho (ADR 0027).

O par global de `/{ws}/debts` e `/{ws}/settlements`. Mesmo gate das outras rotas
pessoais — só `get_current_user` —, porque não há workspace de que ser membro: o
recorte é o próprio usuário, e cada linha devolvida tem ele como uma das pontas.

**Quase só leitura.** Registrar e desfazer acerto continua em
`/workspaces/{ws}/settlements`, onde moram a direção e o teto do ADR 0009, o
`trava_workspace` contra sobrepagamento concorrente e o `publish_event`. A tela
global manda o `workspace_id` da linha em que a pessoa clicou — o que a distingue
do "Nova despesa" ausente na Visão global (ADR 0020): lá o workspace seria
ambíguo, aqui ele vem da própria linha.

A exceção é `PUT /settlements/{id}/account` (ADR 0034): a conta em que o acerto
RECEBIDO caiu só pode ser declarada pelo credor, e ele não é quem registra o
acerto. É a única escrita que não caberia do outro lado.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns
from app.domain.account_policy import AccountCurrencyMismatch, assert_conta_na_moeda
from app.domain.dates import InvalidMonth, parse_month
from app.domain.query_policy import (
    InvalidCurrencyCode,
    normalize_currency_code,
    workspace_base_currency,
)
from app.models.payment_account import PaymentAccount
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.common import StatusRead
from app.schemas.overview import (
    PersonalDebtsByMonthRead,
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


@router.get("/debts/by-month", response_model=PersonalDebtsByMonthRead)
def get_personal_debts_by_month(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """De quais meses vem o saldo, uma seção por casa.

    Sub-rota como `/debts/monthly`, não raiz de coleção — por isso sem o
    `_colecao` (que existe para a barra final de `/debts` e `/settlements`).

    Sem total agregado: somar a origem de casas diferentes produziria a
    compensação que o ADR 0020 proíbe, com a agravante de parecer conta fechada.
    """
    return PersonalDebtService.get_personal_by_month(session, current_user.id)


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


class SettlementAccountRequest(BaseModel):
    """Em qual conta o acerto RECEBIDO caiu (ADR 0034)."""
    #: `None` desfaz a atribuição — o movimento volta a ser "sem conta".
    account_id: Optional[int] = None


@router.put("/settlements/{settlement_id}/account", response_model=StatusRead)
def set_settlement_account(
    settlement_id: int,
    body: SettlementAccountRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """A única ESCRITA deste módulo, e ela existe por uma razão de privacidade.

    Quem registra um acerto é o pagador (`/workspaces/{ws}/settlements`), e a
    conta do credor é invisível para ele — `personal_scope` não a alcança, e
    declará-la violaria a regra que o projeto já escreveu em
    `_validate_payer_accounts`: *"você não pode declarar de qual conta de outra
    pessoa saiu o dinheiro"*.

    Sem esta porta, o acerto recebido seria para sempre um movimento sem conta no
    saldo de quem recebeu — visível no contador de anomalia da tela de Contas e
    sem nenhuma forma de corrigir. O gate é `to_user_id == eu`: só o credor
    declara o lado dele.
    """
    acerto = session.get(Settlement, settlement_id)
    if not acerto or acerto.deleted_at:
        raise HTTPException(status_code=404, detail="Acerto não encontrado")
    # 404 e não 403 (anti-enumeração): quem não é o credor não fica sabendo nem
    # que o acerto existe.
    assert_owns(acerto.to_user_id, current_user.id, detail="Acerto não encontrado")

    conta_id = None
    if body.account_id is not None:
        conta = session.get(PaymentAccount, body.account_id)
        if not conta or conta.deleted_at or conta.owner_user_id != current_user.id:
            raise HTTPException(status_code=400, detail="Conta inválida")
        try:
            # O acerto vale na moeda-base do espaço em que foi registrado — é
            # assim que `CashFlowService._acertos` o expressa.
            assert_conta_na_moeda(
                conta, workspace_base_currency(session, acerto.workspace_id)
            )
        except AccountCurrencyMismatch as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        conta_id = conta.id

    acerto.to_account_id = conta_id
    session.add(acerto)
    session.commit()
    return {"status": "ok"}
