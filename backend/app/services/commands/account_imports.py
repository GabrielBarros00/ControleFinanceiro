"""Importação de EXTRATO DE CONTA: entradas, transferências e pagamento de fatura (ADR 0037).

A importação do ADR 0008 é de despesas de um espaço: toda linha vira lançamento,
com o valor em módulo. Um extrato de conta tem mais que isso — o salário que
caiu, o Pix recebido, a transferência para a poupança, o pagamento da fatura —
e importados como despesa esses movimentos inflavam o gasto (e o pagamento da
fatura somava duas vezes as compras do cartão).

Aqui cada linha tem um SENTIDO (entrou/saiu, o sinal do extrato) e uma
CLASSIFICAÇÃO, e vira o registro que o app já tem para aquilo, pelo MESMO
comando da tela:

- despesa → `create_transaction` no espaço escolhido, paga pela conta;
- renda → `create_income` na conta, já recebida;
- transferência → `create_transfer` com a outra conta da pessoa;
- pagamento de fatura → `pay_statement` na fatura que o pagamento quita.

O lote é PESSOAL (a conta é da pessoa, ADR 0021). Uma linha conta como já
importada enquanto o que ela criou existe (ADR 0036): pelo `external_id` que o
banco dá à linha, quando dá; senão pela impressão digital (conta, dia, sentido,
centavos, título).
"""
from __future__ import annotations

import io
from collections import Counter, defaultdict
from datetime import datetime, time
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlmodel import Session, func, select

from app.db.locks import trava_usuario
from app.domain.classificacao_de_extrato import sugerir
from app.domain.dates import civil_instant, local_day
from app.domain.query_policy import workspace_base_currency
from app.models.account_ledger import AccountTransfer
from app.models.attachment import Attachment
from app.models.category import Category
from app.models.credit_card import CreditCard, StatementPayment
from app.models.import_batch import (
    KIND_ACCOUNT,
    ImportBatch,
    ImportRow,
    ImportRowStatus,
    compute_account_fingerprint,
)
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.models.transaction import SplitMethod, Transaction
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole, role_level
from app.schemas.balance import TransferCreate
from app.schemas.imports import AccountCommitRequest, AccountCommitRow
from app.schemas.income import IncomeCreate
from app.schemas.transaction import TransactionCreate, TransactionPayerBase, TransactionSplitBase
from app.services import app_settings
from app.services.csv_parser import CSVColumnMapping, CSVParserService
from app.services.event_service import publish_event


def _ancora(quando: datetime) -> datetime:
    """Meia-noite cravada é uma data civil (ver `imports._ancora_data_civil`)."""
    if quando.time() == time.min:
        return civil_instant(local_day(quando.date()))
    return quando


def _conta_propria(session: Session, user_id: int, account_id: int) -> PaymentAccount:
    conta = session.get(PaymentAccount, account_id)
    if conta is None or conta.deleted_at is not None or conta.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    if not conta.active:
        raise HTTPException(status_code=400, detail=f"Conta '{conta.name}' está desativada")
    return conta


def _outras_contas(session: Session, user_id: int, conta: PaymentAccount) -> List[PaymentAccount]:
    return list(session.exec(
        select(PaymentAccount).where(
            PaymentAccount.owner_user_id == user_id, PaymentAccount.deleted_at.is_(None),
            PaymentAccount.active.is_(True), PaymentAccount.id != conta.id,
        ).order_by(PaymentAccount.name)
    ).all())


def _cartoes(session: Session, user_id: int) -> List[CreditCard]:
    return list(session.exec(
        select(CreditCard).where(CreditCard.owner_user_id == user_id, CreditCard.deleted_at.is_(None))
        .order_by(CreditCard.name)
    ).all())


def _vivo():
    """A linha importada cujo registro criado ainda existe."""
    return or_(
        and_(ImportRow.transaction_id.is_not(None), Transaction.deleted_at.is_(None)),
        and_(ImportRow.income_id.is_not(None), Income.deleted_at.is_(None)),
        and_(ImportRow.transfer_id.is_not(None), AccountTransfer.deleted_at.is_(None)),
        and_(ImportRow.statement_payment_id.is_not(None), StatementPayment.deleted_at.is_(None)),
    )


def _com_registros(consulta):
    return (
        consulta
        .outerjoin(Transaction, Transaction.id == ImportRow.transaction_id)
        .outerjoin(Income, Income.id == ImportRow.income_id)
        .outerjoin(AccountTransfer, AccountTransfer.id == ImportRow.transfer_id)
        .outerjoin(StatementPayment, StatementPayment.id == ImportRow.statement_payment_id)
    )


