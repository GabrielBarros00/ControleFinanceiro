"""Renda PESSOAL, avulsa e recorrente — sem workspace no caminho (ADR 0021).

Renda é da pessoa. Sempre foi, mas o cadastro morava em
`/workspaces/{id}/income` e isso tinha duas consequências que a auditoria pegou:

1. **A moeda vinha do workspace aberto.** `resolve_currency(session, workspace_id, …)`
   fazia a MESMA renda pessoal nascer em USD ou em BRL conforme a tela por onde
   foi criada — e depois entrar ou sair dos totais conforme a moeda de quem
   estivesse olhando. Aqui a moeda é a de relatório do dono.
2. **Existia renda "da casa"** (`scope="workspace"`), que sem modelo de
   beneficiários era creditada 100% a quem cadastrou no resultado pessoal: o
   aluguel recebido pelo casal aparecia inteiro para um só. Sem rateio, renda
   compartilhada mente; renda estritamente pessoal não tem o que ratear.

O gate é `get_current_user` e o recorte é `Income.user_id`. Não há papel nem
`financial_access` que alcance a renda de outra pessoa — salário é o dado mais
sensível do sistema.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import personal_scope
from app.domain.dates import (
    InvalidMonth,
    month_bounds_utc,
    month_key,
    parse_month,
    today_local,
)
from app.models.income import Income
from app.models.recurring import RecurringIncome
from app.models.user import User
from app.schemas.common import CreatedCountRead, StatusRead
from app.schemas.income import (
    IncomeCreate,
    IncomeReceiveRequest,
    IncomeRead,
    IncomeUpdate,
    RecurringIncomeCreate,
    RecurringIncomeUpdate,
)
from app.services.recurring_service import (
    RecurringIncomeService,
    RecurringMaterializationService,
)

from app.services.commands import income as inc_cmd

router = APIRouter(prefix="/me", tags=["me-income"])


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O redirecionamento automático de barra do Starlette responde 307 — e o 307 é
    uma armadilha conhecida deste projeto: o cliente refaz a requisição para a
    URL nova e o **cookie de sessão não acompanha**, então `/me/income/` devolvia
    401 enquanto `/me/income` devolvia 200. Registrar os dois caminhos elimina o
    redirecionamento em vez de tentar sobreviver a ele.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


# ---------------------------------------------------------------------------
# Renda avulsa
# ---------------------------------------------------------------------------

@_colecao("post", "/income", response_model=IncomeRead)
def create_income(
    *,
    session: Session = Depends(get_session),
    income_in: IncomeCreate,
    current_user: User = Depends(get_current_user),
):
    db_income = inc_cmd.create_income(session, current_user.id, income_in)
    session.commit()
    session.refresh(db_income)
    return db_income


@_colecao("get", "/income", response_model=List[IncomeRead])
def list_income(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    month: Optional[str] = None,  # YYYY-MM: recorta pela competência (received_at)
):
    # Materializa recorrências vencidas só quando o mês pedido é o corrente: a
    # materialização é sempre restrita ao mês de hoje, então em mês fechado seria
    # trabalho perdido (e não casaria com o filtro).
    # `today_local`, não `datetime.now(UTC)`: entre 21h e a meia-noite em São
    # Paulo o UTC já é o mês seguinte, e nessas três horas do último dia do mês a
    # tela pedia o mês corrente e a materialização era pulada por "não é o mês
    # de hoje" — o salário do mês não aparecia até o dia virar de verdade.
    mes_corrente = month_key(today_local())
    if month is None or month == mes_corrente:
        RecurringMaterializationService.ensure_income_and_commit(session, current_user.id)

    statement = select(Income).where(
        Income.deleted_at.is_(None),
        personal_scope(Income.user_id, current_user.id),
    )

    # Filtro por COMPETÊNCIA (`received_at`), e é de propósito que ele NÃO seja o
    # mesmo recorte do `cash_in` de `/me/overview`, que desde o ADR 0034 usa
    # `settled_at`. As duas telas respondem perguntas diferentes: aqui é "quais
    # rendas são deste mês" — inclusive as previstas e as que ainda não caíram —,
    # lá é "quanto dinheiro entrou". É o mesmo par que Contas a pagar
    # (`billing_month`) e caixa (`settled_at`) já formam do lado da despesa.
    if month:
        # Mês inválido é ERRO, não "sem filtro". Antes o except engolia e a rota
        # devolvia o histórico INTEIRO como se fosse o mês pedido.
        try:
            ref = parse_month(month)
        except InvalidMonth as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # `month_bounds_utc`, a MESMA janela de `/me/overview` e do extrato:
        # `received_at` é um instante gravado em UTC e o mês é o do fuso do
        # usuário. Com o `month_bounds` ingênuo as duas telas discordavam — uma
        # renda das 22h de 31/07 aparecia na Visão global de julho e faltava na
        # página Rendas de julho, o pior tipo de divergência, porque cada tela
        # sozinha parece certa.
        inicio, fim = month_bounds_utc(ref)
        statement = statement.where(Income.received_at >= inicio, Income.received_at <= fim)

    return session.exec(statement.order_by(Income.received_at.desc())).all()


@router.put("/income/{income_id}", response_model=IncomeRead)
def update_income(
    income_id: int,
    income_in: IncomeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    income = inc_cmd.update_income(session, current_user.id, income_id, income_in)
    session.commit()
    session.refresh(income)
    return income


@router.post("/income/{income_id}/receive", response_model=IncomeRead)
def receive_income(
    income_id: int,
    body: IncomeReceiveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """"Recebi": a renda prevista vira caixa, na data e na conta informadas.

    Idempotente por natureza — confirmar duas vezes reescreve a mesma data. O que
    ela NÃO faz é mexer em `received_at`: a competência da renda é de setembro
    mesmo que o salário caia em 2 de outubro, e mover a data de competência para
    "fazer bater" jogaria o resultado de setembro para outubro.
    """
    income = inc_cmd.receive_income(session, current_user.id, income_id, body)
    session.commit()
    session.refresh(income)
    return income


@router.post("/income/{income_id}/unreceive", response_model=IncomeRead)
def unreceive_income(
    income_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Desfaz a confirmação: a renda volta a ser prevista.

    Existe pelo mesmo motivo que "reabrir despesa": confirmar a linha errada é um
    erro comum, e sem a volta a única saída seria excluir e recadastrar — o que
    perde a ligação com a recorrência e libera a vaga do tombstone.
    """
    income = inc_cmd.unreceive_income(session, current_user.id, income_id)
    session.commit()
    session.refresh(income)
    return income


