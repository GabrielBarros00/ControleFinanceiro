"""Comandos da despesa RECORRENTE do espaço (ADR 0012/0030/0032).

Movidos de `api/routes/recurring.py` sem mudança de regra (ADR 0035): só o
`commit` saiu — quem chama (rota REST ou pipeline do MCP) comanda a transação.
"""
from datetime import date
from typing import List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.domain.access_policy import assert_can_read, assert_can_write
from app.domain.query_policy import resolve_currency
from app.domain.recurrence_rules import validate_frequency_fields as _validate_frequency_fields
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.recurring import RecurringExpense
from app.models.transaction import PaymentMethod, Transaction, TransactionStatus
from app.models.workspace import WorkspaceMembership
from app.schemas.recurring import RecurringCreate, RecurringSplitEntry, RecurringUpdate
from app.services.event_service import publish_event
from app.services.recurring_service import (
    EDIT_SCOPES,
    MATERIALIZE_SCOPES,
    RecurringMaterializationService,
    RecurringService,
)


def _get_recurring_or_404(
    session: Session, workspace_id: int, recurring_id: int, membership: WorkspaceMembership
) -> RecurringExpense:
    db_recurring = session.get(RecurringExpense, recurring_id)
    if not db_recurring or db_recurring.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Despesa recorrente não encontrada")
    # Template sem criador é da casa e todos veem; com criador, só o dono
    if db_recurring.created_by_user_id is not None:
        assert_can_read(
            db_recurring.created_by_user_id,
            membership,
            detail="Despesa recorrente não encontrada",
        )
    return db_recurring


def _check_ownership(membership: WorkspaceMembership, template: RecurringExpense) -> None:
    """Member mexe só no que é dele; admin+ mexe em tudo.

    Mesmo gate de transações, rendas, acertos e anexos — a recorrência era a
    única entidade em que qualquer member editava ou apagava template alheio.
    """
    assert_can_write(
        template.created_by_user_id,
        membership,
        detail="Você só pode alterar as próprias despesas recorrentes",
        # Template sem criador é o gasto fixo da casa (aluguel, luz), não autoria
        # perdida de um lançamento pessoal
        null_is_shared=True,
    )


def _validate_snapshot(
    session: Session,
    workspace_id: int,
    category_id: Optional[int],
    payer_user_id: Optional[int],
    split_snapshot: Optional[List[RecurringSplitEntry]],
    credit_card_id: Optional[int] = None,
    payment_method: Optional[PaymentMethod] = None,
    *,
    actor_user_id: Optional[int] = None,
    statement_shift: int = 0,
) -> None:
    if category_id is not None:
        category = session.get(Category, category_id)
        if not category or category.workspace_id != workspace_id or category.deleted_at:
            raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")
    if credit_card_id is not None:
        card = session.get(CreditCard, credit_card_id)
        # Cartão é pessoal (ADR 0021): tem de ser de quem vai pagar a recorrência
        # — o pagador declarado, ou quem está cadastrando quando não há um.
        dono_esperado = payer_user_id if payer_user_id is not None else actor_user_id
        if not card or card.deleted_at or card.owner_user_id != dono_esperado:
            raise HTTPException(status_code=400, detail="Cartão de crédito inválido")
        # Mesma regra da despesa avulsa: cartão só faz sentido no crédito, senão
        # a instância cairia numa fatura sem ter sido comprada no cartão
        if payment_method != PaymentMethod.credit_card:
            raise HTTPException(
                status_code=400,
                detail="Cartão de crédito só se aplica à forma de pagamento 'credit_card'",
            )
    else:
        # A guarda que faltava, e o caminho contrário da de cima.
        #
        # `validate_payment_method` (schemas/transaction.py) recusa
        # `credit_card` sem cartão na despesa avulsa — mas ela vive na rota de
        # LANÇAMENTO, e a ocorrência materializada não passa por lá: o
        # `RecurringService` monta o `Transaction` direto. Sem esta linha, um
        # template inconsistente gera todo mês um lançamento que se diz "no
        # cartão", não entra em fatura nenhuma (não há cartão) e ainda cai em
        # Contas a pagar, de onde o ADR 0029 exclui a compra no cartão.
        #
        # Foi encontrado numa varredura de telas com a base cheia: "Contas a
        # pagar" listando uma despesa etiquetada "Cartão de crédito".
        if payment_method == PaymentMethod.credit_card:
            raise HTTPException(
                status_code=400,
                detail="Recorrência no cartão de crédito exige um cartão (credit_card_id)",
            )
        if statement_shift:
            # Mesma guarda da despesa avulsa (`validate_statement_shift`): sem
            # cartão não há fatura para deslocar, e aceitar o valor calado
            # deixaria um deslocamento adormecido que acordaria ao vincular um
            # cartão depois.
            raise HTTPException(
                status_code=400,
                detail="Deslocamento de fatura exige uma recorrência no cartão (credit_card_id)",
            )
    member_ids = set(session.exec(
        select(WorkspaceMembership.user_id).where(WorkspaceMembership.workspace_id == workspace_id)
    ).all())
    users = set()
    if payer_user_id is not None:
        users.add(payer_user_id)
    for entry in split_snapshot or []:
        users.add(entry.user_id)
    outsiders = users - member_ids
    if outsiders:
        raise HTTPException(
            status_code=400,
            detail=f"Usuário(s) {sorted(outsiders)} não pertence(m) a este workspace",
        )


