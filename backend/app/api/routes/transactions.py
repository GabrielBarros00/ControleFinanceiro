from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from typing import Dict, List, Optional
from decimal import Decimal, ROUND_HALF_UP
import math
import datetime
import re
import uuid

from app.schemas.common import DeleteResult, StatusRead
from app.db.session import get_session
from app.domain.access_policy import (
    assert_can_write,
    can_write,
    get_visible_transaction,
    scope_transactions,
)
from app.domain.dates import add_months, month_key_local
from app.domain.settlement import resolve_settled_at
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionItem,
    TransactionStatus,
    SplitMethod,
    SplitMode,
    PaymentMethod,
)
from app.schemas.transaction import (
    BulkCreateResult,
    BulkCategorizeRequest,
    BulkCategorizeResult,
    BulkDeleteResult,
    InstallmentGroupCancelResult,
    InstallmentGroupRead,
    TransactionCreate,
    TransactionItemCreate,
    TransactionItemShareBase,
    TransactionPreviewRead,
    TransactionRead,
    TransactionSplitBase,
    TransactionUpdate,
    TransactionListResponse,
    normalize_payment_method,
    validate_payer_origins,
    validate_split_structure,
    validate_statement_shift,
)
from app.api.deps import get_workspace_membership, require_role
from app.core.config import settings
from app.domain.money import Money
from app.domain.query_policy import (
    REALIZED_STATUSES,
    resolve_currency,
    workspace_base_currency,
)
from app.models.attachment import Attachment
from app.models.tag import Tag, TransactionTagLink
from app.services.attachment_storage import free_keys, keys_to_free
from app.services.base_conversion import (
    apply_statement_leg,
    compute_base_conversion,
    compute_statement_conversion,
)
from app.services.event_service import publish_event
from app.services.transaction_service import (
    _allocate_proportional,
    _cents,
    compute_transaction_breakdown,
    convert_division_to_base,
    delete_transaction_children,
    persist_transaction_children,
    validate_status_transition,
)
from app.services.credit_card_service import CreditCardService, StatementStateError
from app.services.recurring_service import RecurringMaterializationService
from app.models.credit_card import CreditCard

router = APIRouter(prefix="/workspaces/{workspace_id}/transactions", tags=["transactions"])


def _tambem_sem_barra(metodo: str, **kwargs):
    """Registra a coleção também SEM a barra final, fora do schema.

    O redirecionamento automático do Starlette responde 307, e nesse salto o
    **cookie de sessão não acompanha**: `POST .../{caminho}` (sem barra) chegava
    como 401 em vez de funcionar. É a mesma armadilha que `me_accounts`,
    `me_cards`, `me_financing`, `me_income` e `admin` já eliminaram com o
    `_colecao` deles — estas duas coleções, que são as mais usadas do app,
    tinham ficado de fora.

    Aqui o canônico é a forma COM barra (ao contrário do `_colecao`), e a nova
    entra com `include_in_schema=False`: é a que o `openapi.json` já documenta e
    contra a qual o frontend foi escrito, então manter o schema intacto evita
    regerar `api.gen.ts` por uma correção que não muda contrato nenhum.
    """
    def decorador(func):
        getattr(router, metodo)("", include_in_schema=False, **kwargs)(func)
        return func
    return decorador

# Campos do TransactionUpdate que disparam a edição COMPLETA da divisão
FULL_EDIT_KEYS = {"payers", "splits", "items", "split_mode", "adjustments"}


def _set_transaction_tags(
    session: Session, workspace_id: int, transaction_id: int, tag_ids: List[int]
) -> None:
    """Substitui os vínculos de tag da transação (valida workspace)."""
    unique_ids = list(dict.fromkeys(tag_ids))
    tags = []
    if unique_ids:
        tags = session.exec(
            select(Tag).where(
                Tag.id.in_(unique_ids),
                Tag.workspace_id == workspace_id,
                Tag.deleted_at.is_(None),
            )
        ).all()
        if len(tags) != len(unique_ids):
            raise HTTPException(status_code=400, detail="Tag inválida para este workspace")

    for link in session.exec(
        select(TransactionTagLink).where(TransactionTagLink.transaction_id == transaction_id)
    ).all():
        session.delete(link)
    for tag in tags:
        session.add(TransactionTagLink(transaction_id=transaction_id, tag_id=tag.id))


def _ensure_not_paid(db_transaction: Transaction, update_keys: Optional[set] = None):
    """Despesa paga é imutável até ser reaberta (PUT contendo apenas status)."""
    if db_transaction.status != TransactionStatus.paid:
        return
    if update_keys is not None and not (update_keys - {"status"}):
        return  # reabertura: só muda o status
    raise HTTPException(
        status_code=409,
        detail="Despesa paga não pode ser alterada: reabra antes (altere apenas o status)",
    )


def _ensure_not_cancelled(db_transaction: Transaction):
    """Cancelada é terminal (ADR 0003): nenhuma edição, nenhuma transição."""
    if db_transaction.status == TransactionStatus.cancelled:
        raise HTTPException(
            status_code=409,
            detail="Despesa cancelada é definitiva e não pode ser alterada",
        )


#: Campos que definem a IDENTIDADE financeira da parcela espelhada. Mexer neles
#: quebra o pareamento com a `AmortizationInstallment`.
_VINCULO_FINANCIAMENTO_IMUTAVEL = {
    "total_amount",
    "transaction_date",
    "billing_month",
    "currency",
    "workspace_id",
}


def _ensure_financing_link_intact(db_transaction: Transaction, update_keys: set):
    """Despesa que espelha uma parcela de financiamento não muda de valor/data.

    A deduplicação do caixa (`CashFlowService`) escolhe entre contar a despesa ou
    contar a parcela. As duas nascem com a mesma data e o mesmo valor; deixar a
    despesa ser editada livremente fazia a saída trocar de mês sem que a parcela
    soubesse — e um valor editado passava a divergir do cronograma de amortização,
    que é o contrato.

    Mudar o resto (título, categoria, tags, divisão entre pessoas) continua
    liberado: isso é sobre COMO a casa rateia a parcela, não sobre o pagamento.
    """
    if db_transaction.financing_installment_id is None:
        return
    proibidos = update_keys & _VINCULO_FINANCIAMENTO_IMUTAVEL
    if proibidos:
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta despesa é o pagamento de uma parcela de financiamento; "
                f"{', '.join(sorted(proibidos))} vêm da parcela. Desfaça o "
                "pagamento no financiamento e refaça-o com os dados corretos."
            ),
        )


def _resync_item_amounts(session: Session, transaction_id: int, new_total: Decimal) -> None:
    """Rateia `new_total` entre os itens da transação, em centavos exatos.

    Usado pelo caminho de edição PARCIAL, que altera o total sem passar pela
    recriação dos filhos. `quantity`/`unit_amount` são normalizados para
    `1 × valor-da-linha`: a fatia rateada raramente é múltipla exata da
    quantidade, e recalcular a linha a partir do unitário encolheria o item
    (mesmo cuidado do `BaseCurrencyService._apply`).
    """
    items = session.exec(
        select(TransactionItem)
        .where(TransactionItem.transaction_id == transaction_id)
        .order_by(TransactionItem.position, TransactionItem.id)
    ).all()
    if not items:
        return

    pesos = {i: _cents(item.amount) for i, item in enumerate(items)}
    if sum(pesos.values()) <= 0:
        pesos = {i: 1 for i in range(len(items))}
    alocado = _allocate_proportional(_cents(new_total), pesos)
    for i, item in enumerate(items):
        item.amount = Decimal(alocado[i]) / Decimal("100")
        if item.unit_amount is not None:
            item.unit_amount = item.amount
            item.quantity = Decimal("1")
        session.add(item)


#: A regra mora em `services/base_conversion.py` desde que o pagamento de parcela
#: de financiamento passou a precisar dela — rota não importa rota. O alias
#: mantém os chamadores deste módulo como estavam.
_compute_base_conversion = compute_base_conversion


def _statement_leg(session: Session, card, transaction_in) -> dict:
    """A perna de fatura do lançamento, ou `{}` quando não há cartão.

    Devolve dict para poder ser espalhado direto no construtor da `Transaction`,
    como `conv_meta` — assim nenhum caminho de criação precisa lembrar dos três
    campos separadamente.
    """
    if card is None:
        return {}
    return compute_statement_conversion(
        session, card,
        currency=transaction_in.currency,
        total_amount=transaction_in.total_amount,
        transaction_date=transaction_in.transaction_date,
    )


