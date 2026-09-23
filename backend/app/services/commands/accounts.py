"""Comandos de CONTA de pagamento pessoal: transferência e conciliação (ADR 0034).

Movidos de `api/routes/me_balance.py` e `api/routes/me_accounts.py` sem mudança
de regra (ADR 0035): só o `commit` saiu — quem chama (rota REST ou pipeline do
MCP) comanda a transação. O `flush` no fim garante o `id` para quem chamou.
"""
from decimal import Decimal
from typing import Tuple

from fastapi import HTTPException
from sqlmodel import Session

from app.domain.access_policy import assert_owns
from app.domain.dates import civil_instant, today_local
from app.models.account_ledger import AccountEntry, AccountEntryKind, AccountTransfer
from app.models.payment_account import PaymentAccount
from app.schemas.balance import AdjustmentRequest, TransferCreate
from app.services.account_balance_service import AccountBalanceService


def _conta_do_usuario(session: Session, account_id: int, user_id: int) -> PaymentAccount:
    conta = session.get(PaymentAccount, account_id)
    if not conta or conta.deleted_at:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    assert_owns(conta.owner_user_id, user_id, detail="Conta não encontrada")
    return conta


def create_transfer(
    session: Session, user_id: int, body: TransferCreate
) -> Tuple[AccountTransfer, PaymentAccount, PaymentAccount]:
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
    origem = _conta_do_usuario(session, body.from_account_id, user_id)
    destino = _conta_do_usuario(session, body.to_account_id, user_id)
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
        created_by_user_id=user_id,
    )
    session.add(transferencia)
    session.flush()
    return transferencia, origem, destino


def _get_account_or_404(session: Session, account_id: int, user_id: int) -> PaymentAccount:
    account = session.get(PaymentAccount, account_id)
    if not account or account.deleted_at:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    assert_owns(account.owner_user_id, user_id, detail="Conta não encontrada")
    return account


def adjust_balance(
    session: Session, user_id: int, account_id: int, body: AdjustmentRequest
) -> dict:
    """Conciliação: o app diz 4.821,53 e o banco diz 4.900,00.

    O corpo traz o saldo REAL — é o número que a pessoa tem à mão —, e o servidor
    calcula a diferença. Pedir o delta faria as duas pontas divergirem na primeira
    conta feita de cabeça.

    O ajuste vira uma LINHA DATADA no extrato, com motivo. Ele não reescreve valor
    nenhum do passado: "se o usuário ajustar saldo hoje, não reescreva valores
    antigos para fazer o saldo fechar" (§29 do pedido). E não é renda nem despesa —
    não aparece em `cash_in`/`cash_out`, não muda consumo e não muda o resultado do
    mês.
    """
    account = _get_account_or_404(session, account_id, user_id)
    quando = body.occurred_on or today_local()

    anterior = AccountBalanceService.saldo_em(session, user_id, account, quando)
    if anterior is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A conta '{account.name}' ainda não tem saldo inicial. Informe o "
                "saldo e a data dele antes de conciliar — sem ponto de partida não "
                "há diferença a calcular."
            ),
        )

    delta = body.real_balance - anterior
    if delta == Decimal("0.00"):
        raise HTTPException(
            status_code=422,
            detail="O saldo informado é igual ao calculado: não há o que ajustar",
        )

    entrada = AccountEntry(
        account_id=account.id,
        kind=AccountEntryKind.adjustment,
        amount=delta,
        occurred_at=civil_instant(quando),
        description=body.note or "Ajuste de saldo",
        created_by_user_id=user_id,
    )
    session.add(entrada)
    session.flush()
    return {
        "id": entrada.id,
        "account_id": account.id,
        "amount": delta,
        "occurred_on": quando,
        "description": entrada.description,
        "previous_balance": anterior,
        "new_balance": body.real_balance,
    }
