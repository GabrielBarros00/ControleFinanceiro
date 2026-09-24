"""Comandos do FINANCIAMENTO pessoal: pagar e desfazer o pagamento de uma parcela.

Movidos de `api/routes/me_financing.py` sem mudança de regra (ADR 0035): só o
`commit` saiu — quem chama (rota REST ou pipeline do MCP) comanda a transação. A
rota segue tratando o `IntegrityError` do commit (a segunda linha de defesa da
reivindicação atômica).
"""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from app.domain.access_policy import assert_owns
from app.domain.account_policy import AccountCurrencyMismatch, assert_conta_na_moeda
from app.domain.dates import month_key_local
from app.domain.settlement import resolve_settled_at
from app.models.financing import AmortizationInstallment, Financing, FinancingStatus
from app.models.payment_account import PaymentAccount
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.workspace import WorkspaceMembership
from app.schemas.financing import InstallmentPayRequest
from app.services.base_conversion import compute_base_conversion
from app.services.event_service import publish_event


def get_financing_or_404(session: Session, financing_id: int, user_id: int) -> Financing:
    financing = session.get(Financing, financing_id)
    if not financing or financing.deleted_at:
        raise HTTPException(status_code=404, detail="Financiamento não encontrado")
    assert_owns(financing.owner_user_id, user_id, detail="Financiamento não encontrado")
    return financing


def assert_member(session: Session, workspace_id: int, user_id: int) -> None:
    membro = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).first()
    if not membro:
        raise HTTPException(status_code=400, detail="Você não participa deste workspace")


def pay_installment(
    session: Session,
    user_id: int,
    financing_id: int,
    installment_number: int,
    body: InstallmentPayRequest,
) -> Optional[int]:
    """Marca a parcela como paga (e, com `workspace_id`, lança a despesa).

    Devolve o id da despesa criada, ou `None`.
    """
    financing = get_financing_or_404(session, financing_id, user_id)
    # Só financiamento ATIVO é dívida contratada. Um `simulated` é plano: pagar
    # parcela dele registrava gasto real a partir de uma simulação.
    if financing.status != FinancingStatus.active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Financiamento não está ativo (status: "
                f"{getattr(financing.status, 'value', financing.status)}) — "
                "não é possível pagar parcelas."
            ),
        )
    installment = session.exec(
        select(AmortizationInstallment).where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.installment_number == installment_number,
        )
    ).first()
    if not installment:
        raise HTTPException(status_code=404, detail="Parcela não encontrada")
    if installment.is_paid:
        raise HTTPException(status_code=400, detail="Parcela já está paga")

    pago_em = body.paid_at or datetime.now(UTC)

    # A conta é validada ANTES da reivindicação: recusar depois deixaria a parcela
    # marcada como paga por uma requisição que termina em 400.
    conta_id = None
    if body.account_id is not None:
        conta = session.get(PaymentAccount, body.account_id)
        if not conta or conta.deleted_at or conta.owner_user_id != user_id:
            raise HTTPException(status_code=400, detail="Conta inválida")
        if not conta.active:
            raise HTTPException(
                status_code=400, detail=f"Conta '{conta.name}' está desativada"
            )
        try:
            # A parcela é somada ao saldo na moeda do FINANCIAMENTO — é assim que
            # `CashFlowService._parcelas` a expressa (ADR 0034).
            assert_conta_na_moeda(conta, financing.currency)
        except AccountCurrencyMismatch as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        conta_id = conta.id

    # REIVINDICA a parcela antes de qualquer outra escrita. A checagem acima
    # sozinha é lê-depois-escreve: duas requisições simultâneas liam
    # `is_paid=False`, ambas passavam e cada uma criava a sua despesa — a mesma
    # parcela virava dois lançamentos, dobrando caixa, relatórios e gasto do
    # workspace. Este `UPDATE` condicional é atômico nos dois motores (no
    # Postgres a concorrente bloqueia e reavalia o WHERE contra a versão já
    # commitada; no SQLite é uma sentença só). `FOR UPDATE` não serviria: o
    # dialeto SQLite o ignora em silêncio.
    reivindicou = session.execute(
        update(AmortizationInstallment)
        .where(AmortizationInstallment.id == installment.id)
        .where(AmortizationInstallment.is_paid.is_(False))
        # `account_id` no MESMO `UPDATE` que reivindica a parcela (ADR 0034): uma
        # escrita ORM separada correria com a concorrente, e a conta poderia ser
        # gravada por quem perdeu a corrida sobre a parcela do vencedor.
        .values(is_paid=True, paid_at=pago_em, account_id=conta_id)
    ).rowcount
    if not reivindicou:
        # 409, não 400: quem chamou não errou nada — perdeu a corrida.
        raise HTTPException(
            status_code=409,
            detail="Esta parcela acabou de ser paga por outra requisição.",
        )
    # O UPDATE direto não passa pela sessão; sem expirar, o objeto em memória
    # seguiria com `is_paid=False` e o cálculo de quitação abaixo erraria.
    session.expire(installment)

    transaction_id = None
    if body.workspace_id is not None:
        assert_member(session, body.workspace_id, user_id)
        # A despesa segue a data EFETIVA do pagamento, não o vencimento: o caixa
        # é sobre quando o dinheiro saiu, e a parcela e a despesa vinculada
        # precisam cair no mesmo mês (é a dedup do `CashFlowService` que depende
        # disso — com datas diferentes, a saída trocava de mês).
        valor = installment.total_amount
        moeda = financing.currency
        conversao_meta = {}
        # MESMO pipeline dos lançamentos comuns (ADR 0015). Sem ele a despesa
        # nascia na moeda do financiamento dentro de um workspace de outra base,
        # e sumia de todas as agregações — que filtram `currency == base`.
        # `payment_method=None`: parcela não é compra no cartão, então sem IOF.
        conv = compute_base_conversion(
            session,
            body.workspace_id,
            currency=moeda,
            total_amount=valor,
            transaction_date=pago_em,
            payment_method=None,
        )
        if conv is not None:
            valor = conv["base_total"]
            moeda = conv["base_currency"]
            conversao_meta = conv["meta"]

        payment_tx = Transaction(
            title=f"{financing.title} — Parcela {installment_number}/{financing.installments_count}",
            total_amount=valor,
            transaction_date=pago_em,
            # `month_key_local`: `pago_em` é um INSTANTE. Derivar o mês do
            # ano/mês em UTC dava competência de agosto a uma parcela paga às
            # 22h de 31 de julho em São Paulo — e a despesa sumia de todas as
            # telas, que pedem julho.
            billing_month=month_key_local(pago_em),
            currency=moeda,
            workspace_id=body.workspace_id,
            created_by_user_id=user_id,
            status=TransactionStatus.confirmed,
            # Identidade da parcela: é por aqui que o estorno reencontra a despesa.
            # Pelo título, renomear o financiamento deixava a despesa órfã.
            financing_installment_id=installment.id,
            # A rota chama-se "pagar parcela": o dinheiro saiu agora, na data
            # informada (ADR 0029). Nasce liquidada, e por isso `explicit=True` —
            # sem ele, pagar uma parcela com data futura (adiantamento) criaria
            # uma conta a pagar por algo que a pessoa acabou de pagar. É também o
            # que mantém a dedup do `CashFlowService` honesta: a despesa entra no
            # caixa e a parcela é ignorada, como sempre foi.
            settled_at=resolve_settled_at(
                session, body.workspace_id,
                transaction_date=pago_em, explicit=True,
            ),
            **conversao_meta,
        )
        session.add(payment_tx)
        session.flush()
        session.add(TransactionPayer(
            transaction_id=payment_tx.id, user_id=user_id,
            amount=valor,
            # A conta é COPIADA da parcela, não uma segunda fonte (ADR 0034):
            # enquanto esta despesa existe, a dedup do `CashFlowService` suprime
            # a parcela e é o pagador que conta. Guardá-la nos dois como fontes
            # independentes faria, ao desmarcar o pagamento da despesa, a parcela
            # voltar carregando uma conta congelada que pode não ser a atual.
            account_id=conta_id,
        ))
        session.add(TransactionSplit(
            transaction_id=payment_tx.id, user_id=user_id,
            split_method=SplitMethod.equal, input_value=Decimal("100"),
            computed_amount=valor,
        ))
        transaction_id = payment_tx.id
        publish_event(
            session, body.workspace_id, "transaction.created", "transaction",
            payment_tx.id, user_id,
        )

    # Se todas pagas, o financiamento é quitado
    unpaid = session.exec(
        select(AmortizationInstallment).where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.is_paid.is_(False),
            AmortizationInstallment.id != installment.id,
        )
    ).first()
    if not unpaid:
        financing.status = FinancingStatus.settled
        session.add(financing)

    session.flush()
    return transaction_id


