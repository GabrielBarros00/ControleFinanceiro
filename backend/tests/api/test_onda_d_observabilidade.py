"""Observabilidade e desempenho da Onda D."""
from datetime import date, datetime, UTC

from app.domain.dates import civil_instant
from decimal import Decimal

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.recurring import RecurringExpense
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.recurring_service import (
    RecurringMaterializationService,
    RecurringService,
)
from tests.support.rotas import rota_temporaria


@pytest.fixture
def ws(db_session: Session):
    user = User(name="G", email="ondad@t.com", password_hash="h")
    workspace = Workspace(name="WS-D")
    db_session.add_all([user, workspace])
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.commit()
    token = create_access_token({"sub": str(user.id)})
    return {
        "user": user,
        "ws": workspace,
        "headers": {"Cookie": "access_token=" + token},
    }


# --- D3: 500 observável -----------------------------------------------------


def test_erro_500_tem_request_id_e_cabecalhos(caplog):
    """A resposta 500 vem do ServerErrorMiddleware, FORA da pilha de middleware
    da app: não passava pelo logging nem pelos cabeçalhos de segurança."""
    boom = APIRouter()

    @boom.get("/api/v1/_boom_teste")
    def _boom():
        raise RuntimeError("falha proposital")

    with rota_temporaria(boom):
        with TestClient(app, raise_server_exceptions=False) as client:
            resposta = client.get("/api/v1/_boom_teste")
        assert resposta.status_code == 500
        assert resposta.headers.get("X-Request-ID")
        assert resposta.headers.get("X-Content-Type-Options") == "nosniff"
        assert resposta.headers.get("X-Frame-Options") == "DENY"
        assert resposta.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"


def test_erro_500_propaga_request_id_do_cliente():
    boom = APIRouter()

    @boom.get("/api/v1/_boom_teste2")
    def _boom():
        raise RuntimeError("falha proposital")

    with rota_temporaria(boom):
        with TestClient(app, raise_server_exceptions=False) as client:
            resposta = client.get(
                "/api/v1/_boom_teste2", headers={"x-request-id": "meu-id-123"}
            )
        assert resposta.headers.get("X-Request-ID") == "meu-id-123"


# --- D1: materialização não falha em silêncio -------------------------------


def test_falha_de_materializacao_e_logada(db_session: Session, ws, monkeypatch, capsys):
    """`except Exception: rollback` engolia tudo — o usuário só via 'a
    recorrência não apareceu' e não havia rastro nenhum.

    Usa capsys (não caplog): o structlog do app escreve direto em stdout via
    PrintLogger, fora da cadeia de handlers do `logging`.
    """
    def _explode(*args, **kwargs):
        raise RuntimeError("falha proposital na materialização")

    # Template ativo: sem nenhum, `ensure_and_commit` sai antes de tentar
    # materializar (curto-circuito que evita um commit por GET) e a falha
    # proposital nunca aconteceria.
    db_session.add(RecurringExpense(
        title="Aluguel", base_amount=Decimal("100.00"), day_of_month=1,
        workspace_id=ws["ws"].id, created_by_user_id=ws["user"].id,
    ))
    db_session.commit()

    monkeypatch.setattr(
        RecurringMaterializationService, "ensure_current_month", _explode
    )
    resultado = RecurringMaterializationService.ensure_and_commit(
        db_session, ws["ws"].id
    )

    assert resultado == {"expenses": 0, "promoted": 0}
    saida = capsys.readouterr().out
    assert "materializacao_falhou" in saida
    assert "workspace_id" in saida


def test_viewer_nao_materializa_na_leitura(db_session: Session, ws):
    """Papel somente-leitura não pode provocar INSERT + COMMIT.

    A materialização preguiçosa roda no topo de 4 rotas GET, protegidas só por
    `get_workspace_membership` — ou seja, um `viewer` escrevia no banco só de
    abrir o extrato. Quem tem escrita materializa na primeira tela que abrir,
    então nada se perde.
    """
    db_session.add(RecurringExpense(
        title="Aluguel", base_amount=Decimal("100.00"), day_of_month=1,
        workspace_id=ws["ws"].id, created_by_user_id=ws["user"].id,
    ))
    db_session.commit()

    resultado = RecurringMaterializationService.ensure_and_commit(
        db_session, ws["ws"].id, role=WorkspaceRole.viewer
    )
    assert resultado == {"expenses": 0, "promoted": 0}
    assert db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws["ws"].id)
    ).all() == []

    # O mesmo workspace, lido por um member, materializa normalmente
    criadas = RecurringMaterializationService.ensure_and_commit(
        db_session, ws["ws"].id, role=WorkspaceRole.member
    )
    assert criadas["expenses"] == 1