def _snapshot_json(split_snapshot: Optional[List[RecurringSplitEntry]]):
    if not split_snapshot:
        return None
    return [e.model_dump(mode="json") for e in split_snapshot]


def _resolve_end_date(data: dict, template) -> None:
    """"Por N ocorrências" vira `end_date`, in place (ADR 0030).

    A conversão precisa do template com os campos JÁ atualizados — o fim de "por
    144 vezes" depende da frequência, do intervalo e do dia, e todos podem estar
    mudando na mesma requisição. Por isso roda depois dos `setattr`/da montagem.

    Persistimos só `end_date`: guardar as duas formas criaria duas verdades sobre
    quando a série acaba, e elas divergiriam na primeira edição de frequência.
    """
    quantas = data.pop("end_after_occurrences", None)
    if quantas is None:
        return
    fim = RecurringService.end_date_after(template, quantas)
    if fim is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Não foi possível calcular o fim para {quantas} ocorrências — "
                "revise a data de início e a frequência"
            ),
        )
    data["end_date"] = fim


def create_recurring(
    session: Session,
    workspace_id: int,
    recurring_in: RecurringCreate,
    membership: WorkspaceMembership,
    materialize: str = "current",
) -> RecurringExpense:
    if materialize not in MATERIALIZE_SCOPES:
        raise HTTPException(status_code=400, detail=f"materialize deve ser um de {list(MATERIALIZE_SCOPES)}")
    if recurring_in.is_subscription and recurring_in.trial_ends_on and recurring_in.start_date is None:
        # Assinatura em teste grátis sem início declarado (ADR 0039): a primeira
        # cobrança é no fim do teste, e nada nasce cobrado antes dele.
        recurring_in = recurring_in.model_copy(update={"start_date": recurring_in.trial_ends_on})
    _validate_frequency_fields(
        recurring_in.frequency, recurring_in.day_of_week, recurring_in.month_of_year,
        recurring_in.interval, recurring_in.start_date, recurring_in.end_date,
    )
    _validate_snapshot(
        session, workspace_id,
        recurring_in.category_id, recurring_in.payer_user_id, recurring_in.split_snapshot,
        recurring_in.credit_card_id, recurring_in.payment_method,
        actor_user_id=membership.user_id,
        statement_shift=recurring_in.statement_shift,
    )
    from app.services.commands.merchants import resolve_merchant

    # Como no lançamento novo (ADR 0038): o id, o nome (acha ou cria) ou, sem
    # nenhum, o de apelido igual ao título — as ocorrências herdam.
    estabelecimento = resolve_merchant(
        session, workspace_id, membership, merchant_id=recurring_in.merchant_id,
        merchant_name=recurring_in.merchant_name, titulo=recurring_in.title,
    )
    data = recurring_in.model_dump(exclude={"split_snapshot", "merchant_name"})
    data["merchant_id"] = estabelecimento.id if estabelecimento else None
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    data["currency"] = resolve_currency(session, workspace_id, recurring_in.currency)
    # "Por N ocorrências" → `end_date`. Antes do construtor: o campo de entrada
    # não é coluna, e passá-lo adiante estouraria com argumento desconhecido.
    _resolve_end_date(data, recurring_in)
    db_recurring = RecurringExpense(
        **data,
        split_snapshot=_snapshot_json(recurring_in.split_snapshot),
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
    )
    session.add(db_recurring)
    session.flush()
    RecurringMaterializationService.apply_scope(
        session, workspace_id, db_recurring, materialize, is_income=False
    )
    publish_event(session, workspace_id, "recurring.created", "recurring", db_recurring.id, membership.user_id)
    return db_recurring


