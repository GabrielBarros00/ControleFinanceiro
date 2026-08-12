"""Invariantes sob concorrência REAL (F2).

O resto da suíte é sequencial, e o Playwright roda com `workers: 1` — nada no
projeto exercitava duas requisições ao mesmo tempo. Só que é exatamente aí que
mora a classe de bug das Ondas A e C: dedup lê-depois-escreve, `select` antes de
`insert`, `uses += 1` em Python. Todos passavam nos testes sequenciais.

Estes testes usam threads de verdade contra um banco de ARQUIVO (o padrão da
suíte é `:memory:` com StaticPool, que serializa tudo numa conexão só e
esconderia justamente o que queremos ver).

**Nem toda corrida é observável no SQLite.** O SQLite admite UM escritor por vez
e derruba os demais com `database is locked` — o que acidentalmente protege o
padrão lê-depois-escreve. As invariantes que dependem de MVCC (duas transações
lendo o mesmo estado e escrevendo as duas) só se reproduzem no Postgres, que é o
motor de produção; elas são marcadas com `precisa_de_mvcc` e ficam para o leg
`backend-postgres` do CI, via `TEST_DATABASE_URL`. Rodar só em SQLite e ver
verde NÃO é prova para essas — foi assim que a corrida do pagamento de fatura
sobreviveu à Onda 7.

Marcados com `concurrency` para poderem ser isolados quando necessário.
"""
import itertools
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal
from typing import Callable, List, Optional

import pytest
from sqlmodel import Session, SQLModel, create_engine, func, select

from app.models.category import Category
from app.models.credit_card import (
    CardStatement,
    CreditCard,
    StatementPayment,
    StatementStatus,
)
from app.models.financing import (
    AmortizationInstallment,
    AmortizationMethod,
    Financing,
    FinancingStatus,
)
from app.models.income import Income
from app.models.app_setting import AppSetting
from app.models.attachment import Attachment
from app.models.settlement import Settlement
from app.models.notification import Notification  # noqa: F401 (metadata)
from app.models.recurring import RecurringIncome
from app.models.registration_invite import RegistrationInvite
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.user import PlatformRole, User
from app.models.workspace import (
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.services.credit_card_service import CreditCardService
from app.services.debt_service import DebtService
from app.api.routes.admin import UserPatch, patch_user
from app.db.locks import trava_workspace
from app.api.routes.attachments import _ensure_quota
from app.api.routes.imports import CommitRequest, CommitRow, commit_import
from app.api.routes.members import accept_invite
from app.api.routes.settlements import SettlementCreate, create_settlement
from app.services.membership_service import ensure_membership
from app.services.registration_service import (
    assert_pode_cadastrar,
    assert_pode_convidar,
    consome_convite,
    cria_convite,
)
from app.services.recurring_service import RecurringIncomeService

pytestmark = pytest.mark.concurrency

THREADS = 8


def _request_falso():
    """As rotas de admin registram IP/user-agent na auditoria; aqui basta o mínimo."""
    from starlette.requests import Request

    return Request({
        "type": "http", "method": "PATCH", "path": "/admin/users/1",
        "headers": [], "client": ("127.0.0.1", 1234), "query_string": b"",
    })

#: Postgres quando o CI o oferece (`TEST_DATABASE_URL`), SQLite em arquivo senão.
_URL_TESTE = os.environ.get("TEST_DATABASE_URL", "")
TEM_MVCC = _URL_TESTE.startswith("postgresql")

#: Invariantes que só se observam com MVCC de verdade — ver o cabeçalho.
precisa_de_mvcc = pytest.mark.skipif(
    not TEM_MVCC,
    reason=(
        "O SQLite admite um escritor por vez e mascara o lê-depois-escreve. "
        "Esta invariante é provada no leg backend-postgres do CI "
        "(TEST_DATABASE_URL=postgresql://...)."
    ),
)


@pytest.fixture
def engine_concorrente():
    """Um banco que aceita CONEXÕES SIMULTÂNEAS.

    O `:memory:` com StaticPool do resto da suíte serializa tudo numa conexão só
    e esconderia a corrida. Postgres quando disponível (é o motor de produção e o
    único onde as corridas de MVCC aparecem); SQLite em arquivo como piso.
    """
    if TEM_MVCC:
        # Mesmo banco do resto da suíte (o `conftest` cria o schema uma vez por
        # processo e só apaga LINHAS entre testes). Nada de `drop_all` aqui: ele
        # levaria as tabelas embora no meio da rodada e todo teste seguinte
        # morreria — e o motivo ficaria escondido atrás de "relation does not
        # exist" num teste que não tem nada a ver com concorrência.
        engine = create_engine(_URL_TESTE)
        SQLModel.metadata.create_all(engine)

        def limpar():
            with engine.begin() as conn:
                for table in reversed(SQLModel.metadata.sorted_tables):
                    conn.execute(table.delete())

        # Limpa ANTES também: no SQLite cada teste ganhava um arquivo novo, e
        # perder isso deixaria estas asserções (que contam linhas no banco
        # inteiro) à mercê do que o teste anterior esqueceu.
        limpar()
        try:
            yield engine
        finally:
            limpar()
            engine.dispose()
        return

    fd, caminho = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{caminho}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        try:
            os.unlink(caminho)
        except OSError:
            pass


def _em_paralelo(
    engine,
    tarefa: Callable[[Session], object],
    n: int = THREADS,
    *,
    aquecer: Optional[Callable[[Session], object]] = None,
) -> List[object]:
    """Roda `tarefa` em N threads, cada uma com a própria sessão.

    `aquecer` roda ANTES de uma barreira que solta as N threads juntas. Sem ela a
    corrida depende de sorte de escalonamento: numa tarefa curta a primeira
    thread commita antes de as outras sequer lerem, e o teste fica verde contra
    código quebrado (foi o que aconteceu com o pagamento de fatura). Com ela, as
    N leem o mesmo estado e só então escrevem — que é a interleaving que o
    defeito exige.
    """
    barreira = threading.Barrier(n) if aquecer is not None else None

    def executar():
        with Session(engine) as session:
            try:
                if aquecer is not None:
                    aquecer(session)
                    barreira.wait(timeout=30)
                resultado = tarefa(session)
                session.commit()
                return resultado
            except Exception as exc:  # a corrida perdida pode legitimamente falhar
                session.rollback()
                return exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(executar) for _ in range(n)]]