def unpay_installment(session: Session, user_id: int, financing_id: int, installment_number: int) -> None:
    """Estorna o pagamento de uma parcela.

    `is_paid` era irreversível: um clique errado não tinha desfazer, e a despesa
    gerada ficava para sempre no caixa. Aqui a parcela volta a aberta, a despesa
    correspondente (se houve) é soft-deletada e o financiamento sai de `settled`.
    """
    financing = get_financing_or_404(session, financing_id, user_id)

    installment = session.exec(
        select(AmortizationInstallment).where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.installment_number == installment_number,
        )
    ).first()
    if not installment:
        raise HTTPException(status_code=404, detail="Parcela não encontrada")
    if not installment.is_paid:
        raise HTTPException(status_code=400, detail="Parcela não está paga")

    installment.is_paid = False
    installment.paid_at = None
    # Reabrir desfaz também a afirmação "isto foi pago antes de eu cadastrar o
    # contrato". Sem limpar, uma parcela que veio da quitação em lote e depois
    # fosse paga de verdade pela rota individual ficaria invisível no caixa para
    # sempre — o marcador é do fato antigo, não da parcela.
    installment.paid_outside_app = False
    session.add(installment)

    # O vínculo é por ID (`financing_installment_id`): pelo título, renomear o
    # financiamento fazia o estorno não achar nada — a despesa ficava para sempre
    # no caixa com a parcela já reaberta — e uma despesa manual homônima era
    # apagada junto.
    geradas = list(session.exec(
        select(Transaction).where(
            Transaction.financing_installment_id == installment.id,
            Transaction.deleted_at.is_(None),
        )
    ).all())
    workspaces_afetados = set()
    for tx in geradas:
        tx.deleted_at = datetime.now(UTC)
        session.add(tx)
        workspaces_afetados.add(tx.workspace_id)

    if financing.status == FinancingStatus.settled:
        financing.status = FinancingStatus.active
        session.add(financing)

    for workspace_id in sorted(workspaces_afetados):
        publish_event(
            session, workspace_id, "transaction.bulk_updated", "transaction",
            None, user_id,
        )
    session.flush()
