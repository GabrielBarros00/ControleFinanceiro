"""Cartão de crédito PESSOAL e o ciclo da fatura — sem workspace (ADR 0021).

Este módulo é a correção do P0 da auditoria. O que existia antes:

- `GET /workspaces/{id}/credit-cards` serializava `limit`, `available_limit`,
  `committed_amount` e `next_due` de todo cartão alcançado por
  `cards_of_workspace` — que incluía os compartilhados com nível `use`, cujo
  contrato dizia justamente que limite e fatura continuavam sendo do dono. O
  predicado que implementava esse contrato (`card_full_access_here`) existia sem
  um único chamador.
- `GET .../statements/{id}` devolvia as transações filtrando **só** por
  `statement_id`: sem workspace, sem envolvimento. A fatura de um cartão trazia
  junto as compras privadas feitas em outro workspace.
- `close`, `pay` e `reopen` pediam apenas `require_role(member)`. Qualquer membro
  que enxergasse o cartão controlava o ciclo da fatura do dono.

Nada disso é remendável endpoint a endpoint, porque a origem era o cartão morar
num workspace. Aqui o gate é `get_current_user` + `CreditCard.owner_user_id`, e
não existe caminho de leitura por workspace: a fatura de outra pessoa responde
404 em qualquer papel.
"""
from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns, personal_scope
from app.domain.query_policy import resolve_personal_currency
from app.models.credit_card import (
    CardStatement,
    CreditCard,
    StatementPayment,
    StatementStatus,
)
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX, OptionalCurrencyCode, StatusRead
from app.schemas.credit_card import (
    CreditCardRead,
    StatementDetailRead,
    StatementListItemRead,
    StatementRead,
    StatementTargetRead,
)
from app.services.credit_card_service import CreditCardService, StatementStateError

router = APIRouter(prefix="/me/credit-cards", tags=["me-credit-cards"])


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O redirecionamento automático de barra do Starlette responde 307, e nesse
    salto o **cookie de sessão não acompanha** — a URL com a barra "errada"
    devolvia 401 em vez de funcionar. Registrar os dois caminhos elimina o
    redirecionamento em vez de tentar sobreviver a ele.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


class CreditCardCreate(BaseModel):
    """Schema explícito de criação — evita mass assignment de id/deleted_at."""
    name: str = Field(min_length=1, max_length=NAME_MAX)
    limit: Decimal = Field(gt=0, le=MAX_MONEY)
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)
    # None = "não informada" → a rota resolve para a moeda de relatório do dono
    currency: OptionalCurrencyCode = None


class CreditCardUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    limit: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    closing_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)


class StatementPayRequest(BaseModel):
    account_id: Optional[int] = None
    amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    paid_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)


def _get_card_or_404(session: Session, card_id: int, user_id: int) -> CreditCard:
    card = session.get(CreditCard, card_id)
    if not card or card.deleted_at:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    assert_owns(card.owner_user_id, user_id, detail="Cartão não encontrado")
    return card


def _get_statement_or_404(session: Session, card: CreditCard, statement_id: int) -> CardStatement:
    stmt = session.get(CardStatement, statement_id)
    if not stmt or stmt.card_id != card.id:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return stmt


def _payments_by_statement(
    session: Session, statement_ids: list[int]
) -> dict[int, list[StatementPayment]]:
    """Pagamentos vivos agrupados por fatura, numa consulta só.

    A lista de faturas serializa N linhas; buscar os pagamentos dentro de
    `_serialize_statement` seria um SELECT por fatura.
    """
    if not statement_ids:
        return {}
    linhas = session.exec(
        select(StatementPayment)
        .where(StatementPayment.statement_id.in_(statement_ids))
        .where(StatementPayment.deleted_at.is_(None))
        .order_by(StatementPayment.paid_at)
    ).all()
    agrupado: dict[int, list[StatementPayment]] = {}
    for p in linhas:
        agrupado.setdefault(p.statement_id, []).append(p)
    return agrupado