@pytest.fixture
def base(engine_concorrente):
    with Session(engine_concorrente) as session:
        user = User(name="G", email="conc@t.com", password_hash="h")
        ws = Workspace(name="WS")
        session.add_all([user, ws])
        session.commit()
        session.refresh(user)
        session.refresh(ws)
        return {"engine": engine_concorrente, "user_id": user.id, "ws_id": ws.id}


# --- A1: renda recorrente ---------------------------------------------------


def test_renda_recorrente_nao_duplica_sob_concorrencia(base):
    """8 requisições simultâneas de LEITURA materializando o mesmo salário.

    É o cenário real: o Início dispara summary + reports + transactions em
    paralelo, e todos chamam ensure_and_commit.
    """
    engine = base["engine"]
    with Session(engine) as session:
        session.add(RecurringIncome(
            title="Salário", base_amount=Decimal("5000.00"), day_of_month=5,
            user_id=base["user_id"],
        ))
        session.commit()

    # `user_id`, não `ws_id`: renda é da PESSOA (ADR 0021) e o recorte de
    # `generate_due_income` é o dono. O teste passava `ws_id` e só funcionava por
    # coincidência — num banco recém-criado o primeiro usuário e o primeiro
    # workspace têm ambos id 1. Num banco compartilhado (o leg Postgres) as
    # sequências divergem, nenhum template é encontrado e o teste "passava"
    # materializando ZERO salários, que é o oposto do que ele afirma provar.
    _em_paralelo(
        engine,
        lambda s: RecurringIncomeService.generate_due_income(
            s, base["user_id"], date(2026, 7, 15), allow_fetch=False
        ),
    )

    with Session(engine) as session:
        rendas = session.exec(select(Income)).all()
    assert len(rendas) == 1, f"salário materializado {len(rendas)}x — deveria ser 1"


