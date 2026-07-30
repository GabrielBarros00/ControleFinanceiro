from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.db.session import get_session
from app.api.routes import (
    auth, workspaces, members, transactions, income, analytics, credit_cards,
    recurring, recurring_income, debts, imports, categories, financing, settlements, tags, attachments,
    payment_accounts, audit, liabilities, notifications, me,
)
from app.ws import routes as ws_routes

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router)
router.include_router(workspaces.router)
router.include_router(members.router)
router.include_router(members.invites_router)
router.include_router(transactions.router)
router.include_router(income.router)
router.include_router(analytics.router)
router.include_router(credit_cards.router)
router.include_router(recurring.router)
router.include_router(recurring_income.router)
router.include_router(debts.router)
router.include_router(liabilities.router)
router.include_router(settlements.router)
router.include_router(imports.router)
router.include_router(categories.router)
router.include_router(financing.router)
router.include_router(tags.router)
router.include_router(attachments.router)
router.include_router(payment_accounts.router)
router.include_router(audit.router)
router.include_router(notifications.router)
# Rotas PESSOAIS (sem workspace no caminho) — ADR 0020
router.include_router(me.router)
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
