"""Semeia uma base de DEMONSTRAÇÃO: várias pessoas, vários espaços, história real.

Existe para diagnosticar o produto com ele cheio. Um app de finanças só mostra
os problemas que tem quando há meses de história, gente devendo entre si,
parcelas atravessando o calendário, fatura fechada, recorrência já materializada
e moeda estrangeira no meio — e nada disso aparece numa conta recém-criada.

## Como ele escreve

Pela sessão do app e pelos SERVIÇOS dele (`persist_transaction_children`,
`CreditCardService`, `AccountBalanceService`, `RecurringService`), como fazem os
outros scripts desta pasta. Não é `INSERT` cru: os `listener`s de
`billing_month`, o cálculo de divisão, o roteamento para a fatura e o gate de
moeda da conta são os mesmos das rotas. Dado semeado por fora deles fica
plausível e errado — que é o pior tipo de base de teste.

Não usa HTTP nem sessão de ninguém: rodando dentro do container, o dono do banco
é quem executa. As contas fictícias nascem com senha conhecida (`senha123`) para
dar para entrar como elas e ver o outro lado das dívidas.

## Rodar de novo

Pessoas, espaços, contas e cartões são reaproveitados pelo NOME (ou e-mail) —
a primeira versão não fazia isso e a segunda execução criou uma "Casa" paralela
com outros seis meses de história ao lado da primeira. Lançamentos, rendas e
acertos, esses, são acrescentados: rodar duas vezes engorda o histórico em vez
de duplicar a estrutura.

Ele NUNCA apaga nada.

Uso:

    docker exec controle_financeiro_v4-backend-1 python scripts/semear_demo.py
    docker exec ... python scripts/semear_demo.py --dono gabriel-barros15@live.com
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.core.security import get_password_hash  # noqa: E402
from app.db.engine import engine  # noqa: E402
from app.domain.settlement import resolve_settled_at  # noqa: E402
from app.models.category import Category  # noqa: E402
from app.models.credit_card import CreditCard  # noqa: E402
from app.models.financing import Financing  # noqa: E402
from app.models.income import Income  # noqa: E402
from app.models.payment_account import PaymentAccount, PaymentAccountType  # noqa: E402
from app.models.recurring import RecurringExpense, RecurringIncome  # noqa: E402
from app.models.settlement import Settlement  # noqa: E402
from app.models.tag import Tag, TransactionTagLink  # noqa: E402
from app.models.transaction import (  # noqa: E402
    PaymentMethod,
    SplitMethod,
    SplitMode,
    Transaction,
    TransactionStatus,
)
from app.schemas.transaction import (  # noqa: E402
    TransactionPayerBase,
    TransactionSplitBase,
)
from app.models.user import User  # noqa: E402
from app.models.workspace import (  # noqa: E402
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.services.account_balance_service import AccountBalanceService  # noqa: E402
from app.services.credit_card_service import CreditCardService  # noqa: E402
from app.services.financing_service import FinancingService  # noqa: E402
from app.services.transaction_service import persist_transaction_children  # noqa: E402

# Semente fixa: rodar de novo em outra máquina dá a mesma história, e um número
# que muda a cada execução é impossível de conferir a olho.
random.seed(20260906)

HOJE = date.today()


def meses_atras(n: int, dia: int = 10) -> datetime:
    """Um instante ao MEIO-DIA, n meses atrás.

    Meio-dia e não meia-noite: `transaction_date` é um instante ancorado, e a
    meia-noite crua vira o dia anterior em qualquer fuso a oeste de Greenwich —
    é a armadilha que o projeto já registrou em `civil_instant`.
    """
    ano, mes = HOJE.year, HOJE.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return datetime(ano, mes, min(dia, 28), 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Pessoas
# --------------------------------------------------------------------------- #

ELENCO = [
    ("Marina Duarte", "marina@demo.cf4.app"),
    ("Rafael Lopes", "rafael@demo.cf4.app"),
    ("Camila Nunes", "camila@demo.cf4.app"),
    ("Bruno Aguiar", "bruno@demo.cf4.app"),
    ("Tiago Ferraz", "tiago@demo.cf4.app"),
    ("Helena Prado", "helena@demo.cf4.app"),
]


def pessoa(db: Session, nome: str, email: str) -> User:
    """Reaproveita quem já existe (pelo e-mail) em vez de duplicar."""
    achado = db.exec(select(User).where(User.email == email)).first()
    if achado:
        return achado
    u = User(
        name=nome,
        email=email,
        password_hash=get_password_hash("senha123"),
        needs_onboarding=False,
        report_currency="BRL",
    )
    db.add(u)
    db.flush()
    return u


def espaco(db: Session, nome: str, membros, moeda: str = "BRL") -> Workspace:
    """`membros`: lista de (user, papel, acesso).

    Reaproveita o espaço de mesmo nome, como `pessoa()` faz com o e-mail. Sem
    isso, rodar o script duas vezes cria uma segunda "Casa" com outros seis
    meses de história ao lado da primeira — foi o que aconteceu na primeira
    tentativa, e uma base com espaços duplicados é pior para diagnosticar do
    que uma vazia.
    """
    ws = db.exec(
        select(Workspace)
        .where(Workspace.name == nome)
        .where(Workspace.deleted_at.is_(None))
    ).first()
    if ws is not None:
        return ws
    ws = Workspace(name=nome, base_currency=moeda, settlement_tracking=True)
    db.add(ws)
    db.flush()
    for u, papel, acesso in membros:
        db.add(WorkspaceMembership(
            workspace_id=ws.id, user_id=u.id, role=papel, financial_access=acesso,
        ))
    db.flush()
    return ws


def _por_nome(db: Session, modelo, ws: Workspace, nomes) -> dict:
    """Cria o que falta e reaproveita o que já existe.

    Categoria e etiqueta são únicas por (espaço, nome) — e como o espaço passou
    a ser reaproveitado, criar às cegas estoura na segunda execução.
    """
    saida = {}
    for n in nomes:
        achado = db.exec(
            select(modelo)
            .where(modelo.workspace_id == ws.id)
            .where(modelo.name == n)
        ).first()
        if achado is None:
            achado = modelo(workspace_id=ws.id, name=n)
            db.add(achado)
            db.flush()
        saida[n] = achado
    return saida


def categorias(db: Session, ws: Workspace, nomes) -> dict:
    return _por_nome(db, Category, ws, nomes)


def etiquetas(db: Session, ws: Workspace, nomes) -> dict:
    return _por_nome(db, Tag, ws, nomes)


# --------------------------------------------------------------------------- #
# Lançamentos
# --------------------------------------------------------------------------- #

def despesa(
    db: Session,
    ws: Workspace,
    *,
    titulo: str,
    valor: str,
    quando: datetime,
    pagador: User,
    entre: List[User],
    metodo: PaymentMethod = PaymentMethod.pix,
    categoria: Optional[Category] = None,
    cartao: Optional[CreditCard] = None,
    liquidada: Optional[bool] = None,
    etiqueta: Optional[Tag] = None,
    parcelas: int = 1,
    moeda: Optional[str] = None,
) -> Transaction:
    """Uma despesa completa, pelo mesmo caminho das rotas.

    `entre` é quem RATEIA (divisão igual). O pagador entra na conta como quem
    adiantou o dinheiro — os dois eixos que o app separa desde o ADR 0004.
    """
    total = Decimal(valor)
    criadas = []
    valor_parcela = (total / parcelas).quantize(Decimal("0.01"))
    grupo = None

    for i in range(parcelas):
        data_i = quando if i == 0 else _somar_meses(quando, i)
        # A última parcela absorve o centavo que a divisão perdeu.
        bruto = valor_parcela if i < parcelas - 1 else total - valor_parcela * (parcelas - 1)

        tx = Transaction(
            title=titulo,
            description=None,
            total_amount=bruto,
            currency=moeda or ws.base_currency,
            transaction_date=data_i,
            status=TransactionStatus.confirmed,
            workspace_id=ws.id,
            created_by_user_id=pagador.id,
            payment_method=metodo,
            credit_card_id=cartao.id if cartao else None,
            installment_no=(i + 1) if parcelas > 1 else None,
            installments_of=parcelas if parcelas > 1 else None,
            installment_group_id=grupo,
        )
        # Liquidação (ADR 0029) pelo mesmo resolvedor das rotas: compra no
        # cartão nunca nasce liquidada — quem paga é a fatura.
        tx.settled_at = resolve_settled_at(
            db, ws.id,
            transaction_date=data_i,
            credit_card_id=cartao.id if cartao else None,
            explicit=liquidada,
        )
        db.add(tx)
        db.flush()
        if grupo is None and parcelas > 1:
            grupo = tx.installment_group_id or tx.id
            tx.installment_group_id = grupo

        persist_transaction_children(
            db, ws.id, tx,
            total_amount=bruto,
            split_mode=SplitMode.transaction,
            payers=[TransactionPayerBase(user_id=pagador.id, amount=bruto)],
            splits=[
                TransactionSplitBase(
                    user_id=u.id, split_method=SplitMethod.equal, input_value=Decimal("0"),
                )
                for u in entre
            ],
            items=None,
            actor_user_id=pagador.id,
        )
        if categoria is not None:
            from app.models.transaction import TransactionItem
            db.add(TransactionItem(
                transaction_id=tx.id, title=titulo, amount=bruto, category_id=categoria.id,
            ))
        if etiqueta is not None:
            db.add(TransactionTagLink(transaction_id=tx.id, tag_id=etiqueta.id))
        if cartao is not None:
            CreditCardService.get_or_create_statement(db, cartao, data_i)
        criadas.append(tx)

    db.flush()
    return criadas[0]


def _somar_meses(quando: datetime, n: int) -> datetime:
    ano, mes = quando.year, quando.month + n
    while mes > 12:
        mes -= 12
        ano += 1
    return quando.replace(year=ano, month=mes)


# --------------------------------------------------------------------------- #
# O roteiro
# --------------------------------------------------------------------------- #

def semear(db: Session, email_dono: str) -> dict:
    dono = db.exec(select(User).where(User.email == email_dono)).first()
    if dono is None:
        raise SystemExit(
            f"não achei a conta {email_dono} neste banco — rode com --dono <e-mail>"
        )
    if dono.needs_onboarding:
        # Sem isto o app abre o onboarding por cima de tudo no primeiro acesso.
        dono.needs_onboarding = False
        db.add(dono)

    elenco = {email: pessoa(db, nome, email) for nome, email in ELENCO}
    marina = elenco["marina@demo.cf4.app"]
    rafael = elenco["rafael@demo.cf4.app"]
    camila = elenco["camila@demo.cf4.app"]
    bruno = elenco["bruno@demo.cf4.app"]
    tiago = elenco["tiago@demo.cf4.app"]
    helena = elenco["helena@demo.cf4.app"]

    completo = FinancialAccess.full_workspace
    restrito = FinancialAccess.involved_only

    # --- Os espaços -------------------------------------------------------
    #
    # Papéis e acessos DIFERENTES de propósito: é o eixo do ADR 0018, e ele só
    # se enxerga entrando como gente diferente. A Helena entra como `viewer`
    # restrita para dar um caso em que a tela esconde de verdade.
    casa = espaco(db, "Casa", [
        (dono, WorkspaceRole.owner, completo),
        (marina, WorkspaceRole.admin, completo),
        (rafael, WorkspaceRole.member, restrito),
    ])
    viagem = espaco(db, "Viagem — Chile 2026", [
        (dono, WorkspaceRole.owner, completo),
        (marina, WorkspaceRole.member, completo),
        (bruno, WorkspaceRole.member, restrito),
        (camila, WorkspaceRole.member, restrito),
    ])
    republica = espaco(db, "República", [
        (rafael, WorkspaceRole.owner, completo),
        (dono, WorkspaceRole.member, completo),
        (camila, WorkspaceRole.member, restrito),
        (tiago, WorkspaceRole.member, restrito),
        (helena, WorkspaceRole.viewer, restrito),
    ])
    # Um espaço em OUTRA moeda: exercita a conversão e a "Visão global" somando
    # espaços de moedas diferentes.
    freela = espaco(db, "Projeto em dólar", [
        (dono, WorkspaceRole.owner, completo),
        (tiago, WorkspaceRole.member, completo),
    ], moeda="USD")

    cat_casa = categorias(db, casa, [
        "Mercado", "Moradia", "Transporte", "Saúde", "Lazer", "Assinaturas",
    ])
    cat_viagem = categorias(db, viagem, ["Passagens", "Hospedagem", "Alimentação", "Passeios"])
    cat_rep = categorias(db, republica, ["Mercado", "Contas da casa", "Faxina"])
    tag_casa = etiquetas(db, casa, ["fixo", "imprevisto", "reembolsável"])

    return {
        "dono": dono, "elenco": elenco, "casa": casa, "viagem": viagem,
        "republica": republica, "freela": freela,
        "cat_casa": cat_casa, "cat_viagem": cat_viagem, "cat_rep": cat_rep,
        "tag_casa": tag_casa,
        "marina": marina, "rafael": rafael, "camila": camila,
        "bruno": bruno, "tiago": tiago, "helena": helena,
    }


def historia_dos_espacos(db: Session, c: dict) -> None:
    """Seis meses de movimento nos espaços compartilhados."""
    dono, casa, viagem, rep = c["dono"], c["casa"], c["viagem"], c["republica"]
    marina, rafael, camila, bruno, tiago = (
        c["marina"], c["rafael"], c["camila"], c["bruno"], c["tiago"]
    )
    cc, cv, cr, tags = c["cat_casa"], c["cat_viagem"], c["cat_rep"], c["tag_casa"]
    trio_casa = [dono, marina, rafael]

    # --- CASA: o mercado de todo mês, com quem paga alternando ------------
    #
    # Alternar o pagador é o que produz dívida NOS DOIS SENTIDOS — com um
    # pagador fixo, o saldo só cresce para um lado e metade das telas de acerto
    # nunca mostra o caso interessante.
    for m in range(6, 0, -1):
        quem = [dono, marina, rafael][m % 3]
        despesa(db, casa, titulo="Mercado do mês", valor=str(680 + m * 37),
                quando=meses_atras(m, 8), pagador=quem, entre=trio_casa,
                categoria=cc["Mercado"], etiqueta=tags["fixo"])
        despesa(db, casa, titulo="Conta de luz", valor=str(180 + m * 9),
                quando=meses_atras(m, 15), pagador=dono, entre=trio_casa,
                metodo=PaymentMethod.debit_card, categoria=cc["Moradia"])
        despesa(db, casa, titulo="Internet", valor="129.90",
                quando=meses_atras(m, 20), pagador=marina, entre=trio_casa,
                categoria=cc["Assinaturas"], etiqueta=tags["fixo"])

    # Um imprevisto grande, parcelado em 6 — atravessa o calendário e é o caso
    # que a tela de parcelas existe para mostrar.
    despesa(db, casa, titulo="Conserto do encanamento", valor="2400.00",
            quando=meses_atras(4, 5), pagador=dono, entre=trio_casa,
            metodo=PaymentMethod.credit_card, categoria=cc["Moradia"],
            etiqueta=tags["imprevisto"], parcelas=6)

    # Contas ainda EM ABERTO (a pagar), com vencimento à frente e atrás: é o que
    # alimenta "Precisa de você" e o aviso de atraso.
    despesa(db, casa, titulo="IPTU parcela 3/10", valor="312.40",
            quando=datetime.combine(HOJE + timedelta(days=4), datetime.min.time()).replace(hour=12, tzinfo=UTC),
            pagador=dono, entre=trio_casa, metodo=PaymentMethod.boleto,
            categoria=cc["Moradia"], liquidada=False)
    despesa(db, casa, titulo="Plano de saúde", valor="489.00",
            quando=datetime.combine(HOJE - timedelta(days=6), datetime.min.time()).replace(hour=12, tzinfo=UTC),
            pagador=dono, entre=trio_casa, metodo=PaymentMethod.boleto,
            categoria=cc["Saúde"], liquidada=False)

    # --- VIAGEM: gasto concentrado em dois meses, com estrangeira ---------
    quarteto = [dono, marina, bruno, camila]
    despesa(db, viagem, titulo="Passagens aéreas", valor="6320.00",
            quando=meses_atras(3, 12), pagador=dono, entre=quarteto,
            metodo=PaymentMethod.credit_card, categoria=cv["Passagens"], parcelas=4)
    despesa(db, viagem, titulo="Hotel em Santiago", valor="4180.00",
            quando=meses_atras(2, 6), pagador=marina, entre=quarteto,
            categoria=cv["Hospedagem"])
    for i, (titulo, valor) in enumerate([
        ("Jantar no centro", "412.30"), ("Vinícola", "980.00"),
        ("Aluguel do carro", "1250.00"), ("Mercado da viagem", "336.75"),
    ]):
        despesa(db, viagem, titulo=titulo, valor=valor,
                quando=meses_atras(2, 8 + i * 3), pagador=[dono, bruno, camila, marina][i],
                entre=quarteto, categoria=cv["Passeios" if i % 2 else "Alimentação"])

    # --- REPÚBLICA: cinco pessoas, uma delas viewer restrita --------------
    grupo_rep = [dono, rafael, camila, tiago]
    for m in range(5, 0, -1):
        despesa(db, rep, titulo="Feira da semana", valor=str(210 + m * 13),
                quando=meses_atras(m, 6), pagador=[rafael, camila, tiago, dono][m % 4],
                entre=grupo_rep, categoria=cr["Mercado"])
        despesa(db, rep, titulo="Faxina", valor="180.00",
                quando=meses_atras(m, 22), pagador=rafael, entre=grupo_rep,
                categoria=cr["Faxina"])

    # --- FREELA em dólar --------------------------------------------------
    despesa(db, c["freela"], titulo="Assinatura de ferramenta", valor="49.00",
            quando=meses_atras(1, 14), pagador=dono, entre=[dono, tiago],
            metodo=PaymentMethod.credit_card, moeda="USD")

    db.flush()


def vida_pessoal(db: Session, c: dict) -> None:
    """O eixo PESSOAL do dono (ADR 0021): contas, cartões, rendas, financiamento.

    Nada disso pertence a espaço nenhum, e é justamente o que a primeira tela
    ("Hoje") lê. Sem saldo de abertura ela abre dizendo "saldo ainda não
    configurado", que é a tela vazia que não deixa diagnosticar nada.
    """
    dono = c["dono"]

    # --- Contas, com abertura em datas diferentes ------------------------
    contas = {}
    for nome, tipo, saldo, meses in [
        ("Nubank", PaymentAccountType.checking, "8420.55", 8),
        ("Itaú", PaymentAccountType.checking, "3150.00", 8),
        ("Reserva (poupança)", PaymentAccountType.savings, "22800.00", 8),
        ("Carteira", PaymentAccountType.cash, "180.00", 8),
    ]:
        # Reaproveita o que já existe (`uq_paymentaccount_owner_name`): a conta
        # do dono é DELE, e um semeador que derruba o cadastro dele com um nome
        # repetido seria pior que um banco vazio. A abertura é reescrita — é
        # justamente o que `define_abertura` permite.
        conta = db.exec(
            select(PaymentAccount)
            .where(PaymentAccount.owner_user_id == dono.id)
            .where(PaymentAccount.name == nome)
        ).first()
        if conta is None:
            conta = PaymentAccount(
                name=nome, type=tipo, currency="BRL", owner_user_id=dono.id,
                is_default=(nome == "Nubank"),
            )
            db.add(conta)
            db.flush()
        AccountBalanceService.define_abertura(
            db, conta, amount=Decimal(saldo),
            as_of=meses_atras(meses, 1).date(), user_id=dono.id,
        )
        contas[nome] = conta

    # --- Cartões, com ciclos diferentes ----------------------------------
    #
    # Dias de fechamento distintos de propósito: é o que faz a mesma compra cair
    # em faturas diferentes e o que o aviso de "janela de fechamento" precisa
    # para aparecer.
    cartoes = {}
    for nome, limite, fecha, vence in [
        ("Nubank Roxinho", "12000.00", 3, 10),
        ("Inter Gold", "8000.00", 20, 28),
    ]:
        cartao = db.exec(
            select(CreditCard)
            .where(CreditCard.owner_user_id == dono.id)
            .where(CreditCard.name == nome)
        ).first()
        if cartao is None:
            cartao = CreditCard(
                name=nome, limit=Decimal(limite), closing_day=fecha, due_day=vence,
                currency="BRL", owner_user_id=dono.id,
            )
            db.add(cartao)
            db.flush()
        cartoes[nome] = cartao

    # Compras no cartão, espalhadas por três ciclos → faturas fechadas e a
    # corrente em aberto.
    for m, (titulo, valor, qual) in enumerate([
        ("Farmácia", "132.80", "Nubank Roxinho"),
        ("Streaming", "55.90", "Nubank Roxinho"),
        ("Livraria", "240.00", "Inter Gold"),
        ("Posto de gasolina", "310.00", "Nubank Roxinho"),
        ("Restaurante", "186.40", "Inter Gold"),
    ]):
        despesa(db, c["casa"], titulo=titulo, valor=valor,
                quando=meses_atras(2 - (m % 3), 5 + m * 2), pagador=dono,
                entre=[dono], metodo=PaymentMethod.credit_card,
                cartao=cartoes[qual])

    # --- Rendas: salário recorrente + freelas avulsos --------------------
    for m in range(6, 0, -1):
        recebido = meses_atras(m, 5)
        db.add(Income(
            title="Salário", amount=Decimal("9800.00"), currency="BRL",
            category="Salário", user_id=dono.id, received_at=recebido,
            settled_at=recebido, account_id=contas["Nubank"].id,
        ))
    for m, valor in [(4, "2200.00"), (2, "1750.00")]:
        recebido = meses_atras(m, 18)
        db.add(Income(
            title="Freela de projeto", amount=Decimal(valor), currency="BRL",
            category="Freelance", user_id=dono.id, received_at=recebido,
            settled_at=recebido, account_id=contas["Itaú"].id,
        ))
    # Uma renda AINDA NÃO recebida: alimenta o "a receber" da previsão.
    futuro = datetime.combine(HOJE + timedelta(days=9), datetime.min.time()).replace(hour=12, tzinfo=UTC)
    db.add(Income(
        title="Reembolso do convênio", amount=Decimal("430.00"), currency="BRL",
        category="Reembolso", user_id=dono.id, received_at=futuro, settled_at=None,
    ))

    db.add(RecurringIncome(
        title="Salário", base_amount=Decimal("9800.00"), currency="BRL",
        category="Salário", user_id=dono.id, day_of_month=5, is_active=True,
    ))

    # --- Financiamento: começou há 14 meses, então tem passado E futuro ---
    fin = Financing(
        title="Financiamento do carro", total_amount=Decimal("62000.00"),
        interest_rate=Decimal("0.0129"), installments_count=48,
        start_date=meses_atras(14, 1).date(), currency="BRL",
        method="PRICE", owner_user_id=dono.id,
    )
    db.add(fin)
    db.flush()
    parcelas = FinancingService.calculate_amortization_schedule(
        total_amount=fin.total_amount, interest_rate=fin.interest_rate,
        installments_count=fin.installments_count, start_date=fin.start_date,
        method=fin.method,
    )
    for i, parcela in enumerate(parcelas):
        parcela.financing_id = fin.id
        # As 13 primeiras já foram pagas: sem isso a projeção anuncia 14 meses
        # de atraso, que é justamente o defeito que a Onda 0 corrigiu.
        if parcela.due_date < HOJE - timedelta(days=25):
            parcela.is_paid = True
            parcela.paid_at = parcela.due_date
        db.add(parcela)

    db.flush()
    return contas, cartoes


def vida_das_demais(db: Session, c: dict) -> None:
    """Um eixo pessoal ENXUTO para as contas fictícias.

    Sem isto, entrar como a Marina para ver o outro lado de uma dívida abre numa
    tela que diz "saldo ainda não configurado" — e quem está diagnosticando
    perde a metade da experiência que só existe com dinheiro em conta. Não
    precisa ser o cadastro completo do dono: conta com saldo e salário bastam
    para a primeira tela responder as três perguntas dela.
    """
    for u, saldo, salario in [
        (c["marina"], "5200.00", "7400.00"),
        (c["rafael"], "1830.00", "4900.00"),
        (c["camila"], "9450.00", "8100.00"),
        (c["bruno"], "640.00", "3800.00"),
        (c["tiago"], "15200.00", "11000.00"),
    ]:
        ja_tem = db.exec(
            select(PaymentAccount).where(PaymentAccount.owner_user_id == u.id)
        ).first()
        if ja_tem is None:
            conta = PaymentAccount(
                name="Conta corrente", type=PaymentAccountType.checking,
                currency="BRL", owner_user_id=u.id, is_default=True,
            )
            db.add(conta)
            db.flush()
            AccountBalanceService.define_abertura(
                db, conta, amount=Decimal(saldo),
                as_of=meses_atras(6, 1).date(), user_id=u.id,
            )
        else:
            conta = ja_tem
        # Três meses de salário: o bastante para "renda × consumo" ter linha.
        for m in range(3, 0, -1):
            recebido = meses_atras(m, 5)
            db.add(Income(
                title="Salário", amount=Decimal(salario), currency="BRL",
                category="Salário", user_id=u.id, received_at=recebido,
                settled_at=recebido, account_id=conta.id,
            ))
    db.flush()


def recorrencias_e_acertos(db: Session, c: dict) -> None:
    """As despesas fixas (algumas DIVIDIDAS) e os acertos já feitos."""
    dono, casa, rep = c["dono"], c["casa"], c["republica"]
    marina, rafael, camila, tiago = c["marina"], c["rafael"], c["camila"], c["tiago"]
    cc, cr = c["cat_casa"], c["cat_rep"]

    def dividido(*pessoas):
        """O `split_snapshot` do template (ADR 0012): divisão igual entre eles."""
        return [
            {"user_id": p.id, "split_method": "equal", "input_value": "0"}
            for p in pessoas
        ]

    # CASA — o aluguel dividido em três é o caso que a divisão na recorrência
    # existe para resolver: ele se repete todo mês, com as mesmas pessoas.
    db.add(RecurringExpense(
        title="Aluguel", base_amount=Decimal("3200.00"), day_of_month=5,
        workspace_id=casa.id, created_by_user_id=dono.id, payer_user_id=dono.id,
        currency="BRL", payment_method=PaymentMethod.pix, category_id=cc["Moradia"].id,
        start_date=meses_atras(7, 5).date(), auto_settle=True, is_active=True,
        split_snapshot=dividido(dono, marina, rafael),
    ))
    db.add(RecurringExpense(
        title="Internet e streaming", base_amount=Decimal("189.80"), day_of_month=12,
        workspace_id=casa.id, created_by_user_id=marina.id, payer_user_id=marina.id,
        currency="BRL", payment_method=PaymentMethod.credit_card,
        category_id=cc["Assinaturas"].id, start_date=meses_atras(7, 12).date(),
        is_active=True, split_snapshot=dividido(dono, marina, rafael),
    ))
    # Uma SEM divisão (100% de quem cadastrou) e uma INATIVA: os dois estados
    # que a lista precisa mostrar diferente.
    db.add(RecurringExpense(
        title="Academia", base_amount=Decimal("129.00"), day_of_month=8,
        workspace_id=casa.id, created_by_user_id=dono.id, payer_user_id=dono.id,
        currency="BRL", payment_method=PaymentMethod.credit_card,
        start_date=meses_atras(7, 8).date(), is_active=True,
    ))
    db.add(RecurringExpense(
        title="Revista assinada (cancelada)", base_amount=Decimal("39.90"),
        day_of_month=20, workspace_id=casa.id, created_by_user_id=dono.id,
        payer_user_id=dono.id, currency="BRL", start_date=meses_atras(7, 20).date(),
        is_active=False,
    ))
    # Frequências diferentes: semanal e anual entram no "compromisso fixo por
    # mês" convertidos, e é a conta que o topo da tela mostra.
    db.add(RecurringExpense(
        title="Faxina semanal", base_amount=Decimal("180.00"), day_of_month=1,
        day_of_week=2, frequency="weekly", workspace_id=rep.id,
        created_by_user_id=rafael.id, payer_user_id=rafael.id, currency="BRL",
        start_date=meses_atras(5, 1).date(), is_active=True,
        category_id=cr["Faxina"].id, split_snapshot=dividido(dono, rafael, camila, tiago),
    ))
    db.add(RecurringExpense(
        title="Seguro anual do apartamento", base_amount=Decimal("1450.00"),
        day_of_month=15, month_of_year=3, frequency="yearly",
        workspace_id=casa.id, created_by_user_id=dono.id, payer_user_id=dono.id,
        currency="BRL", start_date=meses_atras(7, 15).date(), is_active=True,
    ))
    db.flush()

    # --- Acertos JÁ FEITOS ------------------------------------------------
    #
    # Dos dois tipos, de propósito: um carimbado com o mês que ele fecha, outro
    # a partir do saldo acumulado (que quita do mais antigo para o mais novo).
    # É a distinção que a tela de Acertos mostra e que o histórico etiqueta.
    mes_antigo = meses_atras(5, 1).strftime("%Y-%m")
    db.add(Settlement(
        workspace_id=casa.id, from_user_id=rafael.id, to_user_id=dono.id,
        amount=Decimal("240.00"), billing_month=mes_antigo, note="Pix",
        settled_at=meses_atras(5, 25), created_by_user_id=dono.id,
    ))
    db.add(Settlement(
        workspace_id=casa.id, from_user_id=marina.id, to_user_id=dono.id,
        amount=Decimal("180.00"), note="acerto do acumulado",
        settled_at=meses_atras(3, 14), created_by_user_id=dono.id,
    ))
    db.add(Settlement(
        workspace_id=rep.id, from_user_id=dono.id, to_user_id=rafael.id,
        amount=Decimal("95.00"), billing_month=meses_atras(2, 1).strftime("%Y-%m"),
        note="dinheiro", settled_at=meses_atras(2, 27), created_by_user_id=dono.id,
    ))
    db.flush()


def o_que_falta(db: Session, c: dict, contas, cartoes) -> None:
    """As telas que ficariam vazias mesmo com meses de história.

    Fatura PAGA, transferência entre contas, orçamento por categoria e um
    convite pendente. Cada um alimenta uma tela inteira que, sem eles, abre no
    estado vazio — e estado vazio não diagnostica nada.
    """
    from app.models.account_ledger import AccountTransfer
    from app.models.credit_card import CardStatement, StatementStatus
    from app.models.estimate import MonthlyEstimate

    dono, casa = c["dono"], c["casa"]

    # --- Uma fatura antiga PAGA (o caixa do mês em que ela saiu) ----------
    antigas = db.exec(
        select(CardStatement)
        .where(CardStatement.card_id.in_([x.id for x in cartoes.values()]))
        .order_by(CardStatement.month)
    ).all()
    for st in antigas[:2]:
        if st.status == StatementStatus.paid:
            continue
        total = CreditCardService.compute_statement_total(db, st.id)
        if total <= 0:
            continue
        st.status = StatementStatus.closed
        db.add(st)
        db.flush()
        CreditCardService.pay_statement(
            db, st, account=contas["Nubank"], amount=total,
            paid_at=meses_atras(2, 12), note="pagamento total", user_id=dono.id,
        )

    # --- Transferência entre contas próprias -----------------------------
    db.add(AccountTransfer(
        from_account_id=contas["Nubank"].id,
        to_account_id=contas["Reserva (poupança)"].id,
        from_amount=Decimal("1500.00"), to_amount=Decimal("1500.00"),
        occurred_at=meses_atras(1, 6), note="guardando o do mês",
        created_by_user_id=dono.id,
    ))

    # --- Orçamento por categoria (a aba Orçamento dos Relatórios) --------
    mes = HOJE.strftime("%Y-%m")
    for nome, teto in [("Mercado", "900.00"), ("Lazer", "400.00"), ("Transporte", "350.00")]:
        cat = c["cat_casa"][nome]
        if db.exec(
            select(MonthlyEstimate)
            .where(MonthlyEstimate.workspace_id == casa.id)
            .where(MonthlyEstimate.owner_user_id == dono.id)
            .where(MonthlyEstimate.category_id == cat.id)
            .where(MonthlyEstimate.month == mes)
        ).first():
            continue
        db.add(MonthlyEstimate(
            # `user_id` é quem CRIOU; `owner_user_id` é de quem é a meta. As duas
            # colunas convivem porque a meta da casa e a pessoal de cada membro
            # existem na mesma categoria e no mesmo mês.
            workspace_id=casa.id, user_id=dono.id, owner_user_id=dono.id,
            category=nome, category_id=cat.id,
            amount=Decimal(teto), month=mes,
        ))

    # --- Um convite PENDENTE (a tela de convites e o sino) ---------------
    from app.models.workspace import WorkspaceInvite
    ja_convidado = db.exec(
        select(WorkspaceInvite).where(WorkspaceInvite.token == "demo-convite-pendente-0001")
    ).first()
    if ja_convidado is None:
            db.add(WorkspaceInvite(
            workspace_id=casa.id, email="visitante@demo.cf4.app",
            role=WorkspaceRole.member, invited_by_user_id=dono.id,
            token="demo-convite-pendente-0001",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        ))

    db.flush()


def resumo(db: Session, c: dict) -> None:
    """O que ficou no banco, para conferir a olho antes de abrir o app."""
    from sqlalchemy import func as f

    def conta(modelo, *onde):
        stmt = select(f.count()).select_from(modelo)
        for w in onde:
            stmt = stmt.where(w)
        return db.exec(stmt).one()

    print()
    print("  pessoas .............", conta(User))
    print("  espaços .............", conta(Workspace))
    print("  lançamentos .........", conta(Transaction))
    print("  rendas ..............", conta(Income))
    print("  recorrências ........", conta(RecurringExpense))
    print("  acertos .............", conta(Settlement))
    print("  contas de pagamento .", conta(PaymentAccount))
    print("  cartões .............", conta(CreditCard))
    print("  financiamentos ......", conta(Financing))


ESPACOS_DEMO = ("Casa", "Viagem — Chile 2026", "República", "Projeto em dólar")


def limpar(db: Session, email_dono: str) -> None:
    """Apaga TUDO o que este script cria, para semear de novo do zero.

    Existe porque a estrutura é reaproveitada mas o conteúdo não: rodar duas
    vezes deixa três financiamentos e dezenove recorrências onde deviam existir
    um e seis — uma base mais confusa de diagnosticar do que uma vazia.

    O recorte é o que o semeador conhece: os espaços com os nomes dele, as
    pessoas `@demo.cf4.app` e as linhas pessoais do dono criadas aqui. O que
    existia antes NÃO é tocado — exceto o saldo de abertura de uma conta
    homônima, que `define_abertura` reescreve por natureza.
    """
    from sqlalchemy import text

    ids = [
        w.id for w in db.exec(
            select(Workspace).where(Workspace.name.in_(ESPACOS_DEMO))
        ).all()
    ]
    demo_users = [
        u.id for u in db.exec(
            select(User).where(User.email.like("%@demo.cf4.app"))
        ).all()
    ]
    dono = db.exec(select(User).where(User.email == email_dono)).first()
    if dono is None:
        raise SystemExit(f"não achei {email_dono}")

    if ids:
        lista = ",".join(str(i) for i in ids)
        txs = f"(SELECT id FROM transaction WHERE workspace_id IN ({lista}))"
        # Filhos primeiro: as FKs não têm cascade, e o Postgres recusa a ordem
        # errada — que é o comportamento certo e o que torna esta lista explícita.
        for sql in (
            f"DELETE FROM transactionitemshare WHERE item_id IN (SELECT id FROM transactionitem WHERE transaction_id IN {txs})",
            f"DELETE FROM transactionitem WHERE transaction_id IN {txs}",
            f"DELETE FROM transactionpayer WHERE transaction_id IN {txs}",
            f"DELETE FROM transactionsplit WHERE transaction_id IN {txs}",
            f"DELETE FROM transactiontaglink WHERE transaction_id IN {txs}",
            f"DELETE FROM transactionadjustment WHERE transaction_id IN {txs}",
            f"DELETE FROM attachment WHERE transaction_id IN {txs}",
            f"DELETE FROM transaction WHERE workspace_id IN ({lista})",
            f"DELETE FROM settlement WHERE workspace_id IN ({lista})",
            f"DELETE FROM recurringexpense WHERE workspace_id IN ({lista})",
            f"DELETE FROM monthlyestimate WHERE workspace_id IN ({lista})",
            f"DELETE FROM workspaceinvite WHERE workspace_id IN ({lista})",
            f"DELETE FROM category WHERE workspace_id IN ({lista})",
            f"DELETE FROM tag WHERE workspace_id IN ({lista})",
            f"DELETE FROM workspacemembership WHERE workspace_id IN ({lista})",
            f"DELETE FROM workspace WHERE id IN ({lista})",
        ):
            db.exec(text(sql))

    # O eixo pessoal: do dono e das contas de demonstração.
    pessoas = demo_users + [dono.id]
    lista_p = ",".join(str(i) for i in pessoas)
    contas = f"(SELECT id FROM paymentaccount WHERE owner_user_id IN ({lista_p}))"
    for sql in (
        f"DELETE FROM statementpayment WHERE account_id IN {contas}",
        f"DELETE FROM accounttransfer WHERE from_account_id IN {contas} OR to_account_id IN {contas}",
        f"DELETE FROM accountentry WHERE account_id IN {contas}",
        f"DELETE FROM income WHERE user_id IN ({lista_p})",
        f"DELETE FROM recurringincome WHERE user_id IN ({lista_p})",
        f"DELETE FROM amortizationinstallment WHERE financing_id IN (SELECT id FROM financing WHERE owner_user_id IN ({lista_p}))",
        f"DELETE FROM financing WHERE owner_user_id IN ({lista_p})",
        f"DELETE FROM cardstatement WHERE card_id IN (SELECT id FROM creditcard WHERE owner_user_id IN ({lista_p}))",
        f"DELETE FROM creditcard WHERE owner_user_id IN ({lista_p})",
        f"DELETE FROM paymentaccount WHERE owner_user_id IN ({lista_p})",
    ):
        db.exec(text(sql))

    if demo_users:
        lista_d = ",".join(str(i) for i in demo_users)
        db.exec(text(f"DELETE FROM workspacemembership WHERE user_id IN ({lista_d})"))
        db.exec(text(f"DELETE FROM notification WHERE user_id IN ({lista_d})"))
        db.exec(text(f"DELETE FROM refreshsession WHERE user_id IN ({lista_d})"))
        db.exec(text(f"DELETE FROM pushsubscription WHERE user_id IN ({lista_d})"))
        # A AUDITORIA fica: ela é o registro de quem fez o quê, e apagá-la para
        # remover dado de demonstração seria apagar a trilha justamente na parte
        # em que ela mais serve. O `user_id` é anulado (a coluna aceita), então o
        # log sobrevive sem prender a linha da pessoa.
        db.exec(text(f"UPDATE auditlog SET user_id = NULL WHERE user_id IN ({lista_d})"))
        db.exec(text(f"DELETE FROM \"user\" WHERE id IN ({lista_d})"))

    db.flush()
    print(f"Limpo: {len(ids)} espaço(s) e {len(demo_users)} conta(s) de demonstração.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dono", default="gabriel-barros15@live.com",
                   help="e-mail da conta que recebe o eixo pessoal")
    p.add_argument("--limpar", action="store_true",
                   help="apaga o que o script criou antes de semear de novo")
    args = p.parse_args()

    with Session(engine) as db:
        if args.limpar:
            limpar(db, args.dono)
        c = semear(db, args.dono)
        historia_dos_espacos(db, c)
        contas, cartoes = vida_pessoal(db, c)
        vida_das_demais(db, c)
        recorrencias_e_acertos(db, c)
        o_que_falta(db, c, contas, cartoes)
        db.commit()
        print(f"Semeado. Dono: {c['dono'].name} <{c['dono'].email}>")
        print("Contas fictícias: senha123 (marina@, rafael@, camila@, bruno@, tiago@, helena@demo.cf4.app)")
        resumo(db, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
