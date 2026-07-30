from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.db.session import get_session
from app.api.routes import (
    analytics, attachments, audit, auth, categories, debts, imports, me,
    me_accounts, me_cards, me_financing, me_income, members, notifications,
    recurring, settlements, tags, transactions, workspaces,
)
from app.ws import routes as ws_routes

router = APIRouter(prefix="/api/v1")

# --- Espaço de COLABORAÇÃO: o que a casa compartilha (ADR 0018) --------------
# Lançamentos e o que os descreve, mais a administração do próprio workspace.
router.include_router(workspaces.router)
router.include_router(members.router)
router.include_router(members.invites_router)
router.include_router(transactions.router)
router.include_router(analytics.router)
router.include_router(recurring.router)
router.include_router(debts.router)
router.include_router(settlements.router)
router.include_router(imports.router)
router.include_router(categories.router)
router.include_router(tags.router)
router.include_router(attachments.router)
router.include_router(audit.router)

# --- Espaço PESSOAL: o que é da pessoa e a acompanha (ADR 0020 + 0021) -------
# Sem `workspace_id` no caminho e sem membership no gate. Cartão, conta,
# financiamento e renda vieram de `/workspaces/{id}/...` nesta onda: enquanto
# moravam lá, toda consulta escopada por workspace podia alcançá-los, e uma
# delas alcançava — a listagem de cartões entregava limite e fatura do dono a
# quem tivesse acesso completo no workspace de destino.
router.include_router(me.router)
router.include_router(me_income.router)
router.include_router(me_cards.router)
router.include_router(me_accounts.router)
router.include_router(me_financing.router)

router.include_router(auth.router)
router.include_router(notifications.router)
router.include_router(ws_routes.router)

@router.get("/health")
def health_check(session: Session = Depends(get_session)):
    """Saúde REAL: inclui um toque no banco.

    Antes respondia `ok` sem consultar nada — com o Postgres fora do ar o
    healthcheck do container continuava verde e o orquestrador nunca reiniciava
    nada. Versão vem das settings (a constante embutida ia divergir no 1º bump).
    """
    body = {"status": "ok", "version": settings.APP_VERSION, "database": "ok"}
    try:
        session.exec(text("SELECT 1")).one()
    except Exception:
        body["status"] = "degraded"
        body["database"] = "unavailable"
        return JSONResponse(status_code=503, content=body)
    return body