# --- A2: membership ---------------------------------------------------------


def test_membership_nao_duplica_sob_concorrencia(base):
    engine = base["engine"]
    _em_paralelo(
        engine,
        lambda s: ensure_membership(s, base["ws_id"], base["user_id"], WorkspaceRole.member),
    )

    with Session(engine) as session:
        vinculos = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == base["ws_id"],
                WorkspaceMembership.user_id == base["user_id"],
            )
        ).all()
    assert len(vinculos) == 1, f"{len(vinculos)} memberships para o mesmo par"


def test_ensure_membership_devolve_um_unico_criador(base):
    """Exatamente UMA das threads pode reportar que criou — as outras devem
    receber False, não erro."""
    engine = base["engine"]
    resultados = _em_paralelo(
        engine,
        lambda s: ensure_membership(s, base["ws_id"], base["user_id"], WorkspaceRole.member),
    )
    assert not any(isinstance(r, Exception) for r in resultados), resultados
    assert sum(1 for r in resultados if r is True) == 1


# --- C12: categoria ---------------------------------------------------------


def test_categoria_nao_duplica_sob_concorrencia(base):
    engine = base["engine"]

    def criar(session: Session):
        session.add(Category(workspace_id=base["ws_id"], name="Mercado"))

    _em_paralelo(engine, criar)

    with Session(engine) as session:
        categorias = session.exec(
            select(Category).where(Category.name == "Mercado")
        ).all()
    assert len(categorias) == 1, f"{len(categorias)} categorias com o mesmo nome"


# --- C13: usos do convite por link ------------------------------------------


def test_convite_por_link_respeita_max_uses(base):
    """`invite.uses += 1` em Python deixava 8 threads lerem o mesmo valor."""
    engine = base["engine"]
    with Session(engine) as session:
        convite = WorkspaceInvite(
            workspace_id=base["ws_id"], email=None, role=WorkspaceRole.member,
            expires_at=datetime.now(UTC) + timedelta(days=7), max_uses=1,
        )
        session.add(convite)
        session.commit()
        session.refresh(convite)
        convite_id = convite.id

    from sqlalchemy import update

    def consumir(session: Session):
        return session.execute(
            update(WorkspaceInvite)
            .where(WorkspaceInvite.id == convite_id)
            .values(uses=WorkspaceInvite.uses + 1)
            .returning(WorkspaceInvite.uses)
        ).scalar_one()

    resultados = [r for r in _em_paralelo(engine, consumir) if not isinstance(r, Exception)]

    # O incremento atômico garante que cada thread veja um valor DISTINTO —
    # é isso que permite recusar quem passou do teto.
    assert len(set(resultados)) == len(resultados), (
        f"threads leram o mesmo contador: {sorted(resultados)}"
    )
    dentro_do_limite = [r for r in resultados if r <= 1]
    assert len(dentro_do_limite) == 1, "mais de uma thread ficou dentro do max_uses"


# --- Onda 8 / F1: sobrepagamento de fatura ----------------------------------


@pytest.fixture
def fatura_fechada(base):
    """Fatura FECHADA de R$ 1.000 num cartão do usuário, sem pagamento nenhum."""
    engine = base["engine"]
    with Session(engine) as session:
        card = CreditCard(
            name="Nubank", limit=Decimal("5000.00"), closing_day=10, due_day=20,
            currency="BRL", owner_user_id=base["user_id"],
        )
        session.add(card)
        session.commit()
        session.refresh(card)
        statement = CardStatement(
            card_id=card.id, month="2026-07",
            closing_date=datetime(2026, 7, 10), due_date=datetime(2026, 7, 20),
            status=StatementStatus.closed, total_amount=Decimal("1000.00"),
        )
        session.add(statement)
        session.commit()
        session.refresh(statement)
        return {**base, "card_id": card.id, "statement_id": statement.id}