def update_recurring(
    session: Session,
    workspace_id: int,
    recurring_id: int,
    recurring_in: RecurringUpdate,
    membership: WorkspaceMembership,
    *,
    scope: str = "future",
    materialize: str = "current",
    apply_to: Optional[List[int]] = None,
    create_occurrence: Optional[List[date]] = None,
    since: Optional[date] = None,
) -> RecurringExpense:
    if scope not in EDIT_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope deve ser um de {list(EDIT_SCOPES)}")
    if materialize not in MATERIALIZE_SCOPES:
        raise HTTPException(status_code=400, detail=f"materialize deve ser um de {list(MATERIALIZE_SCOPES)}")
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id, membership)
    _check_ownership(membership, db_recurring)

    update_data = recurring_in.model_dump(exclude_unset=True)
    nome = update_data.pop("merchant_name", None)
    if nome or update_data.get("merchant_id") is not None:
        from app.services.commands.merchants import resolve_merchant

        estabelecimento = resolve_merchant(
            session, workspace_id, membership, merchant_id=update_data.get("merchant_id"), merchant_name=nome,
        )
        update_data["merchant_id"] = estabelecimento.id if estabelecimento else None
    # `is_subscription` é NOT NULL: um `null` explícito é "não mexe", não "apaga".
    if "is_subscription" in update_data and update_data["is_subscription"] is None:
        update_data.pop("is_subscription")
    snapshot_provided = "split_snapshot" in update_data
    update_data.pop("split_snapshot", None)
    # `end_after_occurrences` sai daqui e não vira atributo: ele não é coluna, e
    # o `setattr` abaixo gravaria um campo fantasma no objeto do ORM — aceito
    # pelo SQLModel, jamais persistido, e sem erro.
    quantas = update_data.pop("end_after_occurrences", None)
    # `statement_shift` é NOT NULL e o campo de entrada é `Optional[int]` (para
    # "não mexe" ser distinguível de "zera"). Um `null` explícito no corpo cairia
    # no `setattr` abaixo e gravaria None na coluna — IntegrityError no commit,
    # numa rota que só queria editar o título.
    if update_data.get("statement_shift", 0) is None:
        update_data.pop("statement_shift")
    for key, value in update_data.items():
        setattr(db_recurring, key, value)
    # Tirou o cartão NESTA edição: o deslocamento perde o objeto e é zerado, em
    # vez de reprovar em `_validate_snapshot`. A guarda existe contra
    # deslocamento ÓRFÃO, não contra quem está justamente removendo o cartão.
    #
    # A condição é a TRANSIÇÃO (o campo veio no corpo), não "está sem cartão":
    # zerar sempre que não há cartão faria um `statement_shift` enviado para um
    # template sem cartão ser aceito e ignorado em silêncio — exatamente o que a
    # guarda no `_validate_snapshot` existe para transformar em 400.
    if "credit_card_id" in update_data and db_recurring.credit_card_id is None:
        db_recurring.statement_shift = 0
    if snapshot_provided:
        db_recurring.split_snapshot = _snapshot_json(recurring_in.split_snapshot)
    if quantas is not None:
        # Depois dos `setattr`: o fim de "por 144 vezes" depende da frequência,
        # do intervalo e do dia, e os três podem estar mudando nesta requisição.
        resolvido = {"end_after_occurrences": quantas}
        _resolve_end_date(resolvido, db_recurring)
        db_recurring.end_date = resolvido["end_date"]

    # Estado FINAL precisa ser coerente (frequência × campos auxiliares + snapshot)
    _validate_frequency_fields(
        db_recurring.frequency, db_recurring.day_of_week, db_recurring.month_of_year,
        db_recurring.interval, db_recurring.start_date, db_recurring.end_date,
    )
    _validate_snapshot(
        session, workspace_id,
        db_recurring.category_id, db_recurring.payer_user_id, recurring_in.split_snapshot,
        db_recurring.credit_card_id, db_recurring.payment_method,
        actor_user_id=db_recurring.created_by_user_id or membership.user_id,
        # Do TEMPLATE já atualizado (os `setattr` do PUT rodaram acima), e não do
        # corpo: numa edição parcial que só tira o cartão, `recurring_in` não
        # traz `statement_shift` e a guarda passaria por cima do valor herdado.
        statement_shift=db_recurring.statement_shift,
    )

    session.add(db_recurring)
    session.flush()
    if apply_to is not None or create_occurrence is not None:
        # Caminho da REVISÃO (ADR 0030): a pessoa viu a lista e marcou o que
        # ajustar. O plano é recalculado aqui a partir do template JÁ atualizado
        # — `plan` sem `changes`, porque os `setattr` acima já o deixaram no
        # estado futuro. Recalcular (em vez de confiar no que a tela mandou) é o
        # que impede que uma lista velha, aberta há dez minutos, mova um
        # lançamento que outra pessoa pagou nesse meio-tempo: as travas de
        # congelamento correm de novo, agora contra o banco.
        plano = RecurringService.plan(session, db_recurring, since=since)
        RecurringService.apply_plan(
            session, db_recurring, plano,
            apply_to=apply_to, create_occurrences=create_occurrence,
        )
    else:
        # Propaga a mudança às instâncias não pagas conforme o escopo (ADR 0012).
        # Caminho legado: sem revisão, a data continua congelada.
        RecurringService.sync_unpaid_instances(session, db_recurring.id, scope)
    # ...e materializa o que ainda falta conforme o escopo de datas escolhido
    RecurringMaterializationService.apply_scope(
        session, workspace_id, db_recurring, materialize, is_income=False
    )
    publish_event(session, workspace_id, "recurring.updated", "recurring", db_recurring.id, membership.user_id)
    # Instâncias podem ter mudado → invalida caixa/relatórios também
    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    return db_recurring


