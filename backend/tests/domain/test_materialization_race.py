"""Invariantes de unicidade da Onda A (A1 e A2).

O dedup da materialização e o gate de "já é membro" eram lê-depois-escreve em
Python — corretos em execução sequencial e inúteis sob concorrência, que é
exatamente como o app roda (a materialização dispara de ROTAS DE LEITURA e o
Início pede summary + reports + transactions em paralelo).

Estes testes atacam as duas metades da correção:
  1. a barreira existe NO BANCO (a unique recusa a segunda linha);
  2. o código ABSORVE a colisão de quem perde a corrida, sem 500 e sem
     derrubar o resto do lote.

Nenhum deles passa sem a migração d3b7f1a86c40.
"""
from datetime import date, datetime, UTC
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.income import Income
from app.models.recurring import RecurringIncome
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.membership_service import ensure_membership
from app.services.recurring_service import RecurringIncomeService


def _setup(db_session: Session, tag: str):
    user = User(name="Gabriel", email=f"{tag}@t.com", password_hash="h")
    ws = Workspace(name=f"WS-{tag}")
    db_session.add_all([user, ws])
    db_session.flush()
    return user, ws


# --- A1: renda recorrente ---------------------------------------------------


def test_unique_bloqueia_renda_recorrente_duplicada(db_session: Session):
    """A mesma ocorrência não pode existir duas vezes — nem por caminho torto."""
    user, ws = _setup(db_session, "race1")
    tmpl = RecurringIncome(
        title="Salário", base_amount=Decimal("5000.00"), day_of_month=5,
        user_id=user.id,
    )
    db_session.add(tmpl)
    db_session.flush()

    occ = datetime(2026, 7, 5, tzinfo=UTC)
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), received_at=occ,
        user_id=user.id,
        recurring_income_id=tmpl.id, billing_month="2026-07",
    ))
    db_session.commit()

    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), received_at=occ,
        user_id=user.id,
        recurring_income_id=tmpl.id, billing_month="2026-07",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_renda_avulsa_nao_colide(db_session: Session):
    """recurring_income_id NULL: NULLs são distintos, renda avulsa repete à vontade."""
    user, ws = _setup(db_session, "race2")
    occ = datetime(2026, 7, 5, tzinfo=UTC)
    for _ in range(3):
        db_session.add(Income(
            title="Bico", amount=Decimal("100.00"), received_at=occ,
            user_id=user.id,
        ))
    db_session.commit()

    rows = db_session.exec(select(Income).where(Income.user_id == user.id)).all()
    assert len(rows) == 3


def test_materializacao_absorve_colisao_e_segue_o_lote(db_session: Session):
    """Colisão numa ocorrência não pode derrubar as outras do mesmo lote.

    Cenário real: o dedup de `generate_due_income` filtra por `billing_month`,
    então uma entrada com o MESMO received_at e billing_month diferente passa
    despercebida por ele e só é barrada pela unique. Antes do savepoint isso
    estourava IntegrityError e o lote inteiro era perdido (engolido pelo
    `except Exception` de ensure_and_commit, sem log).
    """
    user, ws = _setup(db_session, "race3")
    ocupado = RecurringIncome(
        title="Salário", base_amount=Decimal("5000.00"), day_of_month=5,
        user_id=user.id,
    )
    livre = RecurringIncome(
        title="Aluguel recebido", base_amount=Decimal("1200.00"), day_of_month=20,
        user_id=user.id,
    )
    db_session.add_all([ocupado, livre])
    db_session.flush()

    # Ocupa a vaga do dia 5 com billing_month divergente (invisível ao dedup)
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"),
        received_at=datetime(2026, 7, 5, tzinfo=UTC),
        user_id=user.id,
        recurring_income_id=ocupado.id, billing_month="2026-06",
    ))
    db_session.commit()

    created = RecurringIncomeService.generate_due_income(db_session, user.id, date(2026, 7, 15))
    db_session.commit()

    # A ocorrência em colisão é pulada; a outra é criada normalmente
    assert created == 1
    do_livre = db_session.exec(
        select(Income).where(Income.recurring_income_id == livre.id)
    ).all()
    assert len(do_livre) == 1
    do_ocupado = db_session.exec(
        select(Income).where(Income.recurring_income_id == ocupado.id)
    ).all()
    assert len(do_ocupado) == 1


# --- A2: membership ---------------------------------------------------------


def test_unique_bloqueia_membership_duplicada(db_session: Session):
    user, ws = _setup(db_session, "race4")
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.commit()

    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.viewer
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_ensure_membership_e_idempotente(db_session: Session):
    user, ws = _setup(db_session, "race5")
    assert ensure_membership(db_session, ws.id, user.id, WorkspaceRole.member) is True
    assert ensure_membership(db_session, ws.id, user.id, WorkspaceRole.admin) is False
    db_session.commit()

    rows = db_session.exec(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws.id)
    ).all()
    assert len(rows) == 1
    # A segunda chamada não promove nem rebaixa quem já é membro
    assert rows[0].role == WorkspaceRole.member


def test_ensure_membership_absorve_leitura_obsoleta(db_session: Session, monkeypatch):
    """Simula a corrida: a checagem "já é membro" enxerga um estado vazio que já
    não vale. Sem o savepoint, a segunda chamada estouraria IntegrityError e
    devolveria 500 no aceite de convite."""
    user, ws = _setup(db_session, "race6")
    db_session.flush()

    monkeypatch.setattr(
        "app.services.membership_service.find_membership", lambda *a, **k: None
    )

    assert ensure_membership(db_session, ws.id, user.id, WorkspaceRole.member) is True
    # Leitura obsoleta diz "não é membro", mas o banco discorda: absorvido
    assert ensure_membership(db_session, ws.id, user.id, WorkspaceRole.member) is False
    db_session.commit()

    rows = db_session.exec(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws.id)
    ).all()
    assert len(rows) == 1