@precisa_de_mvcc
def test_pagamento_de_fatura_nao_ultrapassa_o_saldo(fatura_fechada):
    """8 threads pagando R$ 700 numa fatura de R$ 1.000.

    O saldo cumulativo já recusava sobrepagamento — SEQUENCIALMENTE. Ler o saldo,
    validar e só então inserir deixava duas requisições simultâneas passarem as
    duas: R$ 1.400 pagos numa fatura de R$ 1.000, status `paid`, saldo exibido
    zero. Um pagamento a mais não é arredondamento: é dinheiro que saiu da conta
    e o app diz que não saiu.
    """
    engine = fatura_fechada["engine"]
    statement_id = fatura_fechada["statement_id"]
    user_id = fatura_fechada["user_id"]

    def ler_o_saldo(session: Session):
        """Todas leem R$ 1.000 de saldo ANTES de qualquer uma escrever."""
        statement = session.get(CardStatement, statement_id)
        CreditCardService.statement_balance(session, statement)

    def pagar(session: Session):
        statement = session.get(CardStatement, statement_id)
        return CreditCardService.pay_statement(
            session, statement,
            account=None, amount=Decimal("700.00"), paid_at=None,
            note=None, user_id=user_id,
        )

    _em_paralelo(engine, pagar, aquecer=ler_o_saldo)

    with Session(engine) as session:
        pagamentos = session.exec(
            select(StatementPayment).where(
                StatementPayment.statement_id == statement_id,
                StatementPayment.deleted_at.is_(None),
            )
        ).all()
        total_pago = sum((p.amount for p in pagamentos), Decimal("0.00"))
        statement = session.get(CardStatement, statement_id)

    assert total_pago <= Decimal("1000.00"), (
        f"fatura de R$ 1.000 recebeu R$ {total_pago} em {len(pagamentos)} pagamentos"
    )
    # R$ 700 + R$ 700 = R$ 1.400 > R$ 1.000, então só UM cabe.
    assert len(pagamentos) == 1, f"{len(pagamentos)} pagamentos gravados"
    # E o estado tem de ser coerente com isso: R$ 700 de R$ 1.000 não quita.
    assert statement.status == StatementStatus.closed
    assert statement.paid_at is None


# --- Onda 8 / F2: despesa duplicada por parcela de financiamento -------------


@pytest.fixture
def parcela_em_aberto(base):
    """Financiamento ATIVO do usuário com uma parcela não paga, e o usuário
    membro do workspace onde a despesa será lançada."""
    engine = base["engine"]
    with Session(engine) as session:
        session.add(WorkspaceMembership(
            workspace_id=base["ws_id"], user_id=base["user_id"],
            role=WorkspaceRole.owner,
        ))
        financing = Financing(
            title="Apartamento", total_amount=Decimal("120000.00"),
            interest_rate=Decimal("0.010000"), start_date=date(2026, 1, 10),
            installments_count=60, method=AmortizationMethod.SAC,
            status=FinancingStatus.active, currency="BRL",
            owner_user_id=base["user_id"],
        )
        session.add(financing)
        session.commit()
        session.refresh(financing)
        parcela = AmortizationInstallment(
            financing_id=financing.id, installment_number=1,
            due_date=date(2026, 7, 10), principal_amount=Decimal("2000.00"),
            interest_amount=Decimal("1200.00"), total_amount=Decimal("3200.00"),
            remaining_balance=Decimal("118000.00"), is_paid=False,
        )
        session.add(parcela)
        session.commit()
        session.refresh(parcela)
        return {**base, "financing_id": financing.id, "installment_id": parcela.id}


