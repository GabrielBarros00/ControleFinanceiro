from fastapi import APIRouter
from app.api.routes import (
    auth, workspaces, members, transactions, income, analytics, credit_cards,
    recurring, recurring_income, debts, imports, categories, financing, settlements, tags, attachments,
    payment_accounts, audit,
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
router.include_router(settlements.router)
router.include_router(imports.router)
router.include_router(categories.router)
router.include_router(financing.router)
router.include_router(tags.router)
router.include_router(attachments.router)
router.include_router(payment_accounts.router)
router.include_router(audit.router)
router.include_router(ws_routes.router)

@router.get("/health")
async def health_check():
    return {"status": "ok", "version": "4.0.0"}