def _chaves_vivas(session: Session, account_id: int) -> Tuple[Set[str], Set[str]]:
    """(`external_id`s, impressões digitais) das linhas desta conta ainda vivas."""
    linhas = session.exec(
        _com_registros(select(ImportRow.external_id, ImportRow.fingerprint))
        .where(ImportRow.account_id == account_id, ImportRow.status == ImportRowStatus.imported, _vivo())
    ).all()
    return {e for e, _ in linhas if e}, {f for _, f in linhas}


# --- Prévia ----------------------------------------------------------------------------

def parse_account_statement(
    session: Session, user_id: int, account_id: int, conteudo: str, mapping: CSVColumnMapping,
) -> dict:
    """Lê o CSV com o SINAL preservado e devolve cada linha com o palpite."""
    conta = _conta_propria(session, user_id, account_id)
    resultado = CSVParserService.parse(io.StringIO(conteudo), mapping.model_copy(update={"keep_sign": True}))
    externos, digitais = _chaves_vivas(session, conta.id)
    outras = [(c.id, c.name) for c in _outras_contas(session, user_id, conta)]
    cartoes = [(c.id, c.name) for c in _cartoes(session, user_id)]
    for linha in resultado["rows"]:
        palpite = sugerir(linha["title"], linha["direction"], outras, cartoes)
        digital = compute_account_fingerprint(conta.id, linha["transaction_date"], linha["direction"],
                                              linha["total_amount"], linha["title"])
        linha["duplicate"] = bool(linha.get("external_id") and linha["external_id"] in externos) or digital in digitais
        linha["suggested_classification"] = palpite.classification
        linha["suggested_card_id"] = palpite.card_id
        linha["suggested_account_id"] = palpite.counterpart_account_id
    return {"account_id": conta.id, "currency": conta.currency, **resultado}


# --- Gravação --------------------------------------------------------------------------

class _Recusa(Exception):
    """A linha não entra, com o motivo (vira `skipped`, nunca some calada)."""


class _JaExiste(Exception):
    """O movimento já está no app por outro caminho (vira `duplicate`, com o motivo)."""


class _Contexto:
    """O que a importação consulta muitas vezes, lido uma vez."""

    def __init__(self, session: Session, user_id: int, conta: PaymentAccount):
        self.session = session
        self.user_id = user_id
        self.conta = conta
        self.contas = {c.id: c for c in _outras_contas(session, user_id, conta)}
        self.cartoes = {c.id: c for c in _cartoes(session, user_id)}
        self._membros: Dict[int, Optional[WorkspaceMembership]] = {}

    def membro(self, space_id: int) -> WorkspaceMembership:
        if space_id not in self._membros:
            self._membros[space_id] = self.session.exec(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == space_id, WorkspaceMembership.user_id == self.user_id,
                )
            ).first()
        membro = self._membros[space_id]
        if membro is None:
            raise _Recusa("espaço não encontrado")
        if role_level(membro.role) < role_level(WorkspaceRole.member):
            raise _Recusa("seu papel no espaço não permite lançar despesa")
        return membro


def _despesa(ctx: _Contexto, row: AccountCommitRow, quando: datetime) -> dict:
    from app.services.commands import transactions as tx_cmd

    if row.direction != "out":
        raise _Recusa("despesa é dinheiro que SAIU da conta")
    if row.space_id is None:
        raise _Recusa("escolha o espaço da despesa")
    membro = ctx.membro(row.space_id)
    moeda = workspace_base_currency(ctx.session, row.space_id)
    if moeda != ctx.conta.currency:
        raise _Recusa(f"a conta é em {ctx.conta.currency} e o espaço em {moeda}")
    if row.category_id is not None:
        categoria = ctx.session.get(Category, row.category_id)
        if categoria is None or categoria.workspace_id != row.space_id or categoria.deleted_at is not None:
            raise _Recusa("categoria não encontrada no espaço")
    tx = tx_cmd.create_transaction(ctx.session, row.space_id, TransactionCreate(
        title=row.title,
        total_amount=row.total_amount,
        transaction_date=quando,
        currency=ctx.conta.currency,
        category_id=row.category_id,
        payers=[TransactionPayerBase(user_id=ctx.user_id, amount=row.total_amount, account_id=ctx.conta.id)],
        splits=[TransactionSplitBase(user_id=ctx.user_id, split_method=SplitMethod.equal, input_value=Decimal("100"))],
        # Extrato é fato consumado (ADR 0029): o dinheiro já saiu da conta.
        settled=True,
    ), membro)
    return {"transaction_id": tx.id, "workspace_id": row.space_id}