@precisa_de_mvcc
def test_parcela_de_financiamento_gera_uma_unica_despesa(parcela_em_aberto):
    """8 threads pagando a MESMA parcela.

    A rota checava `installment.is_paid` em Python e só depois inseria a despesa
    vinculada: as 8 liam `False`, as 8 passavam, e a mesma parcela virava N
    lançamentos — dobrando caixa, relatórios e gasto do workspace. Chama a ROTA
    de verdade (e não uma reprodução da lógica) porque é a ordem das escritas
    dela que está sob teste.
    """
    from app.api.routes.me_financing import InstallmentPayRequest, pay_installment

    engine = parcela_em_aberto["engine"]
    financing_id = parcela_em_aberto["financing_id"]
    installment_id = parcela_em_aberto["installment_id"]

    def pagar(session: Session):
        usuario = session.get(User, parcela_em_aberto["user_id"])
        return pay_installment(
            financing_id=financing_id,
            installment_number=1,
            body=InstallmentPayRequest(workspace_id=parcela_em_aberto["ws_id"]),
            session=session,
            current_user=usuario,
        )

    _em_paralelo(engine, pagar)

    with Session(engine) as session:
        despesas = session.exec(
            select(Transaction).where(
                Transaction.financing_installment_id == installment_id,
                Transaction.deleted_at.is_(None),
                Transaction.status.in_([
                    TransactionStatus.confirmed, TransactionStatus.paid,
                ]),
            )
        ).all()
        parcela = session.get(AmortizationInstallment, installment_id)

    assert len(despesas) == 1, (
        f"{len(despesas)} despesas vivas para a mesma parcela — o caixa e os "
        "relatórios do mês contam o pagamento {len(despesas)}x"
    )
    assert parcela.is_paid is True
    assert parcela.paid_at is not None


# --- ADR 0026: convite de CADASTRO -------------------------------------------


@precisa_de_mvcc
def test_convite_de_cadastro_respeita_max_uses(base):
    """O portão do site inteiro: `max_uses=1` tem de significar UMA conta.

    O `WorkspaceInvite` já tinha o incremento atômico (ver
    `test_convite_por_link_respeita_max_uses`); o `RegistrationInvite`, que
    nasceu na onda do ADR 0026, voltou ao `uses += 1` em Python. Com o cadastro
    `invite_only` — o padrão — é ESTE contador que decide quantas contas um link
    vazado cria.
    """
    engine = base["engine"]
    with Session(engine) as session:
        convite = RegistrationInvite(
            email=None,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            max_uses=1,
        )
        session.add(convite)
        session.commit()
        session.refresh(convite)
        token = convite.token
        convite_id = convite.id

    contador = itertools.count()

    def cadastrar(session: Session):
        # O caminho de produção: portão, depois consumo, no mesmo commit.
        email = f"corrida{next(contador)}@t.com"
        convite, _ = assert_pode_cadastrar(session, email, token)
        if convite is None:
            raise AssertionError("o portão deixou passar sem convite")
        user = User(name="X", email=email, password_hash="h")
        session.add(user)
        session.flush()
        consome_convite(session, convite, user)
        return user.id

    def aquecer(session: Session):
        session.exec(select(RegistrationInvite).where(RegistrationInvite.id == convite_id)).first()

    resultados = _em_paralelo(engine, cadastrar, aquecer=aquecer)
    criados = [r for r in resultados if not isinstance(r, Exception)]

    with Session(engine) as session:
        convite = session.get(RegistrationInvite, convite_id)
        # O que interessa é a conta que SOBREVIVEU ao commit, não o retorno da
        # thread: quem perde a corrida levanta depois de já ter dado `flush` no
        # usuário, e é o rollback que precisa levá-lo embora.
        nascidos = session.exec(
            select(User).where(User.email.like("corrida%@t.com"))
        ).all()

    assert len(criados) == 1, (
        f"{len(criados)} cadastros passaram com um convite de max_uses=1 — "
        f"o cadastro por convite não limita nada sob concorrência"
    )
    assert len(nascidos) == 1, f"{len(nascidos)} contas ficaram no banco"
    assert convite.uses == 1, f"contador ficou em {convite.uses}"


