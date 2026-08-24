"""Contas a pagar DO ESPAÇO e a confirmação de pagamento (ADR 0029).

O par de `/me/payables`, e a pergunta é outra: lá é "o que EU tenho a pagar,
somando minhas casas"; aqui é "o que esta casa tem em aberto, e quem vai pagar
cada conta". As duas leituras saem do mesmo `PayablesService`, então não têm como
discordar sobre o que conta como pendência.

A ESCRITA mora aqui e não em `/me` porque o lançamento pertence a um espaço:
quem pode marcá-lo como pago é quem pode editá-lo (`assert_can_write` por linha,
dentro do serviço), e o evento de sincronização é publicado na sala daquele espaço.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import get_workspace_membership, require_role
from app.db.session import get_session
from app.domain.access_policy import has_full_access
from app.domain.dates import InvalidMonth, parse_month
from app.domain.query_policy import (
    InvalidCurrencyCode,
    normalize_currency_code,
    workspace_base_currency,
)
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.schemas.overview import PayablesRead, SettleResult
from app.services.event_service import publish_event
from app.services.payables_service import PayablesService

router = APIRouter(prefix="/workspaces/{workspace_id}/payables", tags=["payables"])


class SettleRequest(BaseModel):
    """Confirmar (ou desfazer) o pagamento de várias contas de uma vez.

    `settled_on` é o dia em que o dinheiro saiu — não "agora". É ele que decide em
    que mês a saída aparece no caixa, e pagar no dia 2 uma conta confirmada no
    app no dia 5 tem de mover o caixa do dia 2.
    """
    transaction_ids: List[int] = Field(min_length=1, max_length=200)
    settled: bool = True
    settled_on: Optional[date] = None


def _mes(month: Optional[str]) -> date:
    try:
        return parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=PayablesRead)
def list_workspace_payables(
    workspace_id: int,
    month: Optional[str] = None,
    currency: Optional[str] = Query(default=None),
    include_overdue: bool = Query(default=True),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """As contas em aberto DESTE espaço, de quem quer que vá pagá-las.

    A moeda de destino é a **base do espaço** (não a de relatório da pessoa): é a
    moeda em que todo número desta casa é expresso, e misturá-la com a preferência
    de quem está olhando faria a mesma conta valer números diferentes para dois
    membros da mesma casa.
    """
    try:
        destino = (
            normalize_currency_code(currency)
            if currency
            else workspace_base_currency(session, workspace_id)
        )
    except InvalidCurrencyCode as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return PayablesService.list_workspace_payables(
        session, workspace_id, _mes(month), destino,
        # Sem acesso completo, só as contas que me envolvem (ADR 0018) — mesmo
        # desenho de `debts.get_debts`: a política é decidida aqui, onde o
        # `membership` existe, e o serviço aplica o recorte que recebeu.
        viewer_user_id=None if has_full_access(membership) else membership.user_id,
        incluir_atrasadas=include_overdue,
    )


@router.post("/settle", response_model=SettleResult)
def settle_payables(
    workspace_id: int,
    body: SettleRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Marca as contas como pagas (ou desfaz), gravando `settled_at`.

    É a única porta que move dinheiro para o caixa sem editar o lançamento — e
    por isso ela **não** mexe em `status`: competência e caixa são eixos
    separados (ADR 0022/0029), e marcar um boleto como pago não pode congelar a
    despesa como o status `paid` congela.

    Linha que não pode ser liquidada (cancelada, no cartão, de outra pessoa) é
    PULADA e contada, nunca recusada: quem confirma cinco contas não pode ver a
    operação inteira falhar por causa de uma.
    """
    resultado = PayablesService.settle(
        session, workspace_id, membership, body.transaction_ids,
        settled=body.settled, settled_on=body.settled_on,
    )
    if resultado["updated"]:
        # Um evento agregado, não N: marcar dez contas não pode virar dez
        # rodadas de refetch em todo mundo que está com a tela aberta.
        publish_event(
            session, workspace_id, "transaction.bulk_updated",
            "transaction", None, membership.user_id,
        )
    session.commit()
    return {"status": "ok", **resultado}
