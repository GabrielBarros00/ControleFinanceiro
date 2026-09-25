from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from typing import List, Optional
from decimal import Decimal
import math
import datetime

from app.schemas.common import DeleteResult, StatusRead
from app.db.session import get_session
from app.domain.access_policy import (
    get_visible_transaction,
    scope_transactions,
)
from app.domain.dates import month_key_local
from app.domain.settlement import resolve_settled_at
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionItem,
    TransactionStatus,
    SplitMethod,
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
    TransactionPreviewRead,
    TransactionRead,
    TransactionUpdate,
    TransactionListResponse,
)
from app.api.deps import get_workspace_membership, require_role
from app.core.config import settings
from app.domain.query_policy import (
    REALIZED_STATUSES,
    workspace_base_currency,
)
from app.models.tag import TransactionTagLink
from app.services.attachment_storage import free_keys
from app.services.event_service import publish_event
from app.services.transaction_service import (
    compute_transaction_breakdown,
)
from app.services.recurring_service import RecurringMaterializationService

from app.services.commands import transactions as tx_cmd
from app.services.commands.transactions import (  # usados pelas rotas de leitura daqui
    _aggregate_group_whole,
    _load_group_siblings,
    _strip_installment_suffix,
)

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


@_tambem_sem_barra("post", response_model=TransactionRead)
@router.post("/", response_model=TransactionRead)
def create_transaction(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    transaction_in: TransactionCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    tx = tx_cmd.create_transaction(session, workspace_id, transaction_in, membership)
    session.commit()
    session.refresh(tx)
    return tx


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
    # Os de um estabelecimento (ADR 0038).
    merchant_id: Optional[int] = None,
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

    if merchant_id:
        statement = statement.where(Transaction.merchant_id == merchant_id)

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
    tx = tx_cmd.update_transaction(session, workspace_id, transaction_id, transaction_in, membership)
    session.commit()
    session.refresh(tx)
    return tx


@router.delete("/{transaction_id}", response_model=DeleteResult)
def delete_transaction(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    resultado, liberar = tx_cmd.delete_transaction(session, workspace_id, transaction_id, membership)
    session.commit()
    # Blobs só DEPOIS do commit: se o commit falhasse, o anexo continuaria
    # referenciado e o arquivo já teria sumido.
    free_keys(liberar)
    return resultado


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
    resultado = tx_cmd.restore_transaction(session, workspace_id, transaction_id, membership)
    session.commit()
    return resultado


@router.post("/{transaction_id}/installment-group/cancel", response_model=InstallmentGroupCancelResult)
def cancel_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Cancela TODAS as parcelas vivas do grupo de uma vez (mantém histórico).
    Parcelas já pagas são preservadas — só reabrindo antes."""
    resultado = tx_cmd.cancel_installment_group(session, workspace_id, transaction_id, membership)
    session.commit()
    return resultado


@router.delete("/{transaction_id}/installment-group", response_model=BulkDeleteResult)
def delete_installment_group(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Exclui (soft) todas as parcelas vivas do grupo atomicamente. Parcelas
    pagas são preservadas para não corromper acertos já feitos."""
    resultado, liberar = tx_cmd.delete_installment_group(session, workspace_id, transaction_id, membership)
    session.commit()
    # Blobs só DEPOIS do commit: se o commit falhasse, o anexo continuaria
    # referenciado e o arquivo já teria sumido.
    free_keys(liberar)
    return resultado


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
    tx = tx_cmd.update_installment_group(session, workspace_id, transaction_id, transaction_in, membership)
    session.commit()
    session.refresh(tx)
    return tx


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
    resultado = tx_cmd.bulk_categorize(session, workspace_id, payload, membership)
    session.commit()
    return resultado


@router.post("/bulk", response_model=BulkCreateResult)
def bulk_create_transactions(
    workspace_id: int,
    # Mesmo teto do /imports/commit: sem ele um cliente autenticado pedia a
    # criação de milhões de transações numa única transação de banco.
    transactions_in: List[dict] = Body(..., max_length=settings.IMPORT_MAX_ROWS),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    from app.services.commands import merchants as merchant_cmd

    base_currency = workspace_base_currency(session, workspace_id)
    # Estabelecimento pelo apelido do título (ADR 0038), como na importação: o
    # mapa é lido uma vez para o lote inteiro.
    chaves = merchant_cmd.mapa_de_chaves(session, workspace_id)
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
        estabelecimento = merchant_cmd.do_titulo(session, workspace_id, title, chaves)
        db_transaction.merchant_id = estabelecimento.id if estabelecimento else None
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