@router.post("/income/{income_id}/cancel", response_model=IncomeRead)
def cancel_income(
    income_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """A renda prevista que não veio — e não virá.

    Diferente de excluir: a linha continua visível como "cancelada" e continua
    ocupando a vaga da unique de ocorrência, então a materialização não recria o
    salário do mês em que a pessoa disse que ele não vem. Excluir também seguraria
    a vaga, mas some da tela — e uma renda que desaparece sem explicação é
    exatamente a experiência que esta onda existe para eliminar.
    """
    income = inc_cmd.cancel_income(session, current_user.id, income_id)
    session.commit()
    session.refresh(income)
    return income


@router.delete("/income/{income_id}", response_model=StatusRead)
def delete_income(
    income_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    inc_cmd.delete_income(session, current_user.id, income_id)
    session.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Renda recorrente
# ---------------------------------------------------------------------------

@_colecao("post", "/recurring-income", response_model=RecurringIncome)
def create_recurring_income(
    recurring_in: RecurringIncomeCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
):
    db_rec = inc_cmd.create_recurring_income(session, current_user.id, recurring_in, materialize)
    session.commit()
    session.refresh(db_rec)
    return db_rec


@_colecao("get", "/recurring-income", response_model=List[RecurringIncome])
def list_recurring_income(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(RecurringIncome).where(
            personal_scope(RecurringIncome.user_id, current_user.id)
        )
    ).all()


@router.post("/recurring-income/generate", response_model=CreatedCountRead)
def generate_recurring_income(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Materializa as rendas recorrentes do mês corrente (idempotente)."""
    created = RecurringIncomeService.generate_due_income(
        session, current_user.id, today_local()
    )
    session.commit()
    return {"created": created}


@router.put("/recurring-income/{recurring_id}", response_model=RecurringIncome)
def update_recurring_income(
    recurring_id: int,
    recurring_in: RecurringIncomeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
):
    db_rec = inc_cmd.update_recurring_income(
        session, current_user.id, recurring_id, recurring_in, materialize
    )
    session.commit()
    session.refresh(db_rec)
    return db_rec


@router.delete("/recurring-income/{recurring_id}", response_model=StatusRead)
def delete_recurring_income(
    recurring_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    inc_cmd.delete_recurring_income(session, current_user.id, recurring_id)
    session.commit()
    return {"status": "ok"}
