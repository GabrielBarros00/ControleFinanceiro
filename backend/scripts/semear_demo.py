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
    AdjustmentType,
    PaymentMethod,
    SplitMethod,
    SplitMode,
    Transaction,
    TransactionStatus,
)
from app.schemas.transaction import (  # noqa: E402
    TransactionAdjustmentCreate,
    TransactionItemCreate,
    TransactionItemShareBase,
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
from app.services.base_conversion import compute_statement_conversion  # noqa: E402
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
    #: Divisão que NÃO é igual: `[(user, método, valor)]`. Cobre porcentagem e
    #: valor fixo, que têm tela própria ("Opções avançadas") e nunca eram
    #: semeados — a tela ficava sem caso para desenhar.
    divisao: Optional[list] = None,
    #: Mais de um pagador (ADR 0004): `[(user, valor)]`.
    pagadores: Optional[list] = None,
    #: Divisão POR ITEM: `[(título, valor, [users])]`. Outro modo inteiro do
    #: formulário, com editor próprio.
    itens: Optional[list] = None,
    #: Desconto, frete, gorjeta… `[(tipo, valor)]`, com o sinal do tipo.
    ajustes: Optional[list] = None,
    #: Deslocamento de fatura (ADR 0032): a compra cai no ciclo seguinte.
    shift: int = 0,
    status: TransactionStatus = TransactionStatus.confirmed,
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
            status=status,
            workspace_id=ws.id,
            created_by_user_id=pagador.id,
            payment_method=metodo,
            credit_card_id=cartao.id if cartao else None,
            statement_shift=shift,
            split_mode=SplitMode.item if itens else SplitMode.transaction,
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

        quem_pagou = (
            [TransactionPayerBase(user_id=u.id, amount=Decimal(v)) for u, v in pagadores]
            if pagadores
            else [TransactionPayerBase(user_id=pagador.id, amount=bruto)]
        )
        if divisao:
            partes = [
                TransactionSplitBase(user_id=u.id, split_method=m, input_value=Decimal(v))
                for u, m, v in divisao
            ]
        else:
            partes = [
                TransactionSplitBase(
                    user_id=u.id, split_method=SplitMethod.equal, input_value=Decimal("0"),
                )
                for u in entre
            ]
        linhas = None
        if itens:
            # No modo item os splits derivam das SHARES de cada linha
            # (`item_split_service`), então a lista de cima não vale — por isso
            # ela vai vazia.
            partes = []
            linhas = [
                TransactionItemCreate(
                    title=titulo_item, amount=Decimal(valor_item),
                    shares=[
                        TransactionItemShareBase(
                            user_id=u.id, split_method=SplitMethod.equal,
                            input_value=Decimal("0"),
                        )
                        for u in quem_do_item
                    ],
                )
                for titulo_item, valor_item, quem_do_item in itens
            ]

        persist_transaction_children(
            db, ws.id, tx,
            total_amount=bruto,
            split_mode=SplitMode.item if itens else SplitMode.transaction,
            payers=quem_pagou,
            splits=partes,
            items=linhas,
            adjustments=[
                TransactionAdjustmentCreate(type=tipo, amount=Decimal(valor))
                for tipo, valor in (ajustes or [])
            ] or None,
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
            # ROTEAR, e não só criar a fatura. A primeira versão chamava
            # `get_or_create_statement` e descartava o resultado: as compras
            # ficavam com cartão e `statement_id` nulo — apareciam na lista, não
            # entravam em fatura nenhuma e o total da fatura somava 0,00 para
            # sempre. A conferência dos cartões foi quem viu.
            #
            # A perna de FATURA (ADR 0024) vem junto: é ela que
            # `compute_statement_total` soma, e sem ela o total continuaria zero
            # mesmo com o vínculo certo.
            fatura = CreditCardService.get_or_create_statement(db, cartao, data_i)
            tx.statement_id = fatura.id
            for campo, valor in compute_statement_conversion(
                db, cartao,
                currency=tx.currency, total_amount=bruto, transaction_date=data_i,
            ).items():
                setattr(tx, campo, valor)
            db.add(tx)
            db.flush()
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

    # --- Os modos de divisão que só existiam no formulário ----------------
    #
    # Divisão IGUAL era a única coisa semeada, e o app tem outras três: por
    # porcentagem, por valor fixo e por ITEM (com editor próprio). Uma tela sem
    # caso para desenhar é uma tela que ninguém consegue diagnosticar.
    despesa(db, casa, titulo="Jantar de aniversário", valor="480.00",
            quando=meses_atras(1, 21), pagador=dono, entre=trio_casa,
            categoria=cc["Lazer"],
            divisao=[(dono, SplitMethod.percentage, "50"),
                     (marina, SplitMethod.percentage, "30"),
                     (rafael, SplitMethod.percentage, "20")])
    despesa(db, casa, titulo="Material de construção", valor="1260.00",
            quando=meses_atras(2, 17), pagador=marina, entre=trio_casa,
            categoria=cc["Moradia"],
            divisao=[(dono, SplitMethod.fixed, "800.00"),
                     (marina, SplitMethod.fixed, "300.00"),
                     (rafael, SplitMethod.fixed, "160.00")])
    # POR ITEM: cada linha da nota tem os seus donos — o remédio é só de quem
    # tomou, a comida é de todos.
    despesa(db, casa, titulo="Mercado com farmácia junto", valor="340.00",
            quando=meses_atras(1, 9), pagador=dono, entre=trio_casa,
            categoria=cc["Mercado"],
            itens=[("Compras da casa", "260.00", trio_casa),
                   ("Remédio da Marina", "80.00", [marina])])
    # DOIS PAGADORES na mesma despesa (ADR 0004) + AJUSTES (frete, desconto).
    #
    # O ajuste RECONCILIA itens com o total, então ele exige os itens — e a
    # conta tem de fechar: 1.500 de itens + 120 de frete − 70 de desconto =
    # 1.550. O serviço recusa qualquer outra soma, e faz bem.
    despesa(db, casa, titulo="Móvel novo (frete e desconto)", valor="1550.00",
            quando=meses_atras(3, 19), pagador=dono, entre=trio_casa,
            categoria=cc["Moradia"],
            pagadores=[(dono, "1000.00"), (marina, "550.00")],
            itens=[("Sofá", "1500.00", trio_casa)],
            ajustes=[(AdjustmentType.shipping, "120.00"),
                     (AdjustmentType.discount, "-70.00")])
    # CANCELADA: o estado que some dos totais mas fica no histórico.
    despesa(db, casa, titulo="Compra cancelada pela loja", valor="219.90",
            quando=meses_atras(2, 24), pagador=dono, entre=trio_casa,
            status=TransactionStatus.cancelled)

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

    # DESLOCAMENTO de fatura (ADR 0032): a compra feita perto do fechamento cai
    # no ciclo seguinte. Sem um caso destes, a tela do deslocamento não tem o que
    # mostrar e o seletor de fatura do detalhe nunca aparece diferente.
    despesa(db, c["casa"], titulo="Compra perto do fechamento", valor="420.00",
            quando=meses_atras(1, 2), pagador=dono, entre=[dono],
            metodo=PaymentMethod.credit_card, cartao=cartoes["Nubank Roxinho"],
            shift=1)

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
    # PIX, e não cartão: a Marina não tem cartão cadastrado, e "no cartão" sem
    # cartão é um estado que não existe — a rota agora recusa. Foi o semeador que
    # o produziu (escrevendo pelo modelo, sem passar pela validação da rota) e a
    # varredura de telas que o encontrou, em Contas a pagar.
    db.add(RecurringExpense(
        title="Internet e streaming", base_amount=Decimal("189.80"), day_of_month=12,
        workspace_id=casa.id, created_by_user_id=marina.id, payer_user_id=marina.id,
        currency="BRL", payment_method=PaymentMethod.pix,
        category_id=cc["Assinaturas"].id, start_date=meses_atras(7, 12).date(),
        is_active=True, split_snapshot=dividido(dono, marina, rafael),
    ))
    # Uma SEM divisão (100% de quem cadastrou) e uma INATIVA: os dois estados
    # que a lista precisa mostrar diferente.
    db.add(RecurringExpense(
        title="Academia", base_amount=Decimal("129.00"), day_of_month=8,
        workspace_id=casa.id, created_by_user_id=dono.id, payer_user_id=dono.id,
        currency="BRL", payment_method=PaymentMethod.credit_card,
        credit_card_id=c["cartao_do_dono"].id,
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
    # A CADA N períodos (ADR 0030), e com FIM declarado: os dois eixos da
    # recorrência que a tela sabe desenhar ("a cada 3 meses", "87 de 144
    # restantes") e que nunca tinham dado para exibir.
    db.add(RecurringExpense(
        title="Manutenção preventiva do carro", base_amount=Decimal("380.00"),
        day_of_month=18, frequency="monthly", interval=3,
        workspace_id=casa.id, created_by_user_id=dono.id, payer_user_id=dono.id,
        currency="BRL", payment_method=PaymentMethod.pix,
        start_date=meses_atras(6, 18).date(), is_active=True,
    ))
    db.add(RecurringExpense(
        title="Mensalidade do curso (12x)", base_amount=Decimal("560.00"),
        day_of_month=10, workspace_id=casa.id, created_by_user_id=dono.id,
        payer_user_id=dono.id, currency="BRL", payment_method=PaymentMethod.boleto,
        start_date=meses_atras(4, 10).date(),
        end_date=_somar_meses(meses_atras(4, 10), 12).date(),
        is_active=True,
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
    from app.models.credit_card import CardStatement, StatementStatus  # noqa: F401
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
        # FECHAR pelo serviço, não marcando o status na mão: é o fechamento que
        # CONGELA o total faturado, e sem ele `statement_balance` calcula saldo
        # zero e o pagamento é recusado com "esta fatura já está quitada". Foi o
        # que aconteceu — marcar o campo não é fechar a fatura.
        CreditCardService.close_statement(db, st)
        db.flush()
        CreditCardService.pay_statement(
            db, st, account=contas["Nubank"], amount=total,
            paid_at=meses_atras(2, 12), note="pagamento total", user_id=dono.id,
        )

    # --- Uma fatura VENCIDA e outra com pagamento PARCIAL ----------------
    #
    # A vencida aciona o aviso de atraso do cartão; a parcial exercita o saldo
    # CUMULATIVO do ADR 0023 — a fatura continua `closed` até chegar a zero, e
    # antes disso qualquer valor positivo a marcava como paga.
    abertas = db.exec(
        select(CardStatement)
        .where(CardStatement.card_id.in_([x.id for x in cartoes.values()]))
        .where(CardStatement.status == StatementStatus.open)
        .order_by(CardStatement.month)
    ).all()
    for st in abertas:
        total = CreditCardService.compute_statement_total(db, st.id)
        if total <= 0:
            continue
        # `due_date` é INSTANTE aqui, e `HOJE` é dia civil — comparar os dois
        # direto estoura. A conversão explícita é a mesma que o app faz.
        vence = st.due_date.date() if hasattr(st.due_date, "date") else st.due_date
        if vence and vence < HOJE:
            CreditCardService.close_statement(db, st)
            db.flush()
            continue  # fechada e NÃO paga: é a fatura vencida
        CreditCardService.close_statement(db, st)
        db.flush()
        CreditCardService.pay_statement(
            db, st, account=contas["Nubank"],
            amount=(total / 2).quantize(Decimal("0.01")),
            paid_at=meses_atras(0, 3), note="pagamento parcial", user_id=dono.id,
        )
        break

    # --- Ajuste de saldo de conta ----------------------------------------
    #
    # "Conferi o extrato e faltavam R$ 35" — o ajuste é como o app reconcilia
    # sem inventar despesa.
    from app.domain.dates import civil_instant
    from app.models.account_ledger import AccountEntry, AccountEntryKind
    db.add(AccountEntry(
        account_id=contas["Itaú"].id,
        kind=AccountEntryKind.adjustment,
        # COM SINAL: negativo tira. É como a rota grava (me_accounts.py).
        amount=Decimal("-35.00"),
        occurred_at=civil_instant(meses_atras(1, 22).date()),
        description="conferência com o extrato do banco",
        created_by_user_id=dono.id,
    ))

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

    # --- Um lote de importação já processado ------------------------------
    #
    # A tela de Importar guarda o histórico por lote e por LINHA (ADR 0008) — e
    # a listagem abre vazia numa base semeada, junto com o resumo
    # "importadas / duplicadas / ignoradas" que é o coração dela.
    #
    # O lote aponta para lançamentos que já existem: um lote cujas linhas não
    # levam a lugar nenhum seria um histórico de mentira.
    from app.models.import_batch import (
        ImportBatch,
        ImportRow,
        ImportRowStatus,
        compute_fingerprint,
    )

    if not db.exec(select(ImportBatch).where(ImportBatch.workspace_id == casa.id)).first():
        importadas = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id == casa.id)
            .where(Transaction.deleted_at.is_(None))
            .order_by(Transaction.transaction_date.desc())
            .limit(3)
        ).all()
        lote = ImportBatch(
            workspace_id=casa.id, filename="extrato-agosto.csv",
            created_by_user_id=dono.id,
            total_rows=len(importadas) + 2,
            imported_count=len(importadas), duplicate_count=1, ignored_count=1,
            created_at=meses_atras(1, 3),
        )
        db.add(lote)
        db.flush()
        for i, t in enumerate(importadas, start=1):
            db.add(ImportRow(
                batch_id=lote.id, workspace_id=casa.id, line=i, title=t.title,
                amount=t.total_amount, transaction_date=t.transaction_date,
                fingerprint=compute_fingerprint(
                    casa.id, t.transaction_date, t.total_amount, t.title,
                ),
                status=ImportRowStatus.imported, transaction_id=t.id,
            ))
        # A DUPLICADA e a IGNORADA: os dois desfechos que explicam a diferença
        # entre "linhas do arquivo" e "lançamentos criados".
        for linha, titulo, status, motivo in [
            (len(importadas) + 1, "Mercado do mês", ImportRowStatus.duplicate,
             "já existe um lançamento igual neste dia"),
            (len(importadas) + 2, "SALDO ANTERIOR", ImportRowStatus.ignored,
             "linha sem valor de lançamento"),
        ]:
            db.add(ImportRow(
                batch_id=lote.id, workspace_id=casa.id, line=linha, title=titulo,
                amount=Decimal("0.00"), transaction_date=meses_atras(1, 3),
                fingerprint=compute_fingerprint(
                    casa.id, meses_atras(1, 3), Decimal("0.00"), titulo,
                ),
                status=status, reason=motivo,
            ))

    # --- Um recibo anexado ------------------------------------------------
    #
    # A seção de anexos existe em todo detalhe de lançamento e abre vazia numa
    # base semeada — junto com a cota de armazenamento, que nunca sai de 0%. O
    # conteúdo vive FORA do banco (ADR 0007), então o arquivo é gravado pelo
    # mesmo `AttachmentStorage` das rotas, com o sha256 de verdade.
    import hashlib

    from app.models.attachment import Attachment
    from app.services.attachment_storage import AttachmentStorage

    alvo = db.exec(
        select(Transaction)
        .where(Transaction.workspace_id == casa.id)
        .where(Transaction.title == "Móvel novo (frete e desconto)")
    ).first()
    if alvo is not None and not db.exec(
        select(Attachment).where(Attachment.transaction_id == alvo.id)
    ).first():
        # Um PDF mínimo de verdade: o app guarda `content_type`, e um .txt
        # disfarçado de PDF deixaria a visualização quebrada na tela.
        conteudo = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
        )
        sha = hashlib.sha256(conteudo).hexdigest()
        chave = AttachmentStorage.save(casa.id, sha, conteudo)
        db.add(Attachment(
            workspace_id=casa.id, transaction_id=alvo.id,
            filename="nota-fiscal-sofa.pdf", content_type="application/pdf",
            size_bytes=len(conteudo), sha256=sha, storage_key=chave,
            uploaded_by_user_id=dono.id,
        ))

    # --- Avisos no sino ---------------------------------------------------
    #
    # A central de avisos abre vazia numa base recém-semeada, e ela é uma tela
    # inteira: sem um item dentro, não dá para ver como o não-lido se distingue
    # do lido, nem o agrupamento.
    from app.models.notification import Notification, NotificationType
    for tipo, titulo, corpo, lida in [
        (NotificationType.due_reminder, "Fatura do Nubank Roxinho fecha em 3 dias",
         "Compras feitas depois do fechamento entram na fatura seguinte.", False),
        (NotificationType.member_added, "Rafael entrou na República",
         "Ele já aparece nas divisões do espaço.", True),
    ]:
        db.add(Notification(
            user_id=dono.id, type=tipo, title=titulo, body=corpo,
            read_at=datetime.now(UTC) if lida else None,
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
            # O canal de tempo real guarda um evento por mutação, com FK para o
            # espaço: sem apagá-los, o Postgres (com razão) recusa remover o
            # espaço. São eventos de sincronização, não histórico — morrem com
            # a sala a que pertencem.
            f"DELETE FROM syncevent WHERE workspace_id IN ({lista})",
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
        # O cartão do dono é insumo das recorrências no crédito (uma delas usa).
        c["cartao_do_dono"] = cartoes["Nubank Roxinho"]
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