def _renda(ctx: _Contexto, row: AccountCommitRow, quando: datetime) -> dict:
    from app.services.commands import income as income_cmd

    if row.direction != "in":
        raise _Recusa("renda é dinheiro que ENTROU na conta")
    renda = income_cmd.create_income(ctx.session, ctx.user_id, IncomeCreate(
        title=row.title, amount=row.total_amount, currency=ctx.conta.currency, received_at=quando,
        category=row.income_category, account_id=ctx.conta.id, received=True,
    ))
    return {"income_id": renda.id}


def _transferencia(ctx: _Contexto, row: AccountCommitRow, quando: datetime) -> dict:
    from app.services.commands import accounts as acc_cmd

    outra = ctx.contas.get(row.counterpart_account_id) if row.counterpart_account_id else None
    if outra is None:
        raise _Recusa("escolha a outra conta (sua) da transferência")
    if outra.currency != ctx.conta.currency:
        raise _Recusa("transferência entre moedas diferentes: registre pela tela de contas, com os dois valores")
    origem, destino = (ctx.conta, outra) if row.direction == "out" else (outra, ctx.conta)
    # A mesma transferência aparece nos extratos das DUAS contas. Importado o da
    # primeira, a linha espelhada do segundo é a mesma transferência, não outra.
    dia = local_day(quando)
    mesmas = ctx.session.exec(
        select(AccountTransfer).where(
            AccountTransfer.from_account_id == origem.id, AccountTransfer.to_account_id == destino.id,
            AccountTransfer.from_amount == row.total_amount, AccountTransfer.deleted_at.is_(None),
        )
    ).all()
    if any(local_day(t.occurred_at) == dia for t in mesmas):
        raise _JaExiste("a mesma transferência já está registrada (pelo extrato da outra conta?)")
    t, _, _ = acc_cmd.create_transfer(ctx.session, ctx.user_id, TransferCreate(
        from_account_id=origem.id, to_account_id=destino.id, from_amount=row.total_amount,
        occurred_on=local_day(quando), note=row.title,
    ))
    return {"transfer_id": t.id}


def _pagamento(ctx: _Contexto, row: AccountCommitRow, quando: datetime) -> dict:
    from app.services.commands import statements as stmt_cmd
    from app.services.credit_card_service import CreditCardService

    if row.direction != "out":
        raise _Recusa("pagamento de fatura é dinheiro que SAIU da conta")
    cartao = ctx.cartoes.get(row.card_id) if row.card_id else None
    if cartao is None:
        raise _Recusa("escolha o cartão da fatura")
    if cartao.currency != ctx.conta.currency:
        raise _Recusa(f"o cartão é em {cartao.currency} e a conta em {ctx.conta.currency}")
    dia = local_day(quando)
    fatura = stmt_cmd.fatura_do_pagamento(ctx.session, cartao, dia)
    if fatura is None:
        raise _Recusa(f"o {cartao.name} não tem fatura com saldo fechada até {dia.strftime('%d/%m/%Y')}")
    stmt_cmd.fechar_se_o_ciclo_acabou(ctx.session, fatura, dia)
    saldo = CreditCardService.statement_balance(ctx.session, fatura)
    if row.total_amount > saldo:
        raise _Recusa(f"valor maior que o saldo da fatura de {fatura.month} ({cartao.currency} {saldo})")
    stmt_cmd.pay_statement(ctx.session, ctx.user_id, cartao.id, fatura.id, account_id=ctx.conta.id,
                           amount=row.total_amount, paid_at=quando, note=row.title)
    pagamento = ctx.session.exec(
        select(StatementPayment).where(StatementPayment.statement_id == fatura.id)
        .order_by(StatementPayment.id.desc())
    ).first()
    return {"statement_payment_id": pagamento.id}


_CRIA = {"expense": _despesa, "income": _renda, "transfer": _transferencia, "statement_payment": _pagamento}