def _serialize_statement(
    session: Session,
    stmt: CardStatement,
    payments: Optional[list[StatementPayment]] = None,
    card: Optional[CreditCard] = None,
    excluidos: Optional[int] = None,
) -> dict:
    """`payments=None` busca sozinho; quem serializa uma LISTA passa o grupo já
    carregado para não disparar uma consulta por fatura. `excluidos` segue a
    mesma regra — ver `CreditCardService.excluded_counts`."""
    if payments is None:
        payments = _payments_by_statement(session, [stmt.id]).get(stmt.id, [])
    total = CreditCardService.effective_total(session, stmt)
    pago = sum((p.amount for p in payments), Decimal("0.00"))
    saldo = total - pago
    card = card or session.get(CreditCard, stmt.card_id)
    if excluidos is None:
        excluidos = (
            CreditCardService.excluded_from_total_count(session, stmt.id, card) if card else 0
        )
    return {
        **stmt.model_dump(),
        "computed_total": total,
        "is_overdue": CreditCardService.is_overdue(stmt),
        "paid_amount": pago,
        "remaining_amount": saldo if saldo > 0 else Decimal("0.00"),
        "payments": payments,
        # Lançamento vivo que a fatura não soma (linha legada sem perna de
        # fatura). Zero na esmagadora maioria — mas quando não é, a tela precisa
        # dizer, senão o total parece completo estando incompleto.
        "excluded_from_total_count": excluidos,
    }


def _serialize_card(session: Session, card: CreditCard) -> dict:
    overview = CreditCardService.card_overview(session, card)
    committed = overview["committed"]
    attention: Optional[CardStatement] = overview["attention"]
    return {
        **card.model_dump(),
        "committed_amount": committed,
        "available_limit": CreditCardService.available_limit(committed, card),
        # Fatura que pede atenção (a não paga mais antiga com valor): permite à
        # tela avisar "fechada", "vence em N dias" ou "vencida" por cartão, sem
        # precisar carregar as faturas de cada um.
        "next_due": None if attention is None else {
            "statement_id": attention.id,
            "month": attention.month,
            "status": attention.status,
            "closing_date": attention.closing_date,
            "due_date": attention.due_date,
            "amount": overview["attention_total"],
            "is_overdue": CreditCardService.is_overdue(attention),
        },
    }


