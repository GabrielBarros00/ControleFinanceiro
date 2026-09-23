"""Escrita de lançamentos: criar, editar, excluir e restaurar.

Todas chamam os MESMOS comandos da API REST (`services/commands/transactions.py`):
fatura derivada no servidor (ADR 0002), divisão em centavos (ADR 0001),
parcelamento, conversão de moeda estrangeira, máquina de estados (ADR 0003),
trava de despesa paga, vínculo de financiamento. A tool só traduz nomes em ids e
decide QUAL comando chamar — regra financeira nenhuma é reescrita aqui.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import func, select

from app.domain.dates import civil_instant, today_local
from app.mcp import resolve
from app.mcp.dates import CivilDate
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import TransactionBrief, TransactionOut
from app.mcp.serializers import load_bundle, one, to_brief
from app.mcp.tools.transactions import WIDGET, PaymentMethodIn, visible_transaction
from app.mcp.writes import DivisionIn, IdempotencyKey, build_division, membership_for_write
from app.models.attachment import Attachment
from app.models.transaction import (
    STATEMENT_SHIFT_MAX,
    STATEMENT_SHIFT_MIN,
    PaymentMethod,
    SplitMethod,
    SplitMode,
    Transaction,
    TransactionItem,
    TransactionSplit,
    TransactionStatus,
)
from app.schemas.common import DESCRIPTION_MAX, TITLE_MAX
from app.schemas.transaction import (
    TransactionCreate,
    TransactionItemCreate,
    TransactionItemShareBase,
    TransactionPayerBase,
    TransactionSplitBase,
    TransactionUpdate,
)
from app.services.attachment_storage import free_keys
from app.services.commands import transactions as tx_cmd
from app.services.oauth import scopes as escopos

CurrencyIn = Optional[str]
_MOEDA = Field(
    None, pattern=r"^[A-Za-z]{3}$",
    description="Moeda ISO 4217 da compra (ex.: USD). Estrangeira é convertida para a moeda do espaço na data (PTAX; IOF no cartão).",
)


# --- Saídas --------------------------------------------------------------------

class WriteResult(BaseModel):
    transaction: TransactionOut
    installments: List[TransactionBrief] = Field(
        default_factory=list, description="Todas as parcelas, quando a compra é parcelada."
    )
    replayed: bool = Field(False, description="true = esta chave já tinha sido processada; nada novo foi criado.")


def _parcelas(call: ToolCall, tx: Transaction) -> List[TransactionBrief]:
    if not tx.installment_group_id:
        return []
    irmas = call.session.exec(
        select(Transaction)
        .where(
            Transaction.workspace_id == tx.workspace_id,
            Transaction.installment_group_id == tx.installment_group_id,
            Transaction.deleted_at.is_(None),
        )
        .order_by(Transaction.installment_no, Transaction.id)
    ).all()
    pacote = load_bundle(call.session, irmas)
    return [to_brief(t, pacote, call.identity.user_id) for t in irmas]


def _frase(saida: TransactionOut, parcelas: List[TransactionBrief]) -> str:
    partes = [f"{saida.title}: {fmt_brl(saida.amount, saida.currency)} em {saida.date.strftime('%d/%m/%Y')} ({saida.space.name})"]
    if saida.card:
        fatura = f", fatura {saida.statement.month}" if saida.statement else ""
        partes.append(f"no cartão {saida.card.name}{fatura}")
    if parcelas:
        partes.append(f"parcelado em {len(parcelas)}x")
    divisao = ", ".join(f"{p.person.name} {fmt_brl(p.amount, saida.currency)}" for p in saida.split)
    if len(saida.split) > 1:
        partes.append(f"divisão: {divisao}")
    partes.append(f"sua parte: {fmt_brl(saida.my_share, saida.currency)}")
    return "; ".join(partes) + "."


def _saida(call: ToolCall, tx: Transaction, *, replayed: bool = False) -> WriteResult:
    return WriteResult(
        transaction=one(call.session, tx, call.identity.user_id),
        installments=_parcelas(call, tx),
        replayed=replayed,
    )


# --- transactions_create ---------------------------------------------------------

class _CreateCore(ToolInput):
    idempotency_key: IdempotencyKey
    title: str = Field(min_length=1, max_length=TITLE_MAX, description="Descrição curta, como aparece na lista (ex.: \"Gasolina\").")
    amount: MoneyIn = Field(description="Valor TOTAL da compra (nas parceladas, o total, não a parcela).")
    date: Optional[CivilDate] = Field(None, description="Dia da compra. Omitido = hoje (profile_get.today).")
    space: Optional[str] = Field(None, max_length=120, description="Espaço onde lançar. Omitido = regra do espaço implícito (ver descrição).")
    space_id: Optional[int] = None
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX, description="Observação livre.")
    currency: CurrencyIn = _MOEDA
    category: Optional[str] = Field(None, max_length=120, description="Nome de uma categoria EXISTENTE do espaço.")
    category_id: Optional[int] = None
    tags: Optional[List[str]] = Field(None, max_length=10, description="Nomes de tags EXISTENTES do espaço.")
    card: Optional[str] = Field(None, max_length=120, description="Cartão de crédito seu (nome). Define pagamento no crédito.")
    card_id: Optional[int] = None
    installments: Optional[int] = Field(None, ge=2, le=36, description="Número de parcelas (exige cartão).")
    statement_shift: Optional[int] = Field(
        None, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX,
        description="Raro: o emissor lançou a compra noutra fatura (+1 = próxima). Só com cartão.",
    )
    payment_method: Optional[PaymentMethodIn] = Field(None, description="Forma de pagamento fora do cartão (pix, debit_card, cash…).")
    settled: Optional[bool] = Field(
        None,
        description="Já foi paga? Omitido = o app decide pela data (passado = pago; futuro = a pagar). Não se aplica a cartão.",
    )


class CreateIn(DivisionIn, _CreateCore):
    """Campos da compra primeiro; quem pagou e a divisão no fim (herdados de `DivisionIn`)."""

    @model_validator(mode="after")
    def _pares(self):
        for a, b in (("space", "space_id"), ("category", "category_id"), ("card", "card_id")):
            if getattr(self, a) is not None and getattr(self, b) is not None:
                raise ValueError(f"informe {a} ou {b}, não os dois")
        if self.installments and self.card is None and self.card_id is None:
            raise ValueError("parcelamento exige o cartão (card ou card_id)")
        return self


def _espaco_para_criar(call: ToolCall, a: CreateIn) -> resolve.SpaceRef:
    me = call.identity.user_id
    ref = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    if ref is not None:
        return ref
    nomes, ids = a.people_named()
    return resolve.choose_space_for_people(call.session, me, nomes, ids)


def _replay_create(call: ToolCall, ref: dict) -> ToolOutput:
    tx = visible_transaction(call, int(ref["transaction_id"]), include_deleted=True)
    saida = _saida(call, tx, replayed=True)
    return ToolOutput(
        structured=saida,
        summary="Esta operação já tinha sido feita (mesma idempotency_key); nada novo foi criado. " + _frase(saida.transaction, saida.installments),
        entity_type="transaction",
        entity_ids=[tx.id],
        space_id=tx.workspace_id,
        widget={"view": "transaction", "app_url": saida.transaction.app_url},
    )


@tool(
    name="transactions_create",
    title="Registrar despesa",
    description=(
        "Registra uma despesa (compra, conta, gasto) numa única chamada atômica: valor, data, "
        "categoria, tags, cartão e parcelas, quem pagou, divisão com outras pessoas, conta de "
        "origem, moeda estrangeira e se já foi paga. O servidor calcula a fatura, as parcelas e "
        "os centavos da divisão — não calcule nada disso.\n"
        "Use quando: o usuário disser que comprou/gastou/pagou algo (\"adicione R$ 89,90 de "
        "gasolina no Nubank\", \"comprei uma TV de R$ 3.000 em 10x\", \"jantar de 120, metade do João\").\n"
        "Não use quando: for renda (income_create), transferência entre contas (transfers_create), "
        "pagamento de fatura (statements_pay) ou acerto de dívida entre pessoas (settlements_create); "
        "nem para corrigir um lançamento existente (transactions_update).\n"
        "Espaço: informe `space` quando o usuário disser. Omitido, vale o ÚNICO espaço que tem todas "
        "as pessoas citadas (sem ninguém citado: seu espaço pessoal); se houver dúvida volta AMBIGUOUS — "
        "pergunte ao usuário. Nomes (cartão, categoria, pessoa) ambíguos também voltam AMBIGUOUS com "
        "candidatos; repita a chamada com o `*_id` escolhido e a MESMA idempotency_key.\n"
        "Divisão: `split_with` = partes iguais entre você e as pessoas; `split` = partes desiguais "
        "(valor ou percentual de cada um). Sem divisão, a despesa é toda sua.\n"
        "Gere uma idempotency_key nova para cada despesa e reutilize-a só ao repetir a mesma chamada."
    ),
    input_model=CreateIn,
    output_model=WriteResult,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_create,
    ui=WIDGET,
    invoking="Registrando a despesa…",
    invoked="Despesa registrada",
    examples=(
        {"title": "Gasolina", "amount": "89.90", "card": "Nubank", "category": "Transporte", "idempotency_key": "b3f1c2d4-0001"},
        {"title": "TV", "amount": "3000.00", "card": "Nubank", "installments": 10, "idempotency_key": "b3f1c2d4-0002"},
        {"title": "Jantar", "amount": "120.00", "split_with": ["João"], "payment_method": "pix", "idempotency_key": "b3f1c2d4-0003"},
    ),
)
def transactions_create(call: ToolCall) -> ToolOutput:
    a: CreateIn = call.args
    me = call.identity.user_id
    ref = _espaco_para_criar(call, a)
    membership = membership_for_write(call, ref.id)

    cartao = resolve.resolve_card(call.session, me, card_id=a.card_id, card=a.card)
    categoria = resolve.resolve_category(call.session, ref.id, category_id=a.category_id, category=a.category)
    tag_ids = resolve.resolve_tags(call.session, ref.id, a.tags)
    divisao = build_division(call.session, ref.id, me, a, a.amount)

    metodo = PaymentMethod(a.payment_method) if a.payment_method else None
    if cartao is not None:
        metodo = PaymentMethod.credit_card
    itens = None
    if categoria is not None:
        itens = [TransactionItemCreate(title=a.title, amount=a.amount, category_id=categoria.id)]

    entrada = TransactionCreate(
        title=a.title,
        description=a.description,
        total_amount=a.amount,
        currency=a.currency.upper() if a.currency else None,
        transaction_date=civil_instant(a.date or today_local()),
        status=TransactionStatus.confirmed,
        credit_card_id=cartao.id if cartao else None,
        statement_shift=a.statement_shift or 0,
        split_mode=SplitMode.transaction,
        payment_method=metodo,
        payers=divisao.payers,
        splits=divisao.splits,
        items=itens,
        tag_ids=tag_ids,
        installments_count=a.installments,
        settled=a.settled,
    )
    tx = tx_cmd.create_transaction(call.session, ref.id, entrada, membership)
    call.session.flush()
    saida = _saida(call, tx)
    return ToolOutput(
        structured=saida,
        summary="Despesa registrada. " + _frase(saida.transaction, saida.installments),
        entity_type="transaction",
        entity_ids=[tx.id] + [p.id for p in saida.installments if p.id != tx.id],
        space_id=ref.id,
        result_ref={"transaction_id": tx.id, "space_id": ref.id},
        widget={"view": "transaction", "app_url": saida.transaction.app_url},
    )


# --- transactions_update ---------------------------------------------------------

class _UpdateCore(ToolInput):
    transaction_id: int
    scope: Literal["installment", "purchase"] = Field(
        "installment",
        description=(
            "Só para compra parcelada: `installment` muda só esta parcela; `purchase` muda a compra "
            "inteira (total, nº de parcelas, divisão, categoria), recalculando as parcelas em aberto."
        ),
    )
    title: Optional[str] = Field(None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX, description="Texto novo; \"\" apaga a observação.")
    amount: Optional[MoneyIn] = Field(
        None,
        description=(
            "Novo valor total, na moeda DA COMPRA: a de `currency`, se informada; senão a original "
            "(`foreign.original_currency`) quando o lançamento foi convertido."
        ),
    )
    currency: CurrencyIn = _MOEDA
    date: Optional[CivilDate] = None
    category: Optional[str] = Field(None, max_length=120, description="Nova categoria (existente no espaço).")
    category_id: Optional[int] = None
    remove_category: bool = Field(False, description="true = deixa o lançamento sem categoria.")
    tags: Optional[List[str]] = Field(None, max_length=10, description="Substitui TODAS as tags ([] remove todas).")
    card: Optional[str] = Field(None, max_length=120, description="Passa a compra para este cartão seu.")
    card_id: Optional[int] = None
    payment_method: Optional[PaymentMethodIn] = Field(None, description="Nova forma de pagamento (fora do cartão remove o cartão).")
    statement_shift: Optional[int] = Field(None, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX)
    installments: Optional[int] = Field(None, ge=2, le=36, description="Novo nº de parcelas (só com scope=purchase).")
    settled: Optional[bool] = Field(None, description="true = já paguei; false = ainda a pagar. Compra no cartão se paga pela fatura.")
    status: Optional[Literal["confirmed", "cancelled"]] = Field(
        None,
        description="`cancelled` = cancelar (definitivo: deixa de contar, continua visível); `confirmed` = reabrir despesa marcada como paga.",
    )


class UpdateIn(DivisionIn, _UpdateCore):
    @model_validator(mode="after")
    def _coerencia(self):
        for a, b in (("category", "category_id"), ("card", "card_id")):
            if getattr(self, a) is not None and getattr(self, b) is not None:
                raise ValueError(f"informe {a} ou {b}, não os dois")
        if self.remove_category and (self.category is not None or self.category_id is not None):
            raise ValueError("remove_category não combina com category/category_id")
        if self.installments is not None and self.scope != "purchase":
            raise ValueError("installments só com scope=purchase")
        campos = self.model_dump(exclude_unset=True, exclude={"transaction_id", "scope"})
        if not campos or campos == {"remove_category": False}:
            raise ValueError("nada para alterar: informe ao menos um campo")
        return self


class UpdateResult(BaseModel):
    transaction: TransactionOut
    previous: TransactionOut = Field(description="Como o lançamento estava ANTES da alteração.")
    changed: List[str] = Field(description="Campos que mudaram de fato.")
    installments: List[TransactionBrief] = Field(default_factory=list)


_COMPARAVEIS = ("title", "description", "date", "billing_month", "amount", "currency", "status", "settled",
                "payment_method", "card", "statement", "category", "categories", "tags", "payers", "split")


def _mudancas(antes: TransactionOut, depois: TransactionOut) -> List[str]:
    a = antes.model_dump(mode="json", include=set(_COMPARAVEIS))
    d = depois.model_dump(mode="json", include=set(_COMPARAVEIS))
    return [k for k in _COMPARAVEIS if a.get(k) != d.get(k)]


def _itens_atuais(call: ToolCall, tx: Transaction) -> List[TransactionItem]:
    return list(call.session.exec(
        select(TransactionItem).where(TransactionItem.transaction_id == tx.id).order_by(TransactionItem.position)
    ).all())


def _recusa_divisao_complexa(call: ToolCall, tx: Transaction) -> None:
    if tx.split_mode == SplitMode.item:
        raise McpToolError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "Esta despesa é dividida por itens e esta mudança refaz a divisão (valor, divisão, moeda; "
            "numa compra em moeda estrangeira, também data e forma de pagamento): edite-a no app.",
            details={"app_url": one(call.session, tx, call.identity.user_id).app_url},
        )
    if tx.adjustments or len(_itens_atuais(call, tx)) > 1:
        raise McpToolError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "Esta despesa tem itens ou ajustes detalhados e esta mudança refaz a divisão (valor, divisão, "
            "moeda; numa compra em moeda estrangeira, também data e forma de pagamento): edite-a no app.",
            details={"app_url": one(call.session, tx, call.identity.user_id).app_url},
        )


def _divisao_existente(call: ToolCall, tx: Transaction, total: Decimal, *, mantem_fixos: bool):
    """Mantém quem pagou e a divisão, trocando só o total (valor muda, estrutura fica)."""
    pacote = load_bundle(call.session, [tx])
    pagadores = pacote.payers.get(tx.id, [])
    if len(pagadores) != 1:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            "Esta despesa tem vários pagadores: informe também `paid_by` e a divisão.",
        )
    p = pagadores[0]
    splits = []
    for s in pacote.splits.get(tx.id, []):
        if s.split_method == SplitMethod.fixed and not mantem_fixos:
            raise McpToolError(
                ErrorCode.VALIDATION_ERROR,
                "A divisão atual é por valores fixos e não fecha com esta mudança: informe a nova "
                "divisão em `split` na mesma chamada.",
            )
        splits.append(TransactionSplitBase(user_id=s.user_id, split_method=s.split_method, input_value=s.input_value))
    pagador = TransactionPayerBase(user_id=p.user_id, amount=total, payment_method=p.payment_method, account_id=p.account_id)
    return [pagador], splits


def _update_single(call: ToolCall, tx: Transaction, a: UpdateIn, membership) -> Transaction:
    me = call.identity.user_id
    ws = tx.workspace_id
    dados: dict = {}
    if a.title is not None:
        dados["title"] = a.title
    if a.description is not None:
        dados["description"] = a.description or None
    if a.date is not None:
        dados["transaction_date"] = civil_instant(a.date)
    if a.status is not None:
        dados["status"] = TransactionStatus(a.status)
    if a.settled is not None:
        dados["settled"] = a.settled
    if a.statement_shift is not None:
        dados["statement_shift"] = a.statement_shift
    if a.tags is not None:
        dados["tag_ids"] = resolve.resolve_tags(call.session, ws, a.tags) or []
    cartao = resolve.resolve_card(call.session, me, card_id=a.card_id, card=a.card)
    if cartao is not None:
        dados["credit_card_id"] = cartao.id
        dados["payment_method"] = PaymentMethod.credit_card
    elif a.payment_method is not None:
        dados["payment_method"] = PaymentMethod(a.payment_method)
        if a.payment_method != "credit_card":
            dados["credit_card_id"] = None
    # Moeda igual à da compra (a original, se já foi convertida) não muda nada.
    moeda_da_compra = tx.original_currency or tx.currency
    nova_moeda = a.currency.upper() if a.currency is not None else None
    if nova_moeda == moeda_da_compra:
        nova_moeda = None

    categoria_id = None
    mexe_categoria = a.remove_category or a.category is not None or a.category_id is not None
    if not a.remove_category and (a.category is not None or a.category_id is not None):
        categoria_id = resolve.resolve_category(call.session, ws, category_id=a.category_id, category=a.category).id

    # Valor na moeda DA COMPRA, como na criação: num lançamento convertido de
    # US$ 50 (R$ 250), `amount: 60` são US$ 60 — e trocar só a moeda mantém o
    # número ("aquilo foi 50 dólares, não 50 reais").
    estrangeira = tx.original_currency is not None
    total_da_compra = tx.original_amount if estrangeira else tx.total_amount
    novo_total = a.amount if a.amount is not None else total_da_compra
    precisa_divisao = a.mentions_division()
    if a.amount is not None and a.amount != total_da_compra and not precisa_divisao:
        # O caminho parcial do app só reescala 1 pagador × 1 parte; com mais
        # gente a divisão é refeita pela edição completa, mesma estrutura.
        n_partes = call.session.exec(
            select(func.count()).select_from(TransactionSplit).where(TransactionSplit.transaction_id == tx.id)
        ).one()
        precisa_divisao = n_partes > 1
    # O caminho parcial do comando não converte nada (o SPA sempre manda a
    # edição completa numa compra em moeda estrangeira): gravaria `currency` sem
    # converter, trataria `amount` como moeda-base apagando o original, e
    # manteria a cotação e o IOF antigos ao mudar a data ou o cartão. Tudo isso
    # vai pela edição completa, que reconverte (PTAX na data; IOF no cartão) —
    # o mesmo que acontece quando a pessoa edita a compra no app.
    muda_pagamento = cartao is not None or a.payment_method is not None
    if nova_moeda is not None or (
        estrangeira and (a.amount is not None or a.date is not None or muda_pagamento)
    ):
        precisa_divisao = True
    if a.amount is not None:
        dados["total_amount"] = a.amount

    muda_conta = a.account is not None or a.account_id is not None
    if precisa_divisao or muda_conta:
        _recusa_divisao_complexa(call, tx)
        if nova_moeda is not None or estrangeira:
            dados["currency"] = nova_moeda or moeda_da_compra
            dados["total_amount"] = novo_total
        if a.mentions_division():
            divisao = build_division(call.session, ws, me, a, novo_total)
            pagadores, partes = divisao.payers, divisao.splits
        else:
            # Divisão por valores fixos só sobrevive se o total e a moeda não mudam.
            mantem_fixos = not estrangeira and nova_moeda is None and novo_total == tx.total_amount
            pagadores, partes = _divisao_existente(call, tx, novo_total, mantem_fixos=mantem_fixos)
            if muda_pagamento:
                # A forma de pagamento do pagador acompanha a nova (sem método,
                # ele herda a do lançamento); conta não existe no cartão.
                pagadores[0] = pagadores[0].model_copy(update={
                    "payment_method": None,
                    "account_id": None if dados.get("credit_card_id") else pagadores[0].account_id,
                })
            if muda_conta:
                if pagadores[0].user_id != me:
                    raise McpToolError(
                        ErrorCode.VALIDATION_ERROR,
                        "A conta só pode ser informada quando foi você quem pagou — a conta de outra pessoa é dela.",
                    )
                conta = resolve.resolve_account(call.session, me, account_id=a.account_id, account=a.account)
                pagadores[0] = pagadores[0].model_copy(update={"account_id": conta.id})
        itens_atuais = _itens_atuais(call, tx)
        cat_final = categoria_id if mexe_categoria else (itens_atuais[0].category_id if itens_atuais else None)
        dados["split_mode"] = SplitMode.transaction
        dados["payers"] = pagadores
        dados["splits"] = partes
        dados["items"] = (
            [TransactionItemCreate(title=dados.get("title", tx.title), amount=novo_total, category_id=cat_final)]
            if cat_final is not None else None
        )
        if dados["items"] is None:
            dados.pop("items")
    elif mexe_categoria:
        dados["category_id"] = categoria_id

    entrada = TransactionUpdate(**dados)
    return tx_cmd.update_transaction(call.session, ws, tx.id, entrada, membership)


def _update_purchase(call: ToolCall, tx: Transaction, a: UpdateIn, membership) -> Transaction:
    """Compra parcelada inteira: parte da definição que o app reconstrói e aplica as mudanças."""
    me = call.identity.user_id
    ws = tx.workspace_id
    if not tx.installment_group_id:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Este lançamento não é parcelado; use scope=installment.")
    if a.status is not None or a.settled is not None:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            "status/settled valem por parcela: use scope=installment em cada parcela.",
        )
    irmas = tx_cmd._load_group_siblings(call.session, ws, tx)
    total_grupo = sum((t.total_amount for t in irmas), Decimal("0"))
    inteira = tx_cmd._aggregate_group_whole(irmas, tx_cmd._strip_installment_suffix(tx.title), total_grupo)
    if inteira["split_mode"] == SplitMode.item and (a.amount is not None or a.mentions_division()):
        raise McpToolError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "Esta compra é dividida por itens; para mudar valor ou divisão, edite-a no app.",
        )

    total = a.amount if a.amount is not None else Decimal(inteira["total_amount"])
    pagadores = [TransactionPayerBase(**{k: p[k] for k in ("user_id", "payment_method", "account_id")}, amount=total)
                 for p in inteira["payers"]]
    partes = [TransactionSplitBase(user_id=s["user_id"], split_method=s["split_method"], input_value=Decimal(s["input_value"]))
              for s in inteira["splits"]]
    if a.mentions_division():
        divisao = build_division(call.session, ws, me, a, total)
        pagadores, partes = divisao.payers, divisao.splits
    elif a.amount is not None and any(p.split_method == SplitMethod.fixed for p in partes):
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            "A divisão atual é por valores fixos: ao mudar o total, informe a nova divisão em `split`.",
        )

    itens = []
    for it in inteira["items"]:
        itens.append(TransactionItemCreate(
            title=it["title"], amount=Decimal(it["amount"]) if a.amount is None else total,
            quantity=Decimal("1"), position=it["position"], category_id=it["category_id"],
            shares=[TransactionItemShareBase(user_id=s["user_id"], split_method=s["split_method"], input_value=Decimal(s["input_value"]))
                    for s in it.get("shares") or []] or None,
        ))
    if a.remove_category or a.category is not None or a.category_id is not None:
        nova = None if a.remove_category else resolve.resolve_category(
            call.session, ws, category_id=a.category_id, category=a.category
        ).id
        if inteira["split_mode"] == SplitMode.item:
            raise McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, "Compra dividida por itens: mude a categoria no app.")
        itens = [TransactionItemCreate(title=a.title or inteira["title"], amount=total, category_id=nova)] if nova else []

    cartao = resolve.resolve_card(call.session, me, card_id=a.card_id, card=a.card)
    tags = resolve.resolve_tags(call.session, ws, a.tags) if a.tags is not None else [t["id"] for t in inteira["tags"]]
    ref_tx = min(irmas, key=lambda t: t.installment_no or 0)
    entrada = TransactionCreate(
        title=a.title or inteira["title"],
        description=(a.description or None) if a.description is not None else inteira["description"],
        total_amount=total,
        currency=(a.currency.upper() if a.currency else inteira["currency"]),
        transaction_date=civil_instant(a.date) if a.date is not None else inteira["transaction_date"],
        status=TransactionStatus.confirmed,
        credit_card_id=cartao.id if cartao else inteira["credit_card_id"],
        statement_shift=a.statement_shift if a.statement_shift is not None else ref_tx.statement_shift,
        split_mode=inteira["split_mode"],
        payment_method=PaymentMethod.credit_card,
        payers=pagadores,
        splits=partes if inteira["split_mode"] == SplitMode.transaction else [],
        items=itens or None,
        tag_ids=tags,
        installments_count=a.installments or inteira["installments_of"],
    )
    return tx_cmd.update_installment_group(call.session, ws, tx.id, entrada, membership)


@tool(
    name="transactions_update",
    title="Editar lançamento",
    description=(
        "Altera um lançamento existente: título, observação, valor, data, categoria, tags, cartão, "
        "forma de pagamento, quem pagou, divisão, moeda (o valor é convertido na data, com IOF no "
        "cartão), \"já paguei\" (settled) ou cancelamento. Só os campos informados mudam. Devolve "
        "como estava ANTES (`previous`) e o que mudou (`changed`).\n"
        "Use quando: o usuário pedir para corrigir ou completar um lançamento (\"troque a categoria "
        "daquela compra para Alimentação\", \"metade dessa compra é do João\", \"marque como paga\").\n"
        "Não use quando: ainda não tiver o `transaction_id` (busque com transactions_search); para "
        "categorizar muitos de uma vez (transactions_bulk_preview); para excluir (transactions_delete).\n"
        "Parcelada: `scope=installment` (padrão) muda só a parcela; `scope=purchase` muda a compra "
        "inteira (total, nº de parcelas, divisão, categoria) — pergunte ao usuário se não estiver claro.\n"
        "Despesa paga não muda até ser reaberta (`status=confirmed`); cancelada é definitiva."
    ),
    input_model=UpdateIn,
    output_model=UpdateResult,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    ui=WIDGET,
    invoking="Atualizando o lançamento…",
    invoked="Lançamento atualizado",
    examples=(
        {"transaction_id": 123, "category": "Alimentação"},
        {"transaction_id": 123, "split_with": ["João"]},
        {"transaction_id": 123, "settled": True},
        {"transaction_id": 456, "scope": "purchase", "amount": "2800.00"},
    ),
)
def transactions_update(call: ToolCall) -> ToolOutput:
    a: UpdateIn = call.args
    me = call.identity.user_id
    tx = visible_transaction(call, a.transaction_id)
    membership = membership_for_write(call, tx.workspace_id)
    antes = one(call.session, tx, me)
    if a.scope == "purchase":
        atualizado = _update_purchase(call, tx, a, membership)
    else:
        atualizado = _update_single(call, tx, a, membership)
    call.session.flush()
    call.session.expire_all()
    novo = call.session.get(Transaction, atualizado.id)
    depois = one(call.session, novo, me)
    mudou = _mudancas(antes, depois)
    saida = UpdateResult(transaction=depois, previous=antes, changed=mudou, installments=_parcelas(call, novo))
    resumo = (
        f"Atualizado ({', '.join(mudou)}). " if mudou else "Nada mudou (os valores já eram esses). "
    ) + _frase(depois, saida.installments)
    return ToolOutput(
        structured=saida,
        summary=resumo,
        entity_type="transaction",
        entity_ids=[novo.id],
        space_id=novo.workspace_id,
        widget={"view": "transaction", "app_url": depois.app_url},
    )


# --- transactions_delete / transactions_restore ------------------------------------

class DeleteIn(ToolInput):
    transaction_id: int
    scope: Literal["installment", "purchase"] = Field(
        "installment",
        description="Parcelada: `installment` exclui só esta parcela; `purchase` exclui todas as parcelas em aberto da compra.",
    )


class DeleteResult(BaseModel):
    deleted: List[TransactionBrief] = Field(description="O que foi excluído (dá para restaurar com transactions_restore).")
    skipped_paid: int = Field(0, description="Parcelas pagas preservadas (compra inteira).")
    restorable: bool = True


def _anexos(call: ToolCall, ids: list[int]) -> int:
    if not ids:
        return 0
    return int(call.session.exec(
        select(func.count()).select_from(Attachment).where(Attachment.transaction_id.in_(ids))
    ).one())


@tool(
    name="transactions_delete",
    title="Excluir lançamento",
    description=(
        "Exclui um lançamento (ou, com `scope=purchase`, todas as parcelas em aberto de uma compra "
        "parcelada). A exclusão pode ser desfeita com transactions_restore. Despesa paga não é "
        "excluída — reabra antes.\n"
        "Use quando: o usuário pedir para apagar um lançamento específico que você já identificou "
        "(mostre qual é antes: título, data, valor).\n"
        "Não use quando: forem vários lançamentos (use transactions_bulk_preview + "
        "transactions_bulk_delete) ou houver dúvida sobre qual lançamento é — pergunte.\n"
        "Se o lançamento tiver anexos (recibos), eles seriam apagados para sempre: a tool recusa e "
        "pede o fluxo com prévia (transactions_bulk_preview com action=delete), que mostra isso ao usuário."
    ),
    input_model=DeleteIn,
    output_model=DeleteResult,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Excluindo…",
    invoked="Excluído",
    examples=({"transaction_id": 123}, {"transaction_id": 456, "scope": "purchase"}),
)
def transactions_delete(call: ToolCall) -> ToolOutput:
    a: DeleteIn = call.args
    me = call.identity.user_id
    tx = visible_transaction(call, a.transaction_id)
    membership = membership_for_write(call, tx.workspace_id)
    if a.scope == "purchase" and not tx.installment_group_id:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Este lançamento não é parcelado; use scope=installment.")
    alvos = tx_cmd._load_group_siblings(call.session, tx.workspace_id, tx) if a.scope == "purchase" else [tx]
    anexos = _anexos(call, [t.id for t in alvos if t.status != TransactionStatus.paid])
    if anexos:
        raise McpToolError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            f"Há {anexos} anexo(s) (recibos) que seriam apagados para sempre — a exclusão se desfaz, os "
            "anexos não. Use transactions_bulk_preview (action=delete) para mostrar isso ao usuário e "
            "confirme com transactions_bulk_delete.",
            details={"attachments": anexos, "next_tool": "transactions_bulk_preview"},
        )
    pacote = load_bundle(call.session, alvos)
    resumo_alvos = {t.id: to_brief(t, pacote, me) for t in alvos}
    if a.scope == "purchase":
        resultado, liberar = tx_cmd.delete_installment_group(call.session, tx.workspace_id, tx.id, membership)
        excluidos = [resumo_alvos[t.id] for t in alvos if t.status != TransactionStatus.paid]
        pulados = int(resultado.get("skipped_paid", 0))
    else:
        _, liberar = tx_cmd.delete_transaction(call.session, tx.workspace_id, tx.id, membership)
        excluidos = [resumo_alvos[tx.id]]
        pulados = 0
    saida = DeleteResult(deleted=excluidos, skipped_paid=pulados)
    total = sum((b.amount for b in excluidos), Decimal("0"))
    resumo = f"Excluído: {len(excluidos)} lançamento(s), {fmt_brl(total, tx.currency)}"
    if pulados:
        resumo += f"; {pulados} parcela(s) paga(s) preservada(s)"
    return ToolOutput(
        structured=saida,
        summary=resumo + ". Dá para desfazer com transactions_restore.",
        entity_type="transaction",
        entity_ids=[b.id for b in excluidos],
        space_id=tx.workspace_id,
        after_commit=[lambda: free_keys(liberar)] if liberar else [],
    )


class RestoreIn(ToolInput):
    transaction_id: int


@tool(
    name="transactions_restore",
    title="Restaurar lançamento excluído",
    description=(
        "Desfaz a exclusão de um lançamento (volta a contar em tudo). Anexos apagados não voltam.\n"
        "Use quando: o usuário pedir para desfazer uma exclusão recente, com o id devolvido por "
        "transactions_delete ou transactions_bulk_delete.\n"
        "Não use quando: o lançamento não foi excluído (nada acontece) ou para cancelar/reabrir "
        "(transactions_update)."
    ),
    input_model=RestoreIn,
    output_model=WriteResult,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    ui=WIDGET,
    invoking="Restaurando…",
    invoked="Restaurado",
    examples=({"transaction_id": 123},),
)
def transactions_restore(call: ToolCall) -> ToolOutput:
    a: RestoreIn = call.args
    tx = visible_transaction(call, a.transaction_id, include_deleted=True)
    membership = membership_for_write(call, tx.workspace_id)
    tx_cmd.restore_transaction(call.session, tx.workspace_id, tx.id, membership)
    call.session.flush()
    call.session.refresh(tx)
    saida = _saida(call, tx)
    return ToolOutput(
        structured=saida,
        summary="Restaurado. " + _frase(saida.transaction, saida.installments),
        entity_type="transaction",
        entity_ids=[tx.id],
        space_id=tx.workspace_id,
        widget={"view": "transaction", "app_url": saida.transaction.app_url},
    )

