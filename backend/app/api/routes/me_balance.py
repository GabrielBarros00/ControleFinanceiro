"""Quanto dinheiro eu tenho, onde ele está e quanto vou ter (ADR 0034).

Três perguntas que o app não respondia, num endpoint só porque a tela as mostra
juntas e o custo é compartilhado (o saldo atual é insumo do projetado):

- **saldo atual** — o dinheiro que existe agora, por conta e no total;
- **a receber / a pagar** — o que se sabe que entra e sai até o fim do mês;
- **saldo projetado** — a soma dos três.

Fora de `/me/overview` de propósito. Aquela é a rota mais chamada do app e já paga
o ledger de dívidas; empilhar a varredura do saldo nela encareceria o caminho de
todo mundo para servir uma seção. Aqui a família de cache é própria (`me-balance`),
então a tela de Contas e o Seu mês compartilham a mesma resposta.

Tudo é PESSOAL (ADR 0021): o gate é `get_current_user` e o recorte é
`owner_user_id`. Nenhum papel de workspace alcança saldo, extrato, ajuste ou
transferência de outra pessoa — dividir despesa com alguém não dá acesso ao
extrato bancário dele.
"""
from datetime import UTC, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns
from app.domain.dates import (
    InvalidMonth,
    civil_instant,
    parse_month,
    today_local,
)
from app.models.account_ledger import AccountTransfer
from app.models.payment_account import PaymentAccount
from app.models.user import User
from app.schemas.common import StatusRead
from app.schemas.balance import (
    BalanceRead,
    TransferCreate,
    TransferRead,
)
from app.services.account_balance_service import AccountBalanceService
from app.services.projection_service import ProjectionService

router = APIRouter(prefix="/me", tags=["me-balance"])


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O 307 do Starlette perde o cookie de sessão no salto — armadilha conhecida
    deste projeto. Registrar os dois caminhos elimina o redirecionamento em vez de
    tentar sobreviver a ele.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


def _conta_do_usuario(session: Session, account_id: int, user_id: int) -> PaymentAccount:
    conta = session.get(PaymentAccount, account_id)
    if not conta or conta.deleted_at:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    assert_owns(conta.owner_user_id, user_id, detail="Conta não encontrada")
    return conta


@_colecao("get", "/balance", response_model=BalanceRead)
def get_balance(
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Saldo atual por conta + a projeção até o fim do mês pedido."""
    try:
        referencia = parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    saldos = AccountBalanceService.balances(session, current_user.id)
    projecao = ProjectionService.ate_o_fim_do_mes(
        session, current_user.id, referencia, saldos["currency"], saldos["total"]
    )
    return {**saldos, **projecao}


# ---------------------------------------------------------------------------
# Transferência entre contas


@_colecao("get", "/transfers", response_model=List[TransferRead])
def list_transfers(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    minhas = select(PaymentAccount.id).where(
        PaymentAccount.owner_user_id == current_user.id
    )
    linhas = session.exec(
        select(AccountTransfer)
        .where(AccountTransfer.deleted_at.is_(None))
        .where(
            AccountTransfer.from_account_id.in_(minhas)
            | AccountTransfer.to_account_id.in_(minhas)
        )
        .order_by(AccountTransfer.occurred_at.desc())
        .limit(limit)
    ).all()
    nomes = {
        c.id: c.name
        for c in session.exec(
            select(PaymentAccount).where(
                PaymentAccount.owner_user_id == current_user.id
            )
        ).all()
    }
    return [
        {
            **t.model_dump(),
            "from_account_name": nomes.get(t.from_account_id, ""),
            "to_account_name": nomes.get(t.to_account_id, ""),
        }
        for t in linhas
    ]


@_colecao("post", "/transfers", response_model=TransferRead)
def create_transfer(
    body: TransferCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Move dinheiro de uma conta para outra. Não é renda, não é despesa.

    **Uma linha com as duas pernas.** Duas linhas ligadas por um id comum
    dependeriam de a aplicação lembrar de gravar as duas; assim, meia transferência
    não é representável — a atomicidade é do esquema, não do cuidado de quem
    programa. O `CHECK` de contas distintas fecha o outro caso degenerado.

    **Moedas diferentes exigem os dois valores.** Nada é convertido em silêncio
    (ADR 0006/0015): quem transfere informa quanto saiu e quanto entrou, e a taxa
    é derivada e conferida contra os dois. Três números que podem discordar dariam
    um saldo que depende de qual deles se lê.
    """
    if body.from_account_id == body.to_account_id:
        raise HTTPException(
            status_code=400, detail="A conta de origem e a de destino são a mesma"
        )
    origem = _conta_do_usuario(session, body.from_account_id, current_user.id)
    destino = _conta_do_usuario(session, body.to_account_id, current_user.id)
    for conta in (origem, destino):
        if not conta.active:
            raise HTTPException(
                status_code=400, detail=f"Conta '{conta.name}' está desativada"
            )

    mesma_moeda = origem.currency == destino.currency
    to_amount = body.to_amount if body.to_amount is not None else body.from_amount
    if mesma_moeda:
        if body.to_amount is not None and body.to_amount != body.from_amount:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"As duas contas são em {origem.currency}: o valor que sai e o "
                    "que entra têm de ser o mesmo"
                ),
            )
        taxa = None
    else:
        if body.to_amount is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Transferência de {origem.currency} para {destino.currency}: "
                    "informe também quanto entrou na conta de destino. O sistema "
                    "não converte por conta própria"
                ),
            )
        taxa = (body.to_amount / body.from_amount).quantize(Decimal("0.000001"))

    transferencia = AccountTransfer(
        from_account_id=origem.id,
        to_account_id=destino.id,
        from_amount=body.from_amount,
        to_amount=to_amount,
        exchange_rate=taxa,
        occurred_at=civil_instant(body.occurred_on or today_local()),
        note=body.note,
        created_by_user_id=current_user.id,
    )
    session.add(transferencia)
    session.commit()
    session.refresh(transferencia)
    return {
        **transferencia.model_dump(),
        "from_account_name": origem.name,
        "to_account_name": destino.name,
    }


@router.delete("/transfers/{transfer_id}", response_model=StatusRead)
def delete_transfer(
    transfer_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft delete: as duas pernas somem juntas, porque são a mesma linha."""
    t = session.get(AccountTransfer, transfer_id)
    if not t or t.deleted_at:
        raise HTTPException(status_code=404, detail="Transferência não encontrada")
    origem = session.get(PaymentAccount, t.from_account_id)
    assert_owns(
        origem.owner_user_id if origem else None,
        current_user.id,
        detail="Transferência não encontrada",
    )
    t.deleted_at = datetime.now(UTC)
    session.add(t)
    session.commit()
    return {"status": "ok"}