def _rotear_fatura(session: Session, card, when, shift: int):
    """`get_or_create_statement` com o deslocamento inalcançável virando 409.

    Ponto único de tradução para os QUATRO caminhos de roteamento desta rota
    (criação, parcelamento, edição e edição do grupo). Espalhar o `try` por cada
    um deles deixaria o primeiro caminho novo respondendo 500 a um erro que é do
    cliente — pedir uma fatura já fechada.
    """
    try:
        return CreditCardService.get_or_create_statement(session, card, when, shift=shift)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _convert_create_to_base(
    session: Session, workspace_id: int, transaction_in: TransactionCreate
):
    """Aplica a conversão a um TransactionCreate — devolve (transaction_in em BRL
    com a divisão inteira reconvertida, meta|None)."""
    conv = _compute_base_conversion(
        session, workspace_id,
        currency=transaction_in.currency,
        total_amount=transaction_in.total_amount,
        transaction_date=transaction_in.transaction_date,
        payment_method=transaction_in.payment_method,
    )
    if conv is None:
        return transaction_in, None
    div = convert_division_to_base(
        factor=conv["factor"],
        base_total=conv["base_total"],
        payers=transaction_in.payers,
        splits=transaction_in.splits or [],
        items=transaction_in.items,
        adjustments=transaction_in.adjustments,
    )
    converted = transaction_in.model_copy(update={
        "total_amount": conv["base_total"],
        "currency": conv["base_currency"],
        "payers": div["payers"],
        "splits": div["splits"],
        "items": div["items"],
        "adjustments": div["adjustments"],
    })
    return converted, conv["meta"]