def commit_account_statement(session: Session, user_id: int, body: AccountCommitRequest) -> dict:
    """Grava o extrato com a decisão de cada linha. Uma linha que não pode entrar
    (sem espaço, conta errada, fatura sem saldo) vira `skipped` com o motivo; as
    outras entram. Um erro que o comando da tela levanta depois de validado
    derruba o lote inteiro, com o número da linha (nada gravado pela metade)."""
    teto = app_settings.get(session, "import_max_rows")
    if len(body.rows) > teto:
        raise HTTPException(status_code=422, detail=f"Importação limitada a {teto} linhas por lote")
    # Antes de ler o que já foi importado: dois envios do mesmo arquivo (duplo
    # clique) leriam o mesmo conjunto e gravariam os dois (ver `db/locks.py`).
    trava_usuario(session, user_id)
    conta = _conta_propria(session, user_id, body.account_id)
    externos, digitais = _chaves_vivas(session, conta.id)
    ctx = _Contexto(session, user_id, conta)

    lote = ImportBatch(kind=KIND_ACCOUNT, account_id=conta.id, workspace_id=None, filename=body.filename,
                       created_by_user_id=user_id, total_rows=len(body.rows))
    session.add(lote)
    session.flush()

    contagem: Counter = Counter()
    por_tipo: Counter = Counter()
    problemas: List[dict] = []
    espacos: Set[int] = set()
    for row in body.rows:
        quando = _ancora(row.transaction_date)
        classe = row.classification or ("expense" if row.direction == "out" else "income")
        digital = compute_account_fingerprint(conta.id, quando, row.direction, row.total_amount, row.title)
        base = dict(
            batch_id=lote.id, account_id=conta.id, line=row.line, title=row.title.strip()[:200],
            amount=row.total_amount, transaction_date=quando, fingerprint=digital,
            direction=row.direction, classification=classe, external_id=row.external_id,
        )
        if row.decision == "ignore":
            session.add(ImportRow(**base, status=ImportRowStatus.ignored))
            contagem["ignored"] += 1
            continue
        if (row.external_id and row.external_id in externos) or digital in digitais:
            session.add(ImportRow(**base, status=ImportRowStatus.duplicate, reason="já importado anteriormente"))
            contagem["duplicate"] += 1
            continue
        try:
            criado = _CRIA[classe](ctx, row, quando)
        except _JaExiste as ja:
            session.add(ImportRow(**base, status=ImportRowStatus.duplicate, reason=str(ja)))
            contagem["duplicate"] += 1
            continue
        except _Recusa as recusa:
            session.add(ImportRow(**base, status=ImportRowStatus.skipped, reason=str(recusa)))
            contagem["skipped"] += 1
            problemas.append({"line": row.line or 0, "reason": str(recusa)})
            continue
        except HTTPException as exc:
            raise HTTPException(status_code=exc.status_code, detail=f"Linha {row.line}: {exc.detail}")
        session.add(ImportRow(**base, **criado, status=ImportRowStatus.imported))
        if criado.get("workspace_id"):
            espacos.add(criado["workspace_id"])
        if row.external_id:
            externos.add(row.external_id)
        digitais.add(digital)
        contagem["imported"] += 1
        por_tipo[classe] += 1

    lote.imported_count = contagem["imported"]
    lote.ignored_count = contagem["ignored"]
    lote.duplicate_count = contagem["duplicate"]
    lote.skipped_count = contagem["skipped"]
    session.add(lote)
    session.flush()
    for espaco in espacos:
        publish_event(session, espaco, "transaction.bulk_created", "transaction", None, user_id)
    return {
        "batch_id": lote.id, "imported": contagem["imported"], "ignored": contagem["ignored"],
        "duplicate": contagem["duplicate"], "skipped": contagem["skipped"],
        "by_classification": dict(por_tipo), "problems": problemas,
    }


# --- Histórico e desfazer ----------------------------------------------------------------

def _lote_proprio(session: Session, user_id: int, batch_id: int) -> ImportBatch:
    lote = session.get(ImportBatch, batch_id)
    if lote is None or lote.kind != KIND_ACCOUNT or lote.created_by_user_id != user_id:
        raise HTTPException(status_code=404, detail="Importação não encontrada")
    return lote


def _vivas(session: Session, batch_ids: List[int]):
    return session.exec(
        _com_registros(select(ImportRow))
        .where(ImportRow.batch_id.in_(batch_ids), ImportRow.status == ImportRowStatus.imported, _vivo())
    ).all()


def _resumo(session: Session, lotes: List[ImportBatch]) -> List[dict]:
    if not lotes:
        return []
    vivas = _vivas(session, [lote.id for lote in lotes])
    por_lote: Dict[int, int] = Counter(r.batch_id for r in vivas)
    tx_do_lote: Dict[int, List[int]] = defaultdict(list)
    for r in vivas:
        if r.transaction_id:
            tx_do_lote[r.batch_id].append(r.transaction_id)
    todos = [t for ids in tx_do_lote.values() for t in ids]
    anexos_por_tx = dict(session.exec(
        select(Attachment.transaction_id, func.count()).where(Attachment.transaction_id.in_(todos))
        .group_by(Attachment.transaction_id)
    ).all()) if todos else {}
    nomes = dict(session.exec(
        select(PaymentAccount.id, PaymentAccount.name).where(PaymentAccount.id.in_({lote.account_id for lote in lotes}))
    ).all())
    return [{
        "id": lote.id, "account_id": lote.account_id, "account_name": nomes.get(lote.account_id, "?"),
        "filename": lote.filename, "created_at": lote.created_at, "total_rows": lote.total_rows,
        "imported": lote.imported_count, "ignored": lote.ignored_count, "duplicate": lote.duplicate_count,
        "skipped": lote.skipped_count, "live": por_lote.get(lote.id, 0),
        "attachments": sum(anexos_por_tx.get(t, 0) for t in tx_do_lote.get(lote.id, [])),
    } for lote in lotes]