def delete_recurring(
    session: Session,
    workspace_id: int,
    recurring_id: int,
    membership: WorkspaceMembership,
    cancel_instance: Optional[List[int]] = None,
) -> List[int]:
    """Exclui o template. Os lançamentos já gerados sobrevivem, salvo escolha.

    Movido de `api/routes/recurring.py` sem mudança de regra. O que a pessoa
    marcar em `cancel_instance` é CANCELADO (status terminal), não excluído; paga
    é pulada (ADR 0003). Devolve os ids efetivamente cancelados.
    """
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id, membership)
    _check_ownership(membership, db_recurring)

    # Desvincula instâncias já geradas antes de excluir o template — sem isso
    # a FK transaction.recurring_expense_id viola no Postgres (500)
    instances = session.exec(
        select(Transaction).where(Transaction.recurring_expense_id == recurring_id)
    ).all()
    escolhidos = set(cancel_instance or [])
    cancelados: List[int] = []
    for tx in instances:
        # Cancela ANTES de desvincular: depois do `recurring_expense_id = None` a
        # linha deixa de ser identificável como ocorrência desta recorrência.
        # Paga não se toca (ADR 0003) — ela é pulada, não recusada, senão excluir
        # um template inteiro falharia por causa de um mês já quitado.
        if tx.id in escolhidos and tx.status not in (
            TransactionStatus.paid, TransactionStatus.cancelled
        ):
            tx.status = TransactionStatus.cancelled
            cancelados.append(tx.id)
        tx.recurring_expense_id = None
        session.add(tx)

    session.delete(db_recurring)
    publish_event(session, workspace_id, "recurring.deleted", "recurring", recurring_id, membership.user_id)
    if escolhidos:
        # Cancelar lançamento muda caixa, dívidas e relatórios — o evento de
        # recorrência sozinho não alcança quem está com o extrato aberto.
        publish_event(
            session, workspace_id, "transaction.bulk_updated",
            "transaction", None, membership.user_id,
        )
    session.flush()
    return cancelados