@_tambem_sem_barra("post", response_model=TransactionRead)
@router.post("/", response_model=TransactionRead)
def create_transaction(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    # Fatura SEMPRE derivada no servidor a partir de cartão + data (ADR 0002)
    statement_id = None
    card = None
    if transaction_in.credit_card_id:
        card = session.get(CreditCard, transaction_in.credit_card_id)
        # O gate é a PROPRIEDADE, não o workspace (ADR 0021): o cartão é meu e eu
        # o uso em qualquer workspace de que participo. A checagem antiga
        # (`card.workspace_id != workspace_id`) era o outro lado do defeito do
        # compartilhamento — o cartão aparecia na listagem do workspace de destino
        # e o lançamento nele respondia 400.
        if not card or card.deleted_at or card.owner_user_id != membership.user_id:
            raise HTTPException(status_code=400, detail="Cartão de crédito inválido")

    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    transaction_in = transaction_in.model_copy(update={
        "currency": resolve_currency(session, workspace_id, transaction_in.currency)
    })
    # A perna de FATURA sai daqui, ANTES da conversão contábil: ela precisa da
    # moeda em que a compra foi feita, e `_convert_create_to_base` a substitui
    # pela moeda-base do workspace (ADR 0024).
    stmt_meta = _statement_leg(session, card, transaction_in)
    # Moeda estrangeira: converte para a base na entrada (taxa do dia + IOF no cartão)
    transaction_in, conv_meta = _convert_create_to_base(session, workspace_id, transaction_in)

    # Parcelamento: N transações irmãs, uma por mês/fatura
    if transaction_in.installments_count and transaction_in.installments_count > 1:
        first_tx = _create_installments(
            session, workspace_id, transaction_in, membership, card,
            conv_meta=conv_meta, stmt_meta=stmt_meta,
        )
        # Evento ÚNICO agregado — N parcelas não podem virar N refetches
        publish_event(session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id)
        session.commit()
        session.refresh(first_tx)
        return first_tx

    if card:
        statement = _rotear_fatura(
            session, card, transaction_in.transaction_date, transaction_in.statement_shift
        )
        statement_id = statement.id

    # Create Transaction
    transaction_data = transaction_in.model_dump(
        exclude={
            "payers", "splits", "items", "adjustments", "tag_ids",
            "installments_count", "settled",
        }
    )
    if not transaction_data.get("billing_month"):
        transaction_data["billing_month"] = month_key_local(transaction_in.transaction_date)

    db_transaction = Transaction(
        **transaction_data,
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
        statement_id=statement_id,
        # Caixa (ADR 0029): quando o dinheiro saiu. `resolve_settled_at` é o
        # ponto ÚNICO que decide — ver `app/domain/settlement.py`.
        settled_at=resolve_settled_at(
            session, workspace_id,
            transaction_date=transaction_in.transaction_date,
            credit_card_id=transaction_in.credit_card_id,
            explicit=transaction_in.settled,
        ),
        **(conv_meta or {}),
        **stmt_meta,
    )
    session.add(db_transaction)
    # flush (não commit): mantém a criação ATÔMICA — se payers/splits/itens
    # falharem na validação, o rollback descarta tudo, sem transação órfã
    session.flush()

    try:
        persist_transaction_children(
            session,
            workspace_id,
            db_transaction,
            total_amount=transaction_in.total_amount,
            split_mode=transaction_in.split_mode,
            payers=transaction_in.payers,
            splits=transaction_in.splits,
            items=transaction_in.items,
            adjustments=transaction_in.adjustments,
            actor_user_id=membership.user_id,
        )
    except ValueError as exc:
        # Divisão/somas inválidas é erro do cliente — nunca 500. Rollback
        # descarta a transação inteira (atômica).
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    if transaction_in.tag_ids is not None:
        _set_transaction_tags(session, workspace_id, db_transaction.id, transaction_in.tag_ids)

    publish_event(session, workspace_id, "transaction.created", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


def _split_amounts(amount: Decimal, parts: int) -> List[Decimal]:
    """Fatia um valor pelos N meses em centavos exatos (resíduo 1¢ aos primeiros
    — ADR 0001). Soma das fatias == valor original por construção."""
    return [m.amount for m in Money(amount).split_equal(parts)]


def _plan_installment_items(
    items: List[TransactionItemCreate], count: int
) -> List[List[TransactionItemCreate]]:
    """Divisão POR ITEM parcelada: fatia cada item pelos N meses, preservando a
    estrutura de participantes. Para shares fixas, fatia o valor de CADA share e
    deriva o total da linha da soma das fatias — assim as shares continuam
    fechando o valor do item em toda parcela. Retorna, por parcela, a lista de
    itens já com quantity=1/unit=None (o valor da linha vira direto)."""
    per_installment: List[List[TransactionItemCreate]] = [[] for _ in range(count)]
    for position, item in enumerate(items):
        method = item.shares[0].split_method if item.shares else SplitMethod.equal
        if method == SplitMethod.fixed:
            share_slices = [_split_amounts(sh.input_value, count) for sh in item.shares]
            for i in range(count):
                shares_i = [
                    TransactionItemShareBase(
                        user_id=sh.user_id,
                        split_method=SplitMethod.fixed,
                        input_value=share_slices[k][i],
                    )
                    for k, sh in enumerate(item.shares)
                ]
                amount_i = sum((s.input_value for s in shares_i), Decimal("0"))
                per_installment[i].append(item.model_copy(update={
                    "amount": amount_i,
                    "quantity": Decimal("1"),
                    "unit_amount": None,
                    "position": position,
                    "shares": shares_i,
                }))
        else:
            # equal/percentage: input_value é escala-invariante — só o valor da
            # linha é fatiado; o serviço recomputa as shares por parcela
            amount_slices = _split_amounts(item.amount, count)
            for i in range(count):
                per_installment[i].append(item.model_copy(update={
                    "amount": amount_slices[i],
                    "quantity": Decimal("1"),
                    "unit_amount": None,
                    "position": position,
                    "shares": list(item.shares or []),
                }))
    return per_installment


def _installment_plan(transaction_in: TransactionCreate, count: int) -> List[Dict]:
    """Plano por parcela {total, splits, items}: parcelar = fatiar a divisão
    pelos N meses. Modo item fatia por item; modo transaction/valor fixo fatia
    cada split; modo transaction igual/porcentagem mantém o comportamento atual
    (split_equal do total, splits escalam por natureza)."""
    if transaction_in.split_mode == SplitMode.item:
        items_per = _plan_installment_items(transaction_in.items or [], count)
        return [
            {
                "total": sum((it.amount for it in items_i), Decimal("0")),
                "splits": [],
                "items": items_i,
            }
            for items_i in items_per
        ]

    method = (
        transaction_in.splits[0].split_method
        if transaction_in.splits
        else SplitMethod.equal
    )
    if method == SplitMethod.fixed:
        split_slices = [_split_amounts(s.input_value, count) for s in transaction_in.splits]
        plans: List[Dict] = []
        for i in range(count):
            splits_i = [
                TransactionSplitBase(
                    user_id=s.user_id,
                    split_method=SplitMethod.fixed,
                    input_value=split_slices[k][i],
                )
                for k, s in enumerate(transaction_in.splits)
            ]
            plans.append({
                "total": sum((sp.input_value for sp in splits_i), Decimal("0")),
                "splits": splits_i,
                "items": None,
            })
        return plans

    amounts = _split_amounts(transaction_in.total_amount, count)
    return [
        {"total": amounts[i], "splits": list(transaction_in.splits), "items": None}
        for i in range(count)
    ]


def _create_installments(
    session: Session,
    workspace_id: int,
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership,
    card: Optional[CreditCard],
    group_id: Optional[str] = None,
    conv_meta: Optional[Dict] = None,
    stmt_meta: Optional[Dict] = None,
):
    """Cria N transações irmãs (i/N), cada uma roteada para a fatura do seu mês,
    fatiando a divisão pelos N meses (igual/porcentagem/valor fixo, pela despesa
    ou por item). Atômico: qualquer falha descarta tudo. NÃO comita nem publica
    evento — quem chama decide (create → bulk_created, group-edit → bulk_updated).
    Reusa `group_id` quando informado (edição do grupo mantém a mesma identidade).
    Com `conv_meta` (lançamento estrangeiro convertido), congela taxa/IOF por
    parcela e fatia o valor ORIGINAL na mesma proporção do total em BRL."""
    count = transaction_in.installments_count
    group_id = group_id or uuid.uuid4().hex
    payer = transaction_in.payers[0]
    plans = _installment_plan(transaction_in, count)
    orig_slices = _split_amounts(conv_meta["original_amount"], count) if conv_meta else None
    # A fatura é fatiada pelo MESMO `_split_amounts` do total, e não recalculada
    # parcela a parcela: é ele que garante que as N parcelas somem exatamente a
    # compra, com o centavo da sobra num lugar só. Recalcular por parcela deixaria
    # a soma da fatura diferente do valor comprado por arredondamento.
    stmt_slices = (
        _split_amounts(stmt_meta["statement_amount"], count) if stmt_meta else None
    )

    base_data = transaction_in.model_dump(exclude={
        "payers", "splits", "items", "adjustments", "tag_ids", "installments_count",
        "title", "total_amount", "transaction_date", "billing_month", "settled",
    })

    first_tx = None
    try:
        for i in range(count):
            plan = plans[i]
            inst_amount = plan["total"]
            inst_title = f"{transaction_in.title} ({i + 1}/{count})"
            inst_date = add_months(transaction_in.transaction_date, i)

            statement_id = None
            if card:
                # O deslocamento vale para TODAS as parcelas, cada uma medida a
                # partir do ciclo natural DELA. É o comportamento correto e o
                # motivo de a coluna ser relativa: se o emissor processou a
                # compra já no ciclo seguinte, ele processou a compra inteira —
                # o cronograma inteiro desliza junto, não só a primeira parcela.
                statement = _rotear_fatura(
                    session, card, inst_date, transaction_in.statement_shift
                )
                statement_id = statement.id

            inst_meta = {}
            if conv_meta:
                inst_meta = {
                    "original_amount": orig_slices[i],
                    "original_currency": conv_meta["original_currency"],
                    "exchange_rate": conv_meta["exchange_rate"],
                    "iof_rate": conv_meta["iof_rate"],
                    "rate_source": conv_meta.get("rate_source"),
                }
            if stmt_meta:
                inst_meta.update({
                    "statement_amount": stmt_slices[i],
                    "statement_currency": stmt_meta["statement_currency"],
                    "statement_exchange_rate": stmt_meta["statement_exchange_rate"],
                })

            db_transaction = Transaction(
                **base_data,
                title=inst_title,
                total_amount=inst_amount,
                transaction_date=inst_date,
                billing_month=month_key_local(inst_date),
                workspace_id=workspace_id,
                created_by_user_id=membership.user_id,
                statement_id=statement_id,
                installment_no=i + 1,
                installments_of=count,
                installment_group_id=group_id,
                # Cada parcela responde pela SUA data (ADR 0029): a 1ª nasce
                # liquidada e as futuras a pagar. `explicit` vale para o lote
                # inteiro — quem diz "já paguei" está falando da compra, e num
                # parcelamento sem cartão (carnê) isso continua sendo uma
                # afirmação sobre a parcela que já venceu, não sobre as outras.
                settled_at=resolve_settled_at(
                    session, workspace_id,
                    transaction_date=inst_date,
                    credit_card_id=transaction_in.credit_card_id,
                    explicit=transaction_in.settled if i == 0 else None,
                ),
                **inst_meta,
            )
            session.add(db_transaction)
            session.flush()

            items = plan["items"]
            if items is None and transaction_in.items:
                # Modo transaction: item-categoria único escala com a parcela
                template = transaction_in.items[0]
                items = [template.model_copy(update={
                    "title": inst_title,
                    "amount": inst_amount,
                    "quantity": Decimal("1"),
                    "unit_amount": None,
                })]

            persist_transaction_children(
                session,
                workspace_id,
                db_transaction,
                total_amount=inst_amount,
                split_mode=transaction_in.split_mode,
                payers=[payer.model_copy(update={"amount": inst_amount})],
                splits=plan["splits"],
                items=items,
                actor_user_id=membership.user_id,
            )

            if transaction_in.tag_ids is not None:
                _set_transaction_tags(session, workspace_id, db_transaction.id, transaction_in.tag_ids)

            if first_tx is None:
                first_tx = db_transaction
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    return first_tx

@router.post("/preview", response_model=TransactionPreviewRead)
def preview_transaction(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Dry-run da criação: devolve a divisão calculada (splits, shares por
    item, rateio de ajustes) SEM persistir — mesma fonte de verdade do POST
    (compute_transaction_breakdown), então o que o preview mostra é
    exatamente o que será gravado."""
    try:
        breakdown = compute_transaction_breakdown(
            session,
            workspace_id,
            total_amount=transaction_in.total_amount,
            split_mode=transaction_in.split_mode,
            payers=transaction_in.payers,
            splits=transaction_in.splits,
            items=transaction_in.items,
            adjustments=transaction_in.adjustments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return breakdown


@_tambem_sem_barra("get", response_model=TransactionListResponse)
@router.get("/", response_model=TransactionListResponse)
def list_transactions(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
    limit: int = Query(10, ge=1, le=100),
    page: int = Query(1, ge=1),
    month: Optional[str] = None, # Formato YYYY-MM
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    payment_method: Optional[PaymentMethod] = None,
    tag_id: Optional[int] = None,
    # Liquidação (ADR 0029): `false` traz só o que ainda não saiu do caixa.
    # Ausente = tudo, que é a leitura padrão do extrato.
    settled: Optional[bool] = None,
    # O que ainda não foi categorizado. Não é `category_id=0`: a ausência de
    # categoria não é uma categoria, e `0` só significaria isso por convenção
    # combinada no código. É o destino do convite "categorizar" dos Relatórios,
    # que até aqui identificavam o problema sem oferecer saída.
    uncategorized: bool = False,
):
    offset = (page - 1) * limit

    # Despesas recorrentes vencidas do mês corrente entram sozinhas (lazy accrual)
    # antes de montar o extrato — assim "tudo que é recorrente" aparece sem o botão.
    # `role`: um viewer não provoca escrita (ver ensure_and_commit).
    RecurringMaterializationService.ensure_and_commit(
        session, workspace_id, role=membership.role
    )

    # Base query. O escopo de visibilidade (ADR 0018) entra ANTES de qualquer
    # filtro opcional, e por isso a contagem e a soma logo abaixo — que derivam
    # desta MESMA statement via `.subquery()` — já saem coerentes com o que o
    # membro pode ver. Sem isso, "N lançamentos" e "saídas" contariam despesas
    # que a lista nem mostra.
    statement = scope_transactions(
        select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.deleted_at.is_(None),
        ),
        membership,
    )

    # Filtering by month
    if month:
        statement = statement.where(Transaction.billing_month == month)

    # Filtering by search. Dois cuidados:
    # 1. '%' e '_' são curingas do LIKE e precisam de escape, senão buscar "%"
    #    casa com TODOS os lançamentos (autoescape=True).
    # 2. lower() nos DOIS lados: LIKE é case-sensitive no Postgres e
    #    case-insensitive no SQLite. Sem isto, "supermercado" achava
    #    "Supermercado" em dev e não achava em produção — e nenhum teste pegava,
    #    porque a fixture usava a mesma caixa da busca.
    if search:
        statement = statement.where(
            func.lower(Transaction.title).contains(search.lower(), autoescape=True)
        )

    # Filtering by category (via items). DISTINCT: uma despesa com dois itens da
    # MESMA categoria casava duas vezes no join e aparecia duplicada na lista
    # (e contava 2 no total).
    if category_id:
        statement = statement.join(TransactionItem).where(
            TransactionItem.category_id == category_id
        ).distinct()

    # Sem categoria: nenhum item categorizado — INCLUSIVE a despesa sem item
    # nenhum, que é a forma mais comum (lançamento simples não cria item). Um
    # `outerjoin` traria a despesa parcialmente categorizada junto (ela tem UM
    # item nulo), e ela não é trabalho pendente do mesmo tipo: já foi mexida.
    if uncategorized:
        statement = statement.where(
            ~select(TransactionItem.id)
            .where(TransactionItem.transaction_id == Transaction.id)
            .where(TransactionItem.category_id.is_not(None))
            .exists()
        )

    # Filtering by payment method
    if payment_method:
        statement = statement.where(Transaction.payment_method == payment_method)

    # Filtering by settlement (ADR 0029). Compra no CARTÃO fica fora do recorte
    # "a pagar": ela nunca tem liquidação própria — quem se paga é a fatura —, e
    # sem esta exclusão o filtro devolveria toda compra do mês como pendente.
    if settled is not None:
        statement = statement.where(
            Transaction.settled_at.is_not(None)
            if settled
            else (Transaction.settled_at.is_(None)) & (Transaction.credit_card_id.is_(None))
        )

    # Filtering by tag
    if tag_id:
        statement = statement.join(TransactionTagLink).where(
            TransactionTagLink.tag_id == tag_id
        ).distinct()

    # Count + soma sobre a MESMA subquery filtrada. A soma referencia
    # subq.c.total_amount (não Transaction.total_amount): usar a coluna da
    # tabela aqui produziria um produto cartesiano com a subquery.
    subq = statement.subquery()
    total = session.exec(select(func.count()).select_from(subq)).one()

    # Soma do FILTRO INTEIRO (não só da página): a tela mostra "N lançamentos"
    # global, então o total de saídas ao lado precisa ser da mesma amostra.
    #
    # A política única (ADR 0003/0006) vale só na AGREGAÇÃO, não na lista: o
    # extrato continua mostrando rascunho e cancelada (com a pílula de status),
    # mas elas não são gasto e não podem entrar no número. Sem estes dois
    # filtros, "saídas" aqui e "Sua despesa" no Início — lidos na mesma sessão —
    # nunca fechavam, e um lançamento legado em outra moeda era somado cru junto
    # com a moeda-base.
    base_currency = workspace_base_currency(session, workspace_id)
    total_amount = session.exec(
        select(func.coalesce(func.sum(subq.c.total_amount), 0)).where(
            subq.c.status.in_(REALIZED_STATUSES),
            subq.c.currency == base_currency,
        )
    ).one()

    # Final statement with ordering and pagination
    statement = statement.order_by(Transaction.transaction_date.desc()).offset(offset).limit(limit)
    transactions = session.exec(statement).all()

    return {
        "items": transactions,
        "total": total,
        "total_amount": total_amount,
        "page": page,
        "limit": limit,
        "total_pages": math.ceil(total / limit) if total > 0 else 1
    }

@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return get_visible_transaction(session, workspace_id, transaction_id, membership)

@router.put("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    workspace_id: int,
    transaction_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionUpdate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    db_transaction = get_visible_transaction(session, workspace_id, transaction_id, membership)

    # Member edita apenas os próprios lançamentos; admin+ edita qualquer um
    assert_can_write(
        db_transaction.created_by_user_id,
        membership,
        detail="Você só pode editar os próprios lançamentos",
    )

    update_data = transaction_in.model_dump(exclude_unset=True)

    _ensure_not_cancelled(db_transaction)
    _ensure_not_paid(db_transaction, set(update_data.keys()))
    _ensure_financing_link_intact(db_transaction, set(update_data.keys()))

    # Máquina de estados (ADR 0003)
    if "status" in update_data:
        try:
            validate_status_transition(db_transaction.status, update_data["status"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    # Tags: substituição dos vínculos vale nos dois caminhos (parcial e full)
    tag_ids = update_data.pop("tag_ids", None)
    if tag_ids is not None:
        _set_transaction_tags(session, workspace_id, db_transaction.id, tag_ids)

    # Mudou a data sem informar billing_month explicitamente? Recalcula —
    # senão a transação some do filtro do mês novo e continua no antigo
    if "transaction_date" in update_data and "billing_month" not in update_data:
        update_data["billing_month"] = month_key_local(update_data["transaction_date"])

    # "Já foi paga" (ADR 0029) → `settled_at`. O campo de ENTRADA é booleano e a
    # coluna é um instante, então a tradução mora aqui — e não pode ir para o
    # `setattr` genérico lá embaixo, que gravaria um atributo `settled` fantasma
    # no objeto do ORM: aceito pelo SQLModel, jamais persistido, e sem erro.
    #
    # Só age quando o booleano MUDA o estado. Um PUT que reenvia o formulário
    # inteiro carrega `settled: true` junto com a edição do título; sem esta
    # guarda, corrigir o título de uma conta paga em 14/08 reescreveria a data do
    # pagamento para a data do lançamento e moveria a saída de caixa de mês.
    if "settled" in update_data:
        quer_liquidada = update_data.pop("settled")
        ja_liquidada = db_transaction.settled_at is not None
        if quer_liquidada and not ja_liquidada:
            update_data["settled_at"] = update_data.get(
                "transaction_date", db_transaction.transaction_date
            )
        elif not quer_liquidada and ja_liquidada:
            update_data["settled_at"] = None

    # Coerência método de pagamento × cartão contra o estado EFETIVO
    if "payment_method" in update_data or "credit_card_id" in update_data:
        effective_card = update_data.get("credit_card_id", db_transaction.credit_card_id)
        effective_method = update_data.get("payment_method", db_transaction.payment_method)
        try:
            update_data["payment_method"] = normalize_payment_method(effective_method, effective_card)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # Reroteamento da fatura (ADR 0002): mudou data, cartão ou o deslocamento
    # declarado (ADR 0032), a fatura é rederivada no servidor; sem cartão, o
    # vínculo é removido.
    #
    # `statement_shift` entra na condição porque é a ÚNICA forma de mover uma
    # compra de fatura depois de lançada. Sem ele aqui, a coluna seria gravada e
    # o `statement_id` continuaria apontando para a fatura antiga: a tela diria
    # "movida para setembro" e a fatura de agosto seguiria cobrando o valor.
    # `statement_shift` é NOT NULL e o campo de entrada é `Optional[int]` (para
    # "não mexe" ser distinguível de "zera"). Um `null` explícito no corpo cairia
    # no `setattr` genérico e gravaria None na coluna — IntegrityError no commit.
    if update_data.get("statement_shift", 0) is None:
        update_data.pop("statement_shift")

    if {"transaction_date", "credit_card_id", "statement_shift"} & update_data.keys():
        effective_card_id = update_data.get("credit_card_id", db_transaction.credit_card_id)
        effective_shift = update_data.get("statement_shift", db_transaction.statement_shift)
        # A guarda vale para o deslocamento PEDIDO nesta requisição, não para o
        # herdado da linha: tirar o cartão de uma compra que já estava deslocada
        # é uma edição legítima — e o `else` abaixo zera o valor órfão. Validar o
        # herdado transformava "mudei para Pix" num 400 sem saída, porque a única
        # forma de zerar o deslocamento seria mandá-lo junto de um cartão.
        if "statement_shift" in update_data:
            try:
                validate_statement_shift(effective_shift, effective_card_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        if effective_card_id is not None:
            card = session.get(CreditCard, effective_card_id)
            # Cartão é pessoal (ADR 0021): tem de ser de quem está editando.
            if not card or card.deleted_at or card.owner_user_id != membership.user_id:
                raise HTTPException(status_code=400, detail="Cartão de crédito inválido")
            effective_date = update_data.get("transaction_date", db_transaction.transaction_date)
            # O deslocamento é RELATIVO, então sobrevive à edição de data de
            # graça: o alvo natural é recalculado da data nova e a correção se
            # reaplica sobre ele. Um mês absoluto gravado teria de ser
            # invalidado aqui, e a compra voltaria calada para o alvo natural.
            statement = _rotear_fatura(session, card, effective_date, effective_shift)
            update_data["statement_id"] = statement.id
            # Virou compra no cartão: a liquidação própria deixa de existir
            # (ADR 0029). Quem paga é a FATURA, e manter `settled_at` aqui somaria
            # a mesma saída duas vezes no caixa — uma pela despesa, outra pelo
            # pagamento da fatura.
            update_data["settled_at"] = None
        else:
            update_data["statement_id"] = None
            # Sem cartão não há fatura para deslocar. Zerar é o par do
            # `validate_statement_shift`: deixar o valor antigo na linha o faria
            # acordar se o lançamento voltasse para um cartão depois, mandando a
            # compra para uma fatura que ninguém pediu naquele momento.
            update_data["statement_shift"] = 0
            # SAIU do cartão (tinha, deixou de ter): volta a ter liquidação
            # própria. Sem isto a compra ficava com `settled_at` nulo para
            # sempre — fora do caixa, e sem aparecer em Contas a pagar.
            #
            # A condição é a TRANSIÇÃO, não "está sem cartão": este ramo também
            # roda quando só a data muda numa despesa que nunca teve cartão, e
            # recalcular ali reabriria uma conta já paga só porque alguém
            # corrigiu o dia.
            if db_transaction.credit_card_id is not None and "settled_at" not in update_data:
                update_data["settled_at"] = resolve_settled_at(
                    session, workspace_id,
                    transaction_date=update_data.get(
                        "transaction_date", db_transaction.transaction_date
                    ),
                    explicit=transaction_in.settled,
                )

    if FULL_EDIT_KEYS & update_data.keys():
        return _full_edit(session, workspace_id, db_transaction, transaction_in, update_data, membership)

    # ------- Caminho parcial (compatível com clientes antigos) -------

    # Alterar o valor total precisa manter payers/splits consistentes —
    # senão o cálculo de dívidas diverge do total. No caso simples
    # (1 pagador, ≤1 divisão) escala junto; com múltiplos, exige recriar.
    if "total_amount" in update_data and update_data["total_amount"] != db_transaction.total_amount:
        if db_transaction.split_mode == SplitMode.item:
            raise HTTPException(
                status_code=400,
                detail="Despesa dividida por itens: altere o valor editando os itens (edição completa)"
            )
        if db_transaction.adjustments:
            raise HTTPException(
                status_code=400,
                detail="Despesa com ajustes de total: use a edição completa (itens + ajustes)"
            )
        new_total = update_data["total_amount"]
        payers = session.exec(
            select(TransactionPayer).where(TransactionPayer.transaction_id == db_transaction.id)
        ).all()
        splits = session.exec(
            select(TransactionSplit).where(TransactionSplit.transaction_id == db_transaction.id)
        ).all()
        if len(payers) > 1 or len(splits) > 1:
            raise HTTPException(
                status_code=400,
                detail="Transação dividida entre várias pessoas: use a edição completa da divisão"
            )
        for payer in payers:
            payer.amount = new_total
            session.add(payer)
        for split in splits:
            split.computed_amount = new_total
            if split.split_method == SplitMethod.fixed:
                split.input_value = new_total
            session.add(split)
        # Os ITENS acompanham o novo total. Sem isto, o item que carrega a
        # categoria ficava com o valor ANTIGO — e a distribuição por categoria
        # (ReportService.get_summary soma TransactionItem.amount) mostrava a fatia
        # congelada no valor velho, com o resíduo `total − categorizado` virando
        # uma fatia "Sem categoria" que não existe. O gráfico fechava com o total
        # e mentia na composição, que é justamente o que o usuário lê ali.
        # Rateio em centavos exatos (ADR 0001) para `soma(itens) == total` valer
        # também quando há mais de um item.
        _resync_item_amounts(session, db_transaction.id, new_total)
        # Total alterado no caminho parcial (semântica BRL): a proveniência
        # estrangeira congelada (original_*) não corresponde mais ao novo total —
        # limpa p/ o registro não afirmar um câmbio que já não bate. Edição de
        # moeda estrangeira usa a edição completa (_full_edit), que re-converte.
        if db_transaction.original_currency:
            for k in ("original_amount", "original_currency", "exchange_rate", "iof_rate", "rate_source"):
                update_data[k] = None

    # Categoria: upsert do item único (modelo simplificado de 1 categoria/transação)
    if "category_id" in update_data:
        category_id = update_data.pop("category_id")
        if category_id is not None:
            from app.models.category import Category
            category = session.get(Category, category_id)
            if not category or category.workspace_id != workspace_id or category.deleted_at:
                raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")
        existing_item = session.exec(
            select(TransactionItem).where(TransactionItem.transaction_id == db_transaction.id)
        ).first()
        if existing_item:
            existing_item.category_id = category_id
            session.add(existing_item)
        elif category_id is not None:
            session.add(TransactionItem(
                transaction_id=db_transaction.id,
                title=update_data.get("title", db_transaction.title),
                amount=update_data.get("total_amount", db_transaction.total_amount),
                category_id=category_id,
            ))

    for key, value in update_data.items():
        setattr(db_transaction, key, value)

    _resync_statement_leg(session, db_transaction, membership)
    session.add(db_transaction)
    publish_event(session, workspace_id, "transaction.updated", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


def _resync_statement_leg(
    session: Session, tx: Transaction, membership: WorkspaceMembership
) -> None:
    """Reancora a perna de fatura no estado FINAL do lançamento.

    Chamada depois dos `setattr`, de propósito: valor, moeda, data e cartão podem
    ter mudado em qualquer combinação, e cada um deles muda o que a fatura cobra.
    Deduzir isso ramo a ramo era o que fazia o valor de fatura ficar para trás
    numa das combinações.
    """
    card = None
    if tx.credit_card_id:
        card = session.get(CreditCard, tx.credit_card_id)
        if card and (card.deleted_at or card.owner_user_id != membership.user_id):
            card = None
    apply_statement_leg(session, tx, card)


def _full_edit(
    session: Session,
    workspace_id: int,
    db_transaction: Transaction,
    transaction_in: TransactionUpdate,
    update_data: dict,
    membership: WorkspaceMembership,
):
    """Substitui payers/splits/items atomicamente (mesmo padrão flush/commit do
    create: qualquer 400 dá rollback e os filhos antigos permanecem)."""
    if transaction_in.payers is None:
        raise HTTPException(
            status_code=400,
            detail="Edição da divisão exige o conjunto completo: payers e splits (ou items)"
        )

    effective_mode = transaction_in.split_mode if transaction_in.split_mode is not None else db_transaction.split_mode
    effective_total = transaction_in.total_amount if transaction_in.total_amount is not None else db_transaction.total_amount
    splits = transaction_in.splits if transaction_in.splits is not None else []
    items = transaction_in.items
    # Conjunto completo: sem o campo, os ajustes anteriores são descartados
    adjustments = transaction_in.adjustments

    # Moeda estrangeira: converte o total/pagador para BRL e congela o original.
    # Editar em BRL (ou trocar de volta) limpa o original congelado.
    conv = _compute_base_conversion(
        session, workspace_id,
        currency=update_data.get("currency", db_transaction.currency),
        total_amount=effective_total,
        transaction_date=update_data.get("transaction_date", db_transaction.transaction_date),
        payment_method=update_data.get("payment_method", db_transaction.payment_method),
    )
    if conv is not None:
        div = convert_division_to_base(
            factor=conv["factor"],
            base_total=conv["base_total"],
            payers=transaction_in.payers,
            splits=splits,
            items=items,
            adjustments=adjustments,
        )
        effective_total = conv["base_total"]
        splits = div["splits"]
        items = div["items"]
        adjustments = div["adjustments"]
        transaction_in = transaction_in.model_copy(update={"payers": div["payers"]})
        # total_amount vem em update_data (setattr) — precisa virar BRL também
        update_data["total_amount"] = conv["base_total"]
        update_data["currency"] = conv["base_currency"]
        update_data.update(conv["meta"])
    else:
        for k in ("original_amount", "original_currency", "exchange_rate", "iof_rate", "rate_source"):
            update_data[k] = None

    try:
        validate_split_structure(effective_mode, splits, items)
        validate_payer_origins(
            transaction_in.payers,
            update_data.get("credit_card_id", db_transaction.credit_card_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    delete_transaction_children(session, db_transaction.id)

    for key, value in update_data.items():
        if key in ("payers", "splits", "items", "adjustments", "category_id"):
            continue
        setattr(db_transaction, key, value)
    db_transaction.split_mode = effective_mode
    _resync_statement_leg(session, db_transaction, membership)
    session.add(db_transaction)
    session.flush()

    try:
        persist_transaction_children(
            session,
            workspace_id,
            db_transaction,
            total_amount=effective_total,
            split_mode=effective_mode,
            payers=transaction_in.payers,
            splits=splits,
            items=items,
            adjustments=adjustments,
            actor_user_id=membership.user_id,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    publish_event(session, workspace_id, "transaction.updated", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    session.refresh(db_transaction)
    return db_transaction


@router.delete("/{transaction_id}", response_model=DeleteResult)
def delete_transaction(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    db_transaction = get_visible_transaction(session, workspace_id, transaction_id, membership)

    # Member exclui apenas os próprios lançamentos; admin+ exclui qualquer um
    assert_can_write(
        db_transaction.created_by_user_id,
        membership,
        detail="Você só pode excluir os próprios lançamentos",
    )

    _ensure_not_paid(db_transaction)

    db_transaction.deleted_at = datetime.datetime.now(datetime.UTC)
    session.add(db_transaction)
    # Quantos anexos foram junto. A exclusão é SOFT e agora tem "desfazer"
    # (`/restore`), mas o anexo não tem soft delete — ele é apagado de verdade,
    # porque um recibo preso a uma despesa inalcançável ocuparia cota para
    # sempre. O desfazer devolve a despesa SEM os recibos, e é este número que
    # permite à tela dizer isso em vez de deixar a pessoa descobrir sozinha.
    # `_purge_attachments` devolve CHAVES a liberar, que são deduplicadas — dois
    # anexos com o mesmo conteúdo compartilham chave. Para avisar a pessoa o que
    # interessa é quantos RECIBOS sumiram, então a contagem é feita antes.
    quantos_anexos = session.exec(
        select(func.count()).select_from(Attachment)
        .where(Attachment.transaction_id == db_transaction.id)
    ).one()
    liberar = _purge_attachments(session, [db_transaction.id])
    publish_event(session, workspace_id, "transaction.deleted", "transaction", db_transaction.id, membership.user_id)
    session.commit()
    free_keys(liberar)
    return {"status": "ok", "attachments_removed": int(quantos_anexos)}


@router.post("/{transaction_id}/restore", response_model=StatusRead)
def restore_transaction(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Desfazer a exclusão — o caminho de volta que o soft delete já permitia.

    Excluir a linha errada é o erro mais fácil de cometer numa lista de trinta
    linhas parecidas, e até aqui ele custava relançar tudo à mão: título, valor,
    data, pagadores e divisão. O dado nunca saiu do banco; só não havia porta.

    **Mesma permissão do delete**, e por isso `assert_can_write` com o mesmo
    argumento: sem ele, `restore` seria a porta dos fundos para reviver o
    lançamento de outra pessoa — quem não pode apagar também não pode ressuscitar.

    Idempotente: restaurar o que já está vivo devolve 200 sem tocar em nada. A
    interface oferece o "desfazer" num toast, e um segundo toque (ou um duplo
    clique) não pode virar erro na cara de quem acabou de acertar.
    """
    # `get_visible_transaction` filtra `deleted_at IS NULL` — aqui é justamente o
    # apagado que se procura, então a busca é direta, com o escopo de
    # visibilidade aplicado à mão.
    alvo = session.exec(
        scope_transactions(
            select(Transaction).where(
                Transaction.workspace_id == workspace_id,
                Transaction.id == transaction_id,
            ),
            membership,
        )
    ).first()
    if alvo is None:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado")

    assert_can_write(
        alvo.created_by_user_id,
        membership,
        detail="Você só pode restaurar os próprios lançamentos",
    )

    if alvo.deleted_at is None:
        return {"status": "ok"}

    alvo.deleted_at = None
    session.add(alvo)
    publish_event(
        session, workspace_id, "transaction.updated", "transaction",
        alvo.id, membership.user_id,
    )
    session.commit()
    return {"status": "ok"}


def _purge_attachments(session: Session, transaction_ids: List[int]) -> List[str]:
    """Apaga os anexos das despesas excluídas e devolve as chaves de
    armazenamento a liberar DEPOIS do commit (`free_keys`).

    A exclusão de despesa é SOFT, mas o anexo não tem soft delete nem cascade: o
    recibo ficava inalcançável pela UI (list/download passam por
    `_get_transaction_or_404`, que dá 404 na despesa apagada) e mesmo assim
    continuava contando na cota do workspace (`_ensure_quota` soma tudo). Ou
    seja: espaço perdido para sempre, sem nenhuma tela por onde liberá-lo.

    Delete pelo ORM (não bulk) para os listeners de auditoria registrarem a
    remoção. Não comita — quem chama comanda a transação (ADR 0010).
    """
    if not transaction_ids:
        return []
    anexos = session.exec(
        select(Attachment).where(Attachment.transaction_id.in_(transaction_ids))
    ).all()
    liberar = keys_to_free(session, anexos)
    for anexo in anexos:
        session.delete(anexo)
    return liberar


def _load_group_siblings(
    session: Session, workspace_id: int, anchor: Transaction
) -> List[Transaction]:
    """Todas as parcelas irmãs vivas do grupo (ou só a âncora, se não for grupo)."""
    if not anchor.installment_group_id:
        return [anchor]
    return session.exec(
        select(Transaction).where(
            Transaction.workspace_id == workspace_id,
            Transaction.installment_group_id == anchor.installment_group_id,
            Transaction.deleted_at.is_(None),
        )
    ).all()


def _get_group_anchor(
    session: Session, workspace_id: int, transaction_id: int, membership: WorkspaceMembership
) -> Transaction:
    anchor = get_visible_transaction(session, workspace_id, transaction_id, membership)
    # Grupo é coeso: as irmãs compartilham o mesmo criador, então o gate de
    # propriedade vale pela âncora (member só mexe no que é seu; admin+ em tudo)
    assert_can_write(
        anchor.created_by_user_id,
        membership,
        detail="Você só pode alterar os próprios lançamentos",
    )
    return anchor


# "Compra (3/12)" → "Compra": o sufixo de parcela é derivado, não faz parte do
# título base que o usuário edita.
#
# SEM `\s*` na frente de propósito. Com ele, o espaço antes do parêntese vira o
# primeiro token do padrão, e aí toda posição da string é um começo possível: o
# motor consome os espaços, esbarra no `\(` e recua — O(n²) num título que seja
# só espaço em branco. O `.strip()` abaixo já tira esse espaço, então o prefixo
# não fazia trabalho nenhum além do de dar o que retroceder.
_INSTALLMENT_SUFFIX_RE = re.compile(r"\(\d+/\d+\)\s*$")


def _strip_installment_suffix(title: str) -> str:
    return _INSTALLMENT_SUFFIX_RE.sub("", title).strip()


def _aggregate_group_whole(
    siblings: List[Transaction], base_title: str, group_total: Decimal
) -> Dict:
    """Reconstrói a definição da COMPRA INTEIRA (formato TransactionRead) a partir
    das parcelas vivas, para o form de edição pré-preencher o total cheio + a
    divisão certa. Métodos igual/porcentagem são estruturais (vêm da 1ª parcela);
    valor fixo e itens são SOMADOS entre as parcelas (senão não fechariam o total
    cheio)."""
    ref = min(siblings, key=lambda t: t.installment_no or 0)
    payer = ref.payers[0] if ref.payers else None

    # Compra estrangeira: o form edita na MOEDA ORIGINAL (soma dos originais); o
    # backend re-converte no save. Sem original, edita direto em BRL.
    if ref.original_currency:
        whole_currency = ref.original_currency
        whole_total = sum((t.original_amount or Decimal("0") for t in siblings), Decimal("0"))
    else:
        whole_currency = ref.currency
        whole_total = group_total

    whole: Dict = {
        "id": ref.id,
        "workspace_id": ref.workspace_id,
        "title": base_title,
        "description": ref.description,
        "currency": whole_currency,
        "total_amount": str(whole_total),
        "transaction_date": ref.transaction_date,
        "billing_month": ref.billing_month,
        "status": ref.status,
        "credit_card_id": ref.credit_card_id,
        "statement_id": ref.statement_id,
        "split_mode": ref.split_mode,
        "payment_method": ref.payment_method,
        "installment_no": None,
        "installments_of": ref.installments_of,
        "installment_group_id": ref.installment_group_id,
        "created_by_user_id": ref.created_by_user_id,
        "created_at": ref.created_at,
        "updated_at": ref.updated_at,
        "payers": [{
            "id": payer.id if payer else 0,
            "user_id": payer.user_id if payer else ref.created_by_user_id,
            "amount": str(whole_total),
            "payment_method": payer.payment_method if payer else None,
            "account_id": payer.account_id if payer else None,
        }],
        "splits": [],
        "items": [],
        "adjustments": [],
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in ref.tags],
    }

    if ref.split_mode == SplitMode.transaction:
        method = ref.splits[0].split_method if ref.splits else SplitMethod.equal
        if method == SplitMethod.fixed:
            totals: Dict[int, Decimal] = {}
            for s in siblings:
                for sp in s.splits:
                    totals[sp.user_id] = totals.get(sp.user_id, Decimal("0")) + sp.computed_amount
            # Grupo estrangeiro: reconstrói o valor fixo na MOEDA ORIGINAL (BRL ÷
            # fator) para o form fechar com o total exibido na moeda original.
            if ref.original_currency and ref.exchange_rate:
                factor = ref.exchange_rate * (Decimal("1") + (ref.iof_rate or Decimal("0")))
                if factor:
                    totals = {
                        uid: (v / factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        for uid, v in totals.items()
                    }
            whole["splits"] = [
                {"id": 0, "user_id": uid, "split_method": "fixed",
                 "input_value": str(v), "computed_amount": str(v)}
                for uid, v in totals.items()
            ]
        else:
            whole["splits"] = [
                {"id": sp.id, "user_id": sp.user_id, "split_method": sp.split_method,
                 "input_value": str(sp.input_value), "computed_amount": str(sp.computed_amount)}
                for sp in ref.splits
            ]
        if ref.items:
            it = ref.items[0]
            whole["items"] = [{
                "id": it.id, "title": base_title, "amount": str(group_total),
                "quantity": "1", "unit_amount": None, "position": 0,
                "category_id": it.category_id, "shares": [],
            }]
        return whole

    # split_mode == item: soma cada item (por posição) e cada share entre as parcelas
    by_pos: Dict[int, Dict] = {}
    for s in siblings:
        for it in s.items:
            agg = by_pos.get(it.position)
            share_method = it.shares[0].split_method if it.shares else SplitMethod.equal
            if agg is None:
                agg = {
                    "id": it.id, "title": it.title, "category_id": it.category_id,
                    "amount": Decimal("0"), "method": share_method,
                    "fixed": {}, "struct": [(sh.user_id, sh.split_method, sh.input_value) for sh in it.shares],
                }
                by_pos[it.position] = agg
            agg["amount"] += it.amount
            for sh in it.shares:
                agg["fixed"][sh.user_id] = agg["fixed"].get(sh.user_id, Decimal("0")) + sh.computed_amount

    # Grupo estrangeiro: re-expressa itens e shares fixas na MOEDA ORIGINAL,
    # rateando o total original (soma dos original_amount) pelos pesos em BRL em
    # CENTAVOS exatos — os itens fecham o total exibido e as shares fecham o item
    # (o save re-rateia o BRL). Sem original, mantém os valores em BRL.
    positions = sorted(by_pos)
    item_orig_cents = None
    if ref.original_currency and ref.exchange_rate:
        weights = {pos: _cents(by_pos[pos]["amount"]) for pos in positions}
        if sum(weights.values()) > 0:
            item_orig_cents = _allocate_proportional(_cents(whole_total), weights)

    items = []
    for pos in positions:
        agg = by_pos[pos]
        item_amount = (
            Decimal(item_orig_cents[pos]) / Decimal("100") if item_orig_cents else agg["amount"]
        )
        if agg["method"] == SplitMethod.fixed:
            fixed_vals = agg["fixed"]
            if item_orig_cents:
                sw = {uid: _cents(v) for uid, v in agg["fixed"].items()}
                if sum(sw.values()) > 0:
                    share_cents = _allocate_proportional(_cents(item_amount), sw)
                    fixed_vals = {uid: Decimal(share_cents[uid]) / Decimal("100") for uid in agg["fixed"]}
            shares = [
                {"id": 0, "user_id": uid, "split_method": "fixed",
                 "input_value": str(v), "computed_amount": str(v)}
                for uid, v in fixed_vals.items()
            ]
        else:
            shares = [
                {"id": 0, "user_id": uid, "split_method": m, "input_value": str(iv), "computed_amount": "0"}
                for (uid, m, iv) in agg["struct"]
            ]
        items.append({
            "id": agg["id"], "title": agg["title"], "amount": str(item_amount),
            "quantity": "1", "unit_amount": None, "position": pos,
            "category_id": agg["category_id"], "shares": shares,
        })
    whole["items"] = items
    return whole


def _recompute_open_installments(
    session: Session,
    workspace_id: int,
    transaction_in: TransactionCreate,
    siblings: List[Transaction],
    paid: List[Transaction],
    card: Optional[CreditCard],
    membership: WorkspaceMembership,
    conv_meta: Optional[Dict] = None,
    stmt_meta: Optional[Dict] = None,
) -> Transaction:
    """Congela as parcelas pagas e recalcula as em aberto para fechar o novo
    total da compra (total − já pago), fatiando o restante entre as parcelas em
    aberto. Mantém o número de parcelas. Não comita (o chamador decide)."""
    new_count = transaction_in.installments_count
    paid_sum = sum((t.total_amount for t in paid), Decimal("0"))
    remaining = transaction_in.total_amount - paid_sum

    open_sibs = sorted(
        [
            t for t in siblings
            if t.status in (
                TransactionStatus.draft, TransactionStatus.pending, TransactionStatus.confirmed,
            )
        ],
        key=lambda t: t.installment_no or 0,
    )
    if not open_sibs:
        raise ValueError("Não há parcelas em aberto para recalcular")

    # Fatiamento do restante entre as parcelas abertas — reusa o mesmo motor da
    # criação (igual/porcentagem/valor fixo, pela despesa ou por item).
    sub_plan_source = transaction_in.model_copy(update={
        "total_amount": remaining,
        "installments_count": len(open_sibs),
    })
    plans = _installment_plan(sub_plan_source, len(open_sibs))

    payer = transaction_in.payers[0]
    base_title = transaction_in.title

    first_tx: Optional[Transaction] = None
    for sib, plan in zip(open_sibs, plans):
        inst_amount = plan["total"]
        sib.title = f"{base_title} ({sib.installment_no}/{new_count})"
        sib.description = transaction_in.description
        sib.total_amount = inst_amount
        sib.currency = transaction_in.currency
        sib.payment_method = transaction_in.payment_method
        sib.credit_card_id = transaction_in.credit_card_id
        sib.installments_of = new_count
        if conv_meta:
            factor = conv_meta["exchange_rate"] * (Decimal("1") + conv_meta["iof_rate"])
            sib.original_amount = (
                (inst_amount / factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if factor else None
            )
            sib.original_currency = conv_meta["original_currency"]
            sib.exchange_rate = conv_meta["exchange_rate"]
            sib.iof_rate = conv_meta["iof_rate"]
            sib.rate_source = conv_meta.get("rate_source")
        else:
            sib.original_amount = None
            sib.original_currency = None
            sib.exchange_rate = None
            sib.iof_rate = None
            sib.rate_source = None
        # Fatura re-derivada por data/cartão/deslocamento (ADR 0002 e 0032)
        if card:
            # `transaction_in.statement_shift` (o valor NOVO vindo do
            # formulário), não o da parcela: esta rotina existe para reescrever
            # as parcelas em aberto com a definição nova da compra, e o
            # deslocamento é parte dela. Ler o da parcela congelaria a correção
            # antiga e a edição do grupo nunca conseguiria desfazê-la.
            sib.statement_shift = transaction_in.statement_shift
            statement = _rotear_fatura(
                session, card, sib.transaction_date, transaction_in.statement_shift
            )
            sib.statement_id = statement.id
            # A perna de fatura acompanha o novo valor da parcela. Sem isto ela
            # ficaria com o valor ANTIGO e o total da fatura deixaria de bater
            # com a compra que a UI mostra — exatamente o tipo de divergência
            # que este ADR existe para fechar. `statement_exchange_rate` já traz
            # a taxa × IOF congelados na compra, então a parcela reconvertida
            # usa o mesmo câmbio das irmãs, e não o de hoje.
            taxa = (stmt_meta or {}).get("statement_exchange_rate") or Decimal("1")
            # O multiplicando é o valor na moeda de ENTRADA, porque é dela que a
            # taxa parte. Numa compra estrangeira `inst_amount` já está na base do
            # workspace, e `original_amount` (recalculado logo acima) é a fatia
            # desta parcela na moeda comprada — usar o valor errado aqui aplicaria
            # um câmbio a um número que já foi convertido uma vez.
            na_entrada = sib.original_amount if conv_meta else inst_amount
            sib.statement_currency = (stmt_meta or {}).get("statement_currency") or card.currency
            sib.statement_amount = (na_entrada * taxa).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ) if na_entrada is not None else inst_amount
            sib.statement_exchange_rate = taxa
        else:
            sib.statement_id = None
            sib.statement_shift = 0
            sib.statement_amount = None
            sib.statement_currency = None
            sib.statement_exchange_rate = None
        session.add(sib)

        items = plan["items"]
        if items is None and transaction_in.items:
            template = transaction_in.items[0]
            items = [template.model_copy(update={
                "title": sib.title,
                "amount": inst_amount,
                "quantity": Decimal("1"),
                "unit_amount": None,
            })]

        delete_transaction_children(session, sib.id)
        session.flush()
        persist_transaction_children(
            session,
            workspace_id,
            sib,
            total_amount=inst_amount,
            split_mode=transaction_in.split_mode,
            payers=[payer.model_copy(update={"amount": inst_amount})],
            splits=plan["splits"],
            items=items,
            actor_user_id=membership.user_id,
        )
        if transaction_in.tag_ids is not None:
            _set_transaction_tags(session, workspace_id, sib.id, transaction_in.tag_ids)
        if first_tx is None:
            first_tx = sib

    return first_tx or paid[0]


@router.post("/{transaction_id}/installment-group/cancel", response_model=InstallmentGroupCancelResult)
def cancel_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Cancela TODAS as parcelas vivas do grupo de uma vez (mantém histórico).
    Parcelas já pagas são preservadas — só reabrindo antes."""
    anchor = _get_group_anchor(session, workspace_id, transaction_id, membership)
    siblings = _load_group_siblings(session, workspace_id, anchor)

    cancelled = 0
    skipped_paid = 0
    for tx in siblings:
        if tx.status == TransactionStatus.paid:
            skipped_paid += 1
            continue
        if tx.status == TransactionStatus.cancelled:
            continue
        tx.status = TransactionStatus.cancelled
        session.add(tx)
        cancelled += 1

    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    return {"status": "ok", "cancelled": cancelled, "skipped_paid": skipped_paid}


@router.delete("/{transaction_id}/installment-group", response_model=BulkDeleteResult)
def delete_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Exclui (soft) todas as parcelas vivas do grupo atomicamente. Parcelas
    pagas são preservadas para não corromper acertos já feitos."""
    anchor = _get_group_anchor(session, workspace_id, transaction_id, membership)
    siblings = _load_group_siblings(session, workspace_id, anchor)

    now = datetime.datetime.now(datetime.UTC)
    deleted = 0
    skipped_paid = 0
    excluidas: List[int] = []
    for tx in siblings:
        if tx.status == TransactionStatus.paid:
            skipped_paid += 1
            continue
        tx.deleted_at = now
        session.add(tx)
        excluidas.append(tx.id)
        deleted += 1
    liberar = _purge_attachments(session, excluidas)

    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    free_keys(liberar)
    return {"status": "ok", "deleted": deleted, "skipped_paid": skipped_paid}


@router.get("/{transaction_id}/installment-group", response_model=InstallmentGroupRead)
def get_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Resumo do grupo de parcelas para pré-preencher a edição da compra inteira:
    total da compra (soma das parcelas vivas), nº de parcelas, quantas já pagas e
    o título base (sem o sufixo i/N)."""
    # Leitura (não escrita): basta a âncora ser VISÍVEL — não precisa ser minha.
    anchor = get_visible_transaction(session, workspace_id, transaction_id, membership)
    if not anchor.installment_group_id:
        raise HTTPException(status_code=400, detail="Lançamento não é uma compra parcelada")

    # As irmãs não são reescopadas: o grupo é uma unidade (as N parcelas nascem
    # juntas, com o mesmo criador e as mesmas divisões) e só se chega a ele por
    # uma âncora já visível. Filtrar aqui daria um `group_total` parcial, que é
    # pior do que não mostrar — o formulário de edição da compra inteira usa
    # exatamente esse número.
    siblings = _load_group_siblings(session, workspace_id, anchor)
    paid = [t for t in siblings if t.status == TransactionStatus.paid]
    group_total = sum((t.total_amount for t in siblings), Decimal("0"))
    base_title = _strip_installment_suffix(anchor.title)

    return {
        "installment_group_id": anchor.installment_group_id,
        "installments_of": anchor.installments_of,
        "count_live": len(siblings),
        "paid_count": len(paid),
        "group_total": group_total,
        "title": base_title,
        # Definição da compra inteira (formato TransactionRead) p/ o form editar
        "whole": _aggregate_group_whole(siblings, base_title, group_total),
    }


@router.put("/{transaction_id}/installment-group", response_model=TransactionRead)
def update_installment_group(
    workspace_id: int,
    transaction_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Edita a compra parcelada INTEIRA a partir da definição do total da compra
    + nº de parcelas (mesmo corpo do create). Sem parcelas pagas: refaz o grupo
    (refatiando total/nº pelas parcelas). Com parcelas pagas: congela as pagas e
    recalcula só as em aberto para fechar o novo total — sem mudar o nº de
    parcelas nem reduzir o total abaixo do já pago."""
    anchor = _get_group_anchor(session, workspace_id, transaction_id, membership)
    if not anchor.installment_group_id:
        raise HTTPException(status_code=400, detail="Lançamento não é uma compra parcelada")
    if not transaction_in.installments_count or transaction_in.installments_count < 2:
        raise HTTPException(status_code=400, detail="Informe o número de parcelas (mínimo 2)")

    # Título base sem o sufixo "(i/N)" — o motor de parcelas o re-aplica por parcela
    transaction_in = transaction_in.model_copy(update={
        "title": _strip_installment_suffix(transaction_in.title),
        "currency": resolve_currency(session, workspace_id, transaction_in.currency),
    })

    # Cartão efetivo (parcelamento sempre é no crédito — o schema já exige)
    card = None
    if transaction_in.credit_card_id:
        card = session.get(CreditCard, transaction_in.credit_card_id)
        if not card or card.deleted_at or card.owner_user_id != membership.user_id:
            raise HTTPException(status_code=400, detail="Cartão de crédito inválido")

    # Perna de fatura antes da contábil, pelo mesmo motivo do create (ADR 0024)
    stmt_meta = _statement_leg(session, card, transaction_in)
    # Moeda estrangeira: converte o total da compra para BRL (PTAX do dia + IOF)
    transaction_in, conv_meta = _convert_create_to_base(session, workspace_id, transaction_in)

    siblings = _load_group_siblings(session, workspace_id, anchor)
    paid = [t for t in siblings if t.status == TransactionStatus.paid]
    new_count = transaction_in.installments_count
    group_id = anchor.installment_group_id

    if paid:
        paid_sum = sum((t.total_amount for t in paid), Decimal("0"))
        if new_count != anchor.installments_of:
            raise HTTPException(
                status_code=409,
                detail="Há parcelas pagas — reabra-as antes de mudar o número de parcelas.",
            )
        if transaction_in.total_amount < paid_sum:
            # Moeda do workspace, não "R$" fixo (a base é configurável)
            moeda = workspace_base_currency(session, workspace_id)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"O novo total ({moeda} {transaction_in.total_amount}) é menor que o já pago "
                    f"({moeda} {paid_sum}). Reabra as parcelas pagas antes."
                ),
            )
        try:
            first_tx = _recompute_open_installments(
                session, workspace_id, transaction_in, siblings, paid, card, membership,
                conv_meta=conv_meta, stmt_meta=stmt_meta,
            )
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        # Sem parcelas pagas: refaz o grupo do zero (mantendo o group_id). As
        # antigas viram tombstone (soft-delete), como no delete de grupo.
        now = datetime.datetime.now(datetime.UTC)
        old_ids = [t.id for t in siblings]
        for t in siblings:
            t.deleted_at = now
            session.add(t)
        session.flush()
        first_tx = _create_installments(
            session, workspace_id, transaction_in, membership, card,
            group_id=group_id, conv_meta=conv_meta, stmt_meta=stmt_meta,
        )
        session.flush()
        # O recibo é da COMPRA, não da linha: as parcelas antigas viraram
        # tombstone, então os anexos migram para a nova âncora do grupo — senão
        # sumiriam da UI e só ficariam ocupando a cota do workspace.
        for att in session.exec(
            select(Attachment).where(Attachment.transaction_id.in_(old_ids))
        ).all():
            att.transaction_id = first_tx.id
            session.add(att)

    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    session.refresh(first_tx)
    return first_tx


@router.post("/bulk-categorize", response_model=BulkCategorizeResult)
def bulk_categorize(
    workspace_id: int,
    payload: BulkCategorizeRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Aplica uma categoria a várias despesas de uma vez.

    ## Por que a categoria vira um ITEM

    Categoria mora no `TransactionItem`, não na `Transaction` — é o que permite
    dividir uma compra de mercado entre "comida" e "remédio". A esmagadora
    maioria das despesas não tem item nenhum (lançamento simples não cria), e
    para essas o lote **cria** um item que vale o total: sem isso a soma dos
    itens não fecharia com a despesa, e a divisão por item quebraria na primeira
    edição.

    ## O que ele NÃO faz

    Não toca em despesa que já tenha algum item categorizado. Quem separou
    mercado de farmácia na mesma compra fez isso de propósito, e sobrescrever
    seria destruir o trabalho mais cuidadoso da tela em nome do mais grosseiro.
    Elas voltam em `skipped`, para a interface poder dizer "3 de 5".

    O escopo de visibilidade e a permissão de escrita são os mesmos da edição
    individual: passar um id de outro espaço na lista simplesmente não o alcança.
    """
    if not payload.transaction_ids:
        return {"status": "ok", "updated": 0, "skipped": 0}

    # Import local, como no `update_transaction` logo acima: `Category` não é
    # importada no topo deste módulo.
    from app.models.category import Category

    categoria = session.get(Category, payload.category_id)
    if categoria is None or categoria.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    alvos = session.exec(
        scope_transactions(
            select(Transaction).where(
                Transaction.workspace_id == workspace_id,
                Transaction.id.in_(payload.transaction_ids),
                Transaction.deleted_at.is_(None),
            ),
            membership,
        )
    ).all()

    atualizadas = 0
    puladas = 0
    for tx in alvos:
        # Escrita segue a regra individual: membro comum só mexe no que é dele.
        if not can_write(tx.created_by_user_id, membership):
            puladas += 1
            continue
        itens = session.exec(
            select(TransactionItem).where(TransactionItem.transaction_id == tx.id)
        ).all()
        if any(i.category_id is not None for i in itens):
            puladas += 1
            continue
        if itens:
            # Tem item, nenhum categorizado: categoriza os existentes em vez de
            # criar mais um — criar duplicaria o valor da despesa.
            for item in itens:
                item.category_id = payload.category_id
                session.add(item)
        else:
            session.add(TransactionItem(
                transaction_id=tx.id,
                title=tx.title,
                amount=tx.total_amount,
                category_id=payload.category_id,
            ))
        atualizadas += 1

    publish_event(
        session, workspace_id, "transaction.bulk_updated", "transaction",
        None, membership.user_id,
    )
    session.commit()
    return {"status": "ok", "updated": atualizadas, "skipped": puladas}


@router.post("/bulk", response_model=BulkCreateResult)
def bulk_create_transactions(
    workspace_id: int,
    # Mesmo teto do /imports/commit: sem ele um cliente autenticado pedia a
    # criação de milhões de transações numa única transação de banco.
    transactions_in: List[dict] = Body(..., max_length=settings.IMPORT_MAX_ROWS),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    base_currency = workspace_base_currency(session, workspace_id)
    created_count = 0
    skipped = []
    for index, tx_data in enumerate(transactions_in):
        # Linha inválida (valor não-numérico, data malformada, valor <= 0)
        # é pulada COM MOTIVO (ADR 0008) — nunca derruba o import com 500
        title = str(tx_data.get("title") or "Imported Transaction")[:200]
        try:
            amount = Decimal(str(tx_data.get("total_amount", "0.00")))
        except (ArithmeticError, TypeError):
            skipped.append({"index": index, "title": title, "reason": "valor não é um número válido"})
            continue
        if amount <= 0:
            skipped.append({"index": index, "title": title, "reason": "valor deve ser positivo"})
            continue
        try:
            dt_str = tx_data.get("transaction_date")
            dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00")) if dt_str else datetime.datetime.now(datetime.UTC)
        except (ValueError, AttributeError, TypeError):
            skipped.append({"index": index, "title": title, "reason": "data inválida"})
            continue

        db_transaction = Transaction(
            title=title,
            total_amount=amount,
            transaction_date=dt,
            # Sem billing_month a transação some do histórico filtrado por mês
            billing_month=month_key_local(dt),
            workspace_id=workspace_id,
            created_by_user_id=membership.user_id,
            # Moeda-base do workspace, não "BRL" fixo: com o literal, TODA linha
            # importada num workspace em outra moeda caía fora das agregações
            # (que filtram `currency == base`) e sumia sem aviso.
            currency=base_currency,
            status="confirmed",
            # Lote é IMPORTAÇÃO de fatos passados (ADR 0029): a linha descreve
            # algo que já aconteceu, então nasce liquidada na própria data.
            # Deixá-la a pagar encheria Contas a pagar com o histórico inteiro
            # de quem sobe um extrato.
            settled_at=resolve_settled_at(
                session, workspace_id, transaction_date=dt, explicit=True
            ),
        )
        session.add(db_transaction)
        session.flush() # Get ID

        # Default Payer: Current User
        db_payer = TransactionPayer(
            transaction_id=db_transaction.id,
            user_id=membership.user_id,
            amount=amount
        )
        session.add(db_payer)

        # Default Split: 100% to Current User
        db_split = TransactionSplit(
            transaction_id=db_transaction.id,
            user_id=membership.user_id,
            split_method=SplitMethod.equal,
            input_value=Decimal("100"),
            computed_amount=amount
        )
        session.add(db_split)
        created_count += 1

    # Import em massa emite UM evento agregado (evita tempestade de refetch)
    if created_count:
        publish_event(session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id)
    session.commit()
    return {
        "status": "ok",
        "created": created_count,
        "skipped": len(skipped),
        "skipped_details": skipped,
    }