@precisa_de_mvcc
def test_aceite_de_convite_por_link_nao_ultrapassa_max_uses(base):
    """A ROTA, não o padrão de UPDATE.

    `test_convite_por_link_respeita_max_uses` prova que o incremento atômico
    devolve valores distintos — mas quem recebe o valor acima do teto não é
    recusado por ninguém: `accept_invite` só marca o convite como aceito. O
    contador fica certo e a pessoa entra do mesmo jeito.
    """
    engine = base["engine"]
    with Session(engine) as session:
        convite = WorkspaceInvite(
            workspace_id=base["ws_id"], email=None, role=WorkspaceRole.member,
            expires_at=datetime.now(UTC) + timedelta(days=7), max_uses=1,
        )
        session.add(convite)
        # Um usuário por thread: o mesmo usuário seria barrado por
        # `ensure_membership`, e a corrida ficaria escondida atrás disso.
        for i in range(THREADS):
            session.add(User(name=f"U{i}", email=f"link{i}@t.com", password_hash="h"))
        session.commit()
        session.refresh(convite)
        token = convite.token

    fila = itertools.count()

    def aceitar(session: Session):
        usuario = session.exec(
            select(User).where(User.email == f"link{next(fila)}@t.com")
        ).one()
        return accept_invite(token=token, session=session, current_user=usuario)

    def aquecer(session: Session):
        session.exec(select(WorkspaceInvite).where(WorkspaceInvite.token == token)).first()

    resultados = _em_paralelo(engine, aceitar, aquecer=aquecer)
    aceitos = [r for r in resultados if not isinstance(r, Exception)]

    with Session(engine) as session:
        membros = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == base["ws_id"]
            )
        ).all()

    assert len(aceitos) == 1, f"{len(aceitos)} aceites em um link de uso único"
    assert len(membros) == 1, (
        f"{len(membros)} pessoas entraram no workspace por um link com max_uses=1"
    )


@precisa_de_mvcc
def test_ultimo_superadmin_nao_pode_sumir(base):
    """A trava do "último superadministrador" é um SELECT antes de um UPDATE.

    Dois superadmins sendo rebaixados ao mesmo tempo: cada requisição conta os
    OUTROS, cada uma vê um restante e as duas passam. O site fica sem ninguém que
    possa promover alguém — a configuração vira imutável e o convite fica sem
    quem o emita, que é exatamente o estado que `_assert_pode_mexer_em` existe
    para impedir.
    """
    engine = base["engine"]
    with Session(engine) as session:
        ator = session.get(User, base["user_id"])
        ator.platform_role = PlatformRole.superadmin
        session.add(ator)
        outro = User(
            name="S2", email="super2@t.com", password_hash="h",
            platform_role=PlatformRole.superadmin,
        )
        session.add(outro)
        session.commit()
        session.refresh(outro)
        alvos = [base["user_id"], outro.id]

    fila = itertools.count()

    def rebaixar(session: Session):
        alvo_id = alvos[next(fila) % 2]
        ator = session.exec(
            select(User).where(User.id == [i for i in alvos if i != alvo_id][0])
        ).one()
        return patch_user(
            user_id=alvo_id,
            dados=UserPatch(platform_role=PlatformRole.user),
            request=_request_falso(),
            db=session,
            ator=ator,
        )

    def aquecer(session: Session):
        session.exec(select(User).where(User.platform_role == PlatformRole.superadmin)).all()

    _em_paralelo(engine, rebaixar, n=2, aquecer=aquecer)

    with Session(engine) as session:
        sobraram = session.exec(
            select(User).where(
                User.platform_role == PlatformRole.superadmin,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        ).all()

    assert len(sobraram) >= 1, (
        "o site ficou SEM superadministrador: ninguém pode mais promover, "
        "configurar ou emitir convite — a saída é SQL dentro do container"
    )


# --- ADR 0009: acertos sem sobrepagamento ------------------------------------


@pytest.fixture
def divida_entre_dois(base):
    """B deve R$ 500 a A: despesa de R$ 1.000 paga por A, dividida meio a meio."""
    engine = base["engine"]
    with Session(engine) as session:
        b = User(name="B", email="devedor@t.com", password_hash="h")
        session.add(b)
        session.commit()
        session.refresh(b)
        for uid in (base["user_id"], b.id):
            session.add(WorkspaceMembership(
                workspace_id=base["ws_id"], user_id=uid, role=WorkspaceRole.admin,
            ))
        tx = Transaction(
            workspace_id=base["ws_id"], title="Aluguel",
            total_amount=Decimal("1000.00"), currency="BRL",
            transaction_date=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
            status=TransactionStatus.paid, created_by_user_id=base["user_id"],
        )
        session.add(tx)
        session.commit()
        session.refresh(tx)
        session.add(TransactionPayer(
            transaction_id=tx.id, user_id=base["user_id"], amount=Decimal("1000.00")
        ))
        for uid in (base["user_id"], b.id):
            session.add(TransactionSplit(
                transaction_id=tx.id, user_id=uid,
                input_value=Decimal("500.00"), computed_amount=Decimal("500.00"),
            ))
        session.commit()
        return {**base, "credor_id": base["user_id"], "devedor_id": b.id}


@precisa_de_mvcc
def test_acerto_nao_ultrapassa_a_divida(divida_entre_dois):
    """ADR 0009: o acerto segue a dívida líquida e NÃO pode excedê-la.

    O teto é calculado por `DebtService` (soma de pagos − devidos − acertos) e
    conferido com um `if` antes do `INSERT`. Duas quitações simultâneas da dívida
    inteira leem o mesmo saldo, passam as duas, e o devedor termina com crédito
    artificial — que é exatamente a inversão de relação que o ADR proíbe.
    """
    engine = divida_entre_dois["engine"]
    ws_id, credor, devedor = (
        divida_entre_dois["ws_id"],
        divida_entre_dois["credor_id"],
        divida_entre_dois["devedor_id"],
    )

    def quitar(session: Session):
        membership = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws_id,
                WorkspaceMembership.user_id == devedor,
            )
        ).one()
        return create_settlement(
            workspace_id=ws_id,
            settlement_in=SettlementCreate(
                from_user_id=devedor, to_user_id=credor, amount=Decimal("500.00")
            ),
            session=session,
            membership=membership,
        )

    def aquecer(session: Session):
        DebtService.get_workspace_debts(session, ws_id)

    resultados = _em_paralelo(engine, quitar, aquecer=aquecer)
    aceitos = [r for r in resultados if not isinstance(r, Exception)]

    with Session(engine) as session:
        total = session.exec(
            select(func.sum(Settlement.amount)).where(
                Settlement.workspace_id == ws_id, Settlement.deleted_at.is_(None)
            )
        ).one() or Decimal("0")

    assert total <= Decimal("500.00"), (
        f"acertos somam {total} para uma dívida de 500 — o devedor ficou com "
        f"{total - Decimal('500.00')} de crédito artificial ({len(aceitos)} aceites)"
    )