@_colecao("get", "", response_model=list[CreditCardRead])
def list_credit_cards(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    cards = session.exec(
        select(CreditCard).where(
            personal_scope(CreditCard.owner_user_id, current_user.id),
            CreditCard.deleted_at.is_(None),
        ).order_by(CreditCard.name)
    ).all()
    return [_serialize_card(session, card) for card in cards]


@_colecao("post", "", response_model=CreditCardRead)
def create_credit_card(
    card_in: CreditCardCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    data = card_in.model_dump()
    data["currency"] = resolve_personal_currency(session, current_user.id, card_in.currency)
    card = CreditCard(**data, owner_user_id=current_user.id)
    session.add(card)
    session.commit()
    session.refresh(card)
    return _serialize_card(session, card)


@router.put("/{card_id}", response_model=CreditCardRead)
def update_credit_card(
    card_id: int,
    card_in: CreditCardUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    card = _get_card_or_404(session, card_id, current_user.id)
    update_data = card_in.model_dump(exclude_unset=True)
    ciclo_mudou = any(
        campo in update_data and update_data[campo] != getattr(card, campo)
        for campo in ("closing_day", "due_day")
    )
    for key, value in update_data.items():
        setattr(card, key, value)
    card.updated_at = datetime.now(UTC)
    session.add(card)
    # Mudar os dias do ciclo tem que valer para a fatura em aberto: as datas
    # dela eram congeladas na criação, então corrigir o vencimento no cadastro
    # não mudava nada na tela — e o aviso continuava anunciando a data antiga.
    if ciclo_mudou:
        session.flush()
        CreditCardService.resync_open_statement_dates(session, card)
    session.commit()
    session.refresh(card)
    return _serialize_card(session, card)


@router.delete("/{card_id}", response_model=StatusRead)
def delete_credit_card(
    card_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    card = _get_card_or_404(session, card_id, current_user.id)

    # Fatura em aberto trava a exclusão. O soft delete só escondia o cartão: as
    # faturas não pagas continuavam existindo e ficavam INALCANÇÁVEIS (fechar/
    # pagar/reabrir passam por _get_card_or_404, que recusa cartão excluído).
    # Pior, a dívida sobrevivia só de um lado — a previsão somava a fatura e o
    # Endividamento não —, e não havia tela por onde resolver.
    overview = CreditCardService.card_overview(session, card)
    abertas = [
        s for s in overview["statements"]
        if s.status != StatementStatus.paid
        and CreditCardService.effective_total(session, s) > 0
    ]
    if abertas:
        meses = ", ".join(s.month for s in abertas[:3])
        reticencias = "…" if len(abertas) > 3 else ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"Há {len(abertas)} fatura(s) em aberto neste cartão ({meses}{reticencias}). "
                "Pague-as (ou reabra e zere) antes de excluir — senão a dívida ficaria "
                "sem nenhuma tela por onde ser quitada."
            ),
        )

    card.deleted_at = datetime.now(UTC)
    session.add(card)
    session.commit()
    return {"status": "ok"}


@router.get("/{card_id}/statement-for", response_model=StatementTargetRead)
def statement_for_date(
    card_id: int,
    # `date`, não `datetime`: o formulário tem um `<input type="date">` e manda
    # `YYYY-MM-DD`. Tipado como `datetime` isso virava meia-noite NAIVE, que o
    # roteamento lê como instante UTC e resolve para o dia anterior — o preview
    # anunciaria uma fatura e o POST gravaria em outra. Um preview que mente
    # sobre o destino é pior que preview nenhum.
    on: date,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Em qual fatura cairia uma compra neste cartão neste DIA (ADR 0002).

    A fatura é derivada no SERVIDOR, e a regra não é óbvia: a partir do dia de
    fechamento a compra vai para o mês seguinte, e se essa fatura já estiver
    fechada/paga ela rola para frente. Somente LEITURA: não cria fatura (senão
    digitar no formulário criaria faturas vazias).
    """
    card = _get_card_or_404(session, card_id, current_user.id)
    return CreditCardService.preview_statement_target(session, card, on)


@router.get("/{card_id}/statements", response_model=list[StatementListItemRead])
def list_statements(
    card_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    card = _get_card_or_404(session, card_id, current_user.id)
    # Materializa a fatura do ciclo corrente antes de listar: um mês sem compras
    # não gerava fatura e a tela abria no mês anterior como se fosse o atual.
    # Best-effort — nunca derruba o GET (a criação é acessória à leitura).
    current_month = None
    try:
        current_month = CreditCardService.ensure_current_statement(session, card).month
        session.commit()
    except Exception:
        session.rollback()
    statements = session.exec(
        select(CardStatement)
        .where(CardStatement.card_id == card.id)
        .order_by(CardStatement.month.desc())
    ).all()
    ids = [s.id for s in statements]
    pagamentos = _payments_by_statement(session, ids)
    # Em lote pela mesma razão dos pagamentos: por fatura eram duas contagens
    # dentro do laço, ~120 consultas num cartão com 60 meses de histórico.
    excluidos = CreditCardService.excluded_counts(session, ids, card)
    # is_current marca o ciclo aberto de hoje. A tela não pode deduzir isso de
    # "a mais recente": uma compra lançada com data futura cria uma fatura à
    # frente, e ela não é a fatura atual.
    return [
        {
            # `card=card` fecha mais um SELECT por fatura: todas são deste cartão,
            # que a rota já carregou para autorizar.
            **_serialize_statement(
                session, s, pagamentos.get(s.id, []), card, excluidos.get(s.id, 0)
            ),
            "is_current": s.month == current_month,
        }
        for s in statements
    ]


@router.get("/{card_id}/statements/{statement_id}", response_model=StatementDetailRead)
def get_statement(
    card_id: int,
    statement_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """A fatura com as compras dela.

    As transações saem sem filtro adicional de propósito, e agora isso é correto:
    a fatura é de um cartão que é do usuário logado, então tudo que caiu nela foi
    comprado por ele. Era a MESMA query de antes — o que a tornava um vazamento
    era o cartão poder ser de outra pessoa.

    `workspace_id` viaja em cada linha porque a compra continua morando num
    workspace: é o que permite à tela dizer "esta parcela caiu na Casa".

    A população é a MESMA de `compute_statement_total`, por construção
    (`statement_population`). Aqui havia só `statement_id` + `deleted_at`: a lista
    trazia rascunho e cancelada, que o total ignora, e trazia lançamento de
    qualquer moeda, que o total também ignorava. A tela mostrava linhas que o
    rodapé não somava e ninguém tinha como perceber qual dos dois estava certo.
    """
    card = _get_card_or_404(session, card_id, current_user.id)
    stmt = _get_statement_or_404(session, card, statement_id)

    transactions = session.exec(
        select(Transaction)
        .where(*CreditCardService.statement_population(stmt.id, card))
        .order_by(Transaction.transaction_date.desc())
    ).all()

    return {
        **_serialize_statement(session, stmt),
        "transactions": transactions,
    }


# ---- Ciclo da fatura (ADR 0011) --------------------------------------------
# Sem guarda de dono nos três: a ROTA inteira é do dono. Antes cada uma pedia
# `require_role(member)` no workspace, e era assim que um membro qualquer fechava
# ou pagava a fatura de outra pessoa.


@router.post("/{card_id}/statements/{statement_id}/close", response_model=StatementRead)
def close_statement(
    card_id: int,
    statement_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    card = _get_card_or_404(session, card_id, current_user.id)
    stmt = _get_statement_or_404(session, card, statement_id)
    try:
        CreditCardService.close_statement(session, stmt)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    session.commit()
    session.refresh(stmt)
    return _serialize_statement(session, stmt)


@router.post("/{card_id}/statements/{statement_id}/pay", response_model=StatementRead)
def pay_statement(
    card_id: int,
    statement_id: int,
    body: StatementPayRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    card = _get_card_or_404(session, card_id, current_user.id)
    stmt = _get_statement_or_404(session, card, statement_id)

    account = None
    if body.account_id is not None:
        account = session.get(PaymentAccount, body.account_id)
        # A conta de origem tem de ser DO DONO do cartão. Antes a checagem era
        # `account.workspace_id != workspace_id`, que num modelo de recurso
        # pessoal não quer dizer nada.
        if not account or account.deleted_at or account.owner_user_id != current_user.id:
            raise HTTPException(status_code=400, detail="Conta inválida")
        if not account.active:
            raise HTTPException(status_code=400, detail="Conta inativa não pode originar pagamento")

    try:
        CreditCardService.pay_statement(
            session,
            stmt,
            account=account,
            amount=body.amount,
            paid_at=body.paid_at,
            note=body.note,
            user_id=current_user.id,
        )
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    session.commit()
    session.refresh(stmt)
    return _serialize_statement(session, stmt)


@router.post("/{card_id}/statements/{statement_id}/reopen", response_model=StatementRead)
def reopen_statement(
    card_id: int,
    statement_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    card = _get_card_or_404(session, card_id, current_user.id)
    stmt = _get_statement_or_404(session, card, statement_id)
    try:
        CreditCardService.reopen_statement(session, stmt)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    session.commit()
    session.refresh(stmt)
    return _serialize_statement(session, stmt)