def list_account_imports(session: Session, user_id: int, *, limit: int = 50) -> List[dict]:
    lotes = list(session.exec(
        select(ImportBatch).where(ImportBatch.kind == KIND_ACCOUNT, ImportBatch.created_by_user_id == user_id)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()).limit(limit)
    ).all())
    return _resumo(session, lotes)


def get_account_import(session: Session, user_id: int, batch_id: int) -> dict:
    lote = _lote_proprio(session, user_id, batch_id)
    vivas = {r.id for r in _vivas(session, [lote.id])}
    linhas = session.exec(
        select(ImportRow).where(ImportRow.batch_id == lote.id).order_by(ImportRow.line, ImportRow.id)
    ).all()
    return {
        **_resumo(session, [lote])[0],
        "rows": [{
            "line": r.line, "title": r.title, "amount": r.amount, "transaction_date": r.transaction_date,
            "direction": r.direction, "classification": r.classification, "status": r.status,
            "reason": r.reason, "external_id": r.external_id, "alive": r.id in vivas,
        } for r in linhas],
    }


def undo_account_import(
    session: Session, user_id: int, batch_id: int, *, confirm_attachments: bool = False,
) -> Tuple[dict, List[str]]:
    """Desfaz o extrato: exclui despesas e rendas, exclui transferências e
    estorna os pagamentos de fatura que ele criou e que ainda existem — cada um
    pelo comando da tela, com as regras dela. Tudo ou nada (ADR 0036/0037)."""
    from app.services.commands import accounts as acc_cmd
    from app.services.commands import income as income_cmd
    from app.services.commands import statements as stmt_cmd
    from app.services.commands import transactions as tx_cmd

    trava_usuario(session, user_id)
    lote = _lote_proprio(session, user_id, batch_id)
    vivas = _vivas(session, [lote.id])
    txs = [r for r in vivas if r.transaction_id]
    anexos = session.exec(
        select(func.count()).select_from(Attachment).where(Attachment.transaction_id.in_([r.transaction_id for r in txs]))
    ).one() if txs else 0
    if anexos and not confirm_attachments:
        raise HTTPException(
            status_code=409,
            detail=f"{anexos} recibo(s) anexado(s) a despesas desta importação seriam apagados para sempre. "
                   "Confirme para desfazer mesmo assim.",
        )
    desfeitos: Counter = Counter()
    removidos = 0
    liberar: List[str] = []
    espacos: Set[int] = set()
    for r in vivas:
        if r.transaction_id:
            tx = session.get(Transaction, r.transaction_id)
            membro = session.exec(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == tx.workspace_id, WorkspaceMembership.user_id == user_id,
                )
            ).first()
            if membro is None:
                espaco = session.get(Workspace, tx.workspace_id)
                raise HTTPException(
                    status_code=409,
                    detail=f"A despesa \"{tx.title}\" está no espaço {espaco.name if espaco else ''}, de que você não "
                           "participa mais. Nada foi desfeito.",
                )
            resultado, chaves = tx_cmd.delete_transaction(session, tx.workspace_id, tx.id, membro)
            removidos += resultado["attachments_removed"]
            liberar.extend(chaves)
            espacos.add(tx.workspace_id)
            desfeitos["expense"] += 1
        elif r.income_id:
            income_cmd.delete_income(session, user_id, r.income_id)
            desfeitos["income"] += 1
        elif r.transfer_id:
            acc_cmd.delete_transfer(session, user_id, r.transfer_id)
            desfeitos["transfer"] += 1
        elif r.statement_payment_id:
            stmt_cmd.estornar_pagamento(session, user_id, r.statement_payment_id)
            desfeitos["statement_payment"] += 1
    for espaco in espacos:
        publish_event(session, espaco, "transaction.bulk_updated", "transaction", None, user_id)
    session.flush()
    return {"batch_id": lote.id, "undone": dict(desfeitos), "attachments_removed": removidos}, liberar


__all__ = [
    "commit_account_statement", "get_account_import", "list_account_imports", "parse_account_statement",
    "undo_account_import",
]