# --- ADR 0008: idempotência da importação ------------------------------------


@precisa_de_mvcc
def test_importacao_nao_duplica_o_mesmo_lote(base):
    """ADR 0008: reimportar o mesmo arquivo NÃO duplica.

    A idempotência é um `set` de fingerprints lido antes do laço que insere. Dois
    envios simultâneos do mesmo CSV — um duplo clique no botão de confirmar é o
    caso realista — leem o mesmo conjunto vazio e inserem as duas vezes. O
    fingerprint tem índice, mas NÃO é único, então nada no banco recusa.
    """
    engine = base["engine"]
    ws_id = base["ws_id"]
    with Session(engine) as session:
        session.add(WorkspaceMembership(
            workspace_id=ws_id, user_id=base["user_id"], role=WorkspaceRole.admin,
        ))
        session.commit()

    corpo = CommitRequest(
        filename="extrato.csv",
        rows=[
            CommitRow(
                line=1, title="Mercado",
                total_amount=Decimal("250.00"),
                transaction_date=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
            )
        ],
    )

    def importar(session: Session):
        membership = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws_id,
                WorkspaceMembership.user_id == base["user_id"],
            )
        ).one()
        return commit_import(
            workspace_id=ws_id, body=corpo, session=session, membership=membership
        )

    def aquecer(session: Session):
        session.exec(select(Transaction).where(Transaction.workspace_id == ws_id)).all()

    _em_paralelo(engine, importar, aquecer=aquecer)

    with Session(engine) as session:
        lancamentos = session.exec(
            select(Transaction).where(
                Transaction.workspace_id == ws_id, Transaction.deleted_at.is_(None)
            )
        ).all()

    assert len(lancamentos) == 1, (
        f"{len(lancamentos)} lançamentos para a mesma linha de extrato — "
        f"a idempotência do ADR 0008 não sobrevive a dois envios simultâneos"
    )