def test_sem_template_ativo_nao_comita(db_session: Session, ws, monkeypatch):
    """Workspace sem recorrência não paga as consultas de dedup nem um commit a
    cada listagem — e são 4 rotas de leitura chamando isto."""
    def _nao_deveria(*args, **kwargs):
        raise AssertionError("materializou sem nenhum template ativo")

    monkeypatch.setattr(
        RecurringMaterializationService, "ensure_current_month", _nao_deveria
    )
    resultado = RecurringMaterializationService.ensure_and_commit(
        db_session, ws["ws"].id, role=WorkspaceRole.owner
    )
    assert resultado == {"expenses": 0, "promoted": 0}


# --- D9: materialização restrita ao template editado ------------------------


def test_generate_due_instances_aceita_template_id(db_session: Session, ws):
    """Salvar UMA recorrência varria e materializava TODAS as do workspace."""
    hoje = date.today()
    editado = RecurringExpense(
        title="Editado", base_amount=Decimal("10.00"), day_of_month=1,
        workspace_id=ws["ws"].id, created_by_user_id=ws["user"].id,
        payer_user_id=ws["user"].id,
    )
    outro = RecurringExpense(
        title="Outro", base_amount=Decimal("20.00"), day_of_month=1,
        workspace_id=ws["ws"].id, created_by_user_id=ws["user"].id,
        payer_user_id=ws["user"].id,
    )
    db_session.add_all([editado, outro])
    db_session.commit()

    criadas = RecurringService.generate_due_instances(
        db_session, ws["ws"].id, hoje, template_id=editado.id
    )
    db_session.commit()

    assert criadas == 1
    titulos = {
        t.title for t in db_session.exec(
            select(Transaction).where(Transaction.workspace_id == ws["ws"].id)
        ).all()
    }
    assert titulos == {"Editado"}, "só o template editado deve materializar"


# --- D4: duplicata só na janela do arquivo ----------------------------------


def test_parse_so_consulta_a_janela_do_arquivo(db_session: Session, ws, override_get_session):
    """Carregava TODAS as transações vivas do workspace a cada parse."""
    db_session.add(Transaction(
        title="Muito antiga", total_amount=Decimal("50.00"), currency="BRL",
        transaction_date=datetime(2019, 1, 5, tzinfo=UTC), billing_month="2019-01",
        workspace_id=ws["ws"].id,
    ))
    # `civil_instant` e não meia-noite: a heurística de duplicata compara o DIA
    # LOCAL dos dois lados, e `2026-08-10T00:00Z` é dia 9 em São Paulo — a linha
    # de 10/08 do CSV não seria a mesma despesa. Meia-noite aqui era uma data
    # civil disfarçada de instante, a mesma confusão que a Onda 9 desfez.
    db_session.add(Transaction(
        title="Na janela", total_amount=Decimal("50.00"), currency="BRL",
        transaction_date=civil_instant(date(2026, 8, 10)), billing_month="2026-08",
        workspace_id=ws["ws"].id,
    ))
    db_session.commit()

    csv = "Data;Descricao;Valor\n10/08/2026;Na janela;50,00\n"
    url = "/api/v1/workspaces/" + str(ws["ws"].id) + "/imports/parse"
    with TestClient(app) as client:
        resposta = client.post(
            url,
            headers=ws["headers"],
            files={"file": ("e.csv", csv, "text/csv")},
            data={
                "date_column": "Data", "description_column": "Descricao",
                "amount_column": "Valor", "date_format": "%d/%m/%Y",
                "delimiter": ";", "decimal_separator": ",",
            },
        )
    assert resposta.status_code == 200
    linhas = resposta.json()["rows"]
    assert len(linhas) == 1
    # A duplicata dentro da janela continua sendo detectada
    assert linhas[0]["duplicate"] is True