# --- ADR 0007: cota de anexos ------------------------------------------------


@precisa_de_mvcc
def test_cota_de_anexos_nao_e_ultrapassada(base):
    """A cota é uma SOMA lida antes do INSERT.

    Oito envios simultâneos leem o mesmo total usado, todos passam, e o volume
    recebe mais do que o teto permite — que é justamente o que a cota existe para
    impedir ("sem quota, qualquer membro enche o volume").
    """
    engine = base["engine"]
    ws_id = base["ws_id"]
    teto = 1_000_000
    with Session(engine) as session:
        session.add(AppSetting(
            key="attachment_quota_bytes", value=json.dumps(teto),
        ))
        tx = Transaction(
            workspace_id=ws_id, title="Com recibo",
            total_amount=Decimal("10.00"), currency="BRL",
            transaction_date=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
            status=TransactionStatus.confirmed, created_by_user_id=base["user_id"],
        )
        session.add(tx)
        session.commit()
        session.refresh(tx)
        tx_id = tx.id
        # Já quase cheia: sobra espaço para UM anexo de 200 KB.
        session.add(Attachment(
            workspace_id=ws_id, transaction_id=tx_id, filename="antigo.pdf",
            content_type="application/pdf", size_bytes=teto - 200_000,
            sha256="x" * 64, storage_key="k/antigo",
        ))
        session.commit()

    def enviar(session: Session):
        # Espelha a ordem de `upload_attachment` — trava, confere a soma, grava.
        # Chamar a rota de verdade exigiria um `UploadFile` e o volume de anexos
        # montado; o que esta invariante precisa provar é a SEQUÊNCIA, e é ela
        # que está reproduzida aqui. Sem a primeira linha (como era antes da
        # correção) o teste falha, que é o controle de que ele mede algo.
        trava_workspace(session, ws_id)
        _ensure_quota(session, ws_id, 200_000)
        session.add(Attachment(
            workspace_id=ws_id, transaction_id=tx_id, filename="novo.pdf",
            content_type="application/pdf", size_bytes=200_000,
            sha256="y" * 64, storage_key="k/novo",
        ))
        session.flush()

    def aquecer(session: Session):
        _ensure_quota(session, ws_id, 0)

    _em_paralelo(engine, enviar, aquecer=aquecer)

    with Session(engine) as session:
        usado = session.exec(
            select(func.coalesce(func.sum(Attachment.size_bytes), 0)).where(
                Attachment.workspace_id == ws_id
            )
        ).one()

    assert usado <= teto, (
        f"volume com {usado} bytes para uma cota de {teto} — "
        f"{usado - teto} bytes além do teto"
    )


@precisa_de_mvcc
def test_cota_mensal_de_convites_e_respeitada(base):
    """A cota de convites por pessoa (ADR 0026) é um COUNT antes de um INSERT.

    Menos grave que os outros tetos — a rodada seguinte já enxerga o excesso e
    barra, então sem trava a cota degradava para "teto + rajada" em vez de cair
    de vez. Mesmo mecanismo, mesma correção.
    """
    engine = base["engine"]
    teto = 3
    with Session(engine) as session:
        session.add(AppSetting(
            key="user_invite_quota_per_month", value=json.dumps(teto),
        ))
        session.commit()

    def convidar(session: Session):
        autor = session.get(User, base["user_id"])
        assert_pode_convidar(session, autor)
        return cria_convite(session, autor)

    def aquecer(session: Session):
        session.exec(select(RegistrationInvite)).all()

    _em_paralelo(engine, convidar, aquecer=aquecer)

    with Session(engine) as session:
        emitidos = session.exec(select(RegistrationInvite)).all()

    assert len(emitidos) <= teto, (
        f"{len(emitidos)} convites emitidos para uma cota de {teto}"
    )
