"""Política única de VISIBILIDADE financeira dentro de um workspace (ADR 0018).

Irmã de `query_policy.py`: lá se decide o que é "realizado" e em que moeda; aqui
se decide QUEM PODE VER cada linha. Toda leitura escopada passa por este módulo —
nunca por um filtro local.

O problema que este arquivo existe para resolver: até a Onda 5, `deps.py` tinha
duas funções e era toda a autorização do sistema. `get_workspace_membership` é
satisfeito por QUALQUER papel (inclusive `viewer`) e era o gate de praticamente
todo GET; cada listagem filtrava `workspace_id + deleted_at` e mais nada. Ou
seja: quem entrava no workspace por convite lia o salário dos outros, os
lançamentos individuais de quem não o envolveu, os anexos desses lançamentos, os
cartões e os totais da casa. Papel controlava a ESCRITA e não protegia a LEITURA.

Dois conceitos, de propósito separados:

- **Papel** (`WorkspaceRole`): o que eu posso FAZER (viewer < member < admin < owner).
- **Acesso financeiro** (`FinancialAccess`): o que eu posso VER.

Um `member` que lança as próprias despesas não precisa ver o extrato inteiro da
casa; um `viewer` contador pode precisar. As duas dimensões não se derivam uma da
outra, então são colunas distintas.

Regra de resposta: o que não é visível responde **404**, não 403. 403 confirmaria
que o registro existe — e a existência já é informação (quantos lançamentos o
outro tem, se aquele cartão é dele).
"""
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy import or_, true
from sqlmodel import select

from app.models.transaction import (
    Transaction,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
)
from app.models.workspace import FinancialAccess, WorkspaceRole, role_level

# Reexportado de propósito: quem faz política importa daqui, não do model.
__all__ = [
    "FinancialAccess",
    "assert_can_read",
    "accounts_of_workspace",
    "assert_can_write",
    "can_write",
    "card_full_access_here",
    "card_scope",
    "cards_of_workspace",
    "financings_of_workspace",
    "effective_access",
    "get_visible_transaction",
    "has_full_access",
    "income_of_workspace",
    "income_visible_to",
    "involved_transaction_ids",
    "involvement_filter",
    "owner_scope",
    "owner_scope_for",
    "participant_scope",
    "scope_transactions",
    "shared_or_mine_scope",
    "transaction_scope",
]

def effective_access(membership) -> FinancialAccess:
    """Acesso REAL do membro: o cargo pode sobrepor o que está gravado na coluna.

    `admin` e `owner` têm acesso completo por natureza do cargo e não podem ser
    rebaixados: quem administra membros, cadastros e auditoria precisa dos números
    da casa para fazer o trabalho, e o dono não pode se trancar fora do próprio
    workspace.

    Ler a coluna crua em vez de chamar isto é o modo de falha óbvio — um owner com
    `involved_only` no banco (linha antiga, import, teste) perderia a visão da
    própria casa.
    """
    if role_level(membership.role) >= role_level(WorkspaceRole.admin):
        return FinancialAccess.full_workspace
    valor = getattr(membership, "financial_access", None)
    if isinstance(valor, FinancialAccess):
        return valor
    # Coluna vinda do banco é string; valor desconhecido fecha (não abre).
    return (
        FinancialAccess.full_workspace
        if str(valor) == FinancialAccess.full_workspace.value
        else FinancialAccess.involved_only
    )


def has_full_access(membership) -> bool:
    """Atalho legível para o `if` que decide entre número da casa e número meu."""
    return effective_access(membership) is FinancialAccess.full_workspace


def involvement_filter(user_id: int):
    """Predicado SQL: transações em que `user_id` está ENVOLVIDO.

    Envolvido = criou, OU pagou, OU tem divisão direta, OU participa da divisão
    de algum item.

    `or_` de SUBQUERIES, nunca `join`: join com as tabelas de participação
    multiplicaria a linha (uma transação com dois pagadores apareceria duas vezes
    e contaria 2 no total). É o mesmo defeito que o filtro de categoria em
    `transactions.py` já documenta e resolve com `.distinct()` — aqui a subquery
    evita o problema na origem, e de graça, porque a contagem e a soma da listagem
    derivam da MESMA statement.

    O ramo de `TransactionItemShare` é redundante hoje: divisão por item deriva
    `TransactionSplit` (`item_split_service.derive_transaction_splits`), então
    quem tem share tem split. Ele fica aqui para a política não passar a depender
    dessa derivação continuar existindo — o custo é uma subquery a mais e o
    benefício é não haver um caminho silencioso de vazamento se ela mudar.
    """
    return or_(
        Transaction.created_by_user_id == user_id,
        Transaction.id.in_(
            select(TransactionPayer.transaction_id).where(TransactionPayer.user_id == user_id)
        ),
        Transaction.id.in_(
            select(TransactionSplit.transaction_id).where(TransactionSplit.user_id == user_id)
        ),
        Transaction.id.in_(
            select(TransactionItem.transaction_id)
            .join(TransactionItemShare, TransactionItemShare.item_id == TransactionItem.id)
            .where(TransactionItemShare.user_id == user_id)
        ),
    )


def transaction_scope(membership):
    """Predicado de leitura de transações para ESTE membro.

    Devolve `true()` com acesso completo em vez de `None`, para que o chamador
    aplique `.where(transaction_scope(m))` SEMPRE, sem `if`. Um `if` por endpoint
    é um lugar a mais para esquecer — e esquecer aqui é vazar.
    """
    if has_full_access(membership):
        return true()
    return involvement_filter(membership.user_id)


def scope_transactions(statement, membership):
    """Aplica `transaction_scope` a uma statement de `Transaction`."""
    return statement.where(transaction_scope(membership))


def owner_scope_for(column, user_id: Optional[int]):
    """Variante de `owner_scope` para os SERVIÇOS, que recebem `user_id` cru em vez
    do membership. `None` = sem recorte (acesso completo)."""
    if user_id is None:
        return true()
    return column == user_id


def owner_scope(column, membership):
    """Predicado de leitura para recurso com dono único (renda, cartão, conta,
    financiamento, recorrência): tudo com acesso completo, só o meu sem ele."""
    return owner_scope_for(column, None if has_full_access(membership) else membership.user_id)


def shared_or_mine_scope(column, membership):
    """Predicado para recurso cujo dono `NULL` significa "da casa".

    Conta de pagamento e recorrência têm dono OPCIONAL: sem dono, a linha é da
    casa e todo mundo precisa vê-la (é a conta de onde saem as despesas comuns, é
    o aluguel que todos rateiam). É a mesma forma que `/estimates` já usava à mão
    para separar meta da casa de meta pessoal (ADR 0017).

    Note a assimetria deliberada com `can_write`: a linha sem dono é VISÍVEL a
    todos e alterável só por `admin+`. Ver é inofensivo; mexer no que não tem dono
    declarado é o que fazia de todo registro legado um registro de todo mundo.
    """
    if has_full_access(membership):
        return true()
    return or_(column.is_(None), column == membership.user_id)


def income_of_workspace(workspace_id: int):
    """Renda que compõe o orçamento DAQUELE workspace (ADR 0019).

    Duas origens: a renda da CASA (`workspace_id` preenchido — aluguel de imóvel
    compartilhado, receita conjunta) e a renda PESSOAL que o dono compartilhou
    explicitamente. Renda pessoal não compartilhada nunca entra: ela é do dono e
    aparece só no recorte pessoal dele.

    Subquery, não join — o join com a tabela de compartilhamento duplicaria a
    linha e a renda seria somada duas vezes no total da casa.
    """
    from app.models.income import Income, IncomeWorkspaceShare

    return or_(
        Income.workspace_id == workspace_id,
        Income.id.in_(
            select(IncomeWorkspaceShare.income_id).where(
                IncomeWorkspaceShare.workspace_id == workspace_id
            )
        ),
    )


def income_visible_to(workspace_id: int, membership):
    """Renda que ESTE membro pode ler na tela de um workspace.

    A minha (global, venha de onde vier — é o ponto da renda pessoal) mais, com
    acesso completo, a da casa. Sem acesso completo, a renda dos outros não existe:
    salário é o dado mais sensível do sistema.
    """
    from app.models.income import Income

    minha = Income.user_id == membership.user_id
    if not has_full_access(membership):
        return minha
    return or_(minha, income_of_workspace(workspace_id))


def cards_of_workspace(workspace_id: int):
    """Cartões disponíveis NESTE workspace: os dele + os pessoais compartilhados.

    O cartão continua morando num workspace (`CreditCard.workspace_id`), e o
    compartilhamento estende o alcance sem duplicar o cadastro — que era o que
    fazia a MESMA fatura ser contada duas vezes no Endividamento (ADR 0019).
    """
    from app.models.credit_card import CardWorkspaceAccess, CreditCard

    return or_(
        CreditCard.workspace_id == workspace_id,
        CreditCard.id.in_(
            select(CardWorkspaceAccess.card_id).where(
                CardWorkspaceAccess.workspace_id == workspace_id
            )
        ),
    )


def card_full_access_here(workspace_id: int):
    """Cartões cuja FATURA INTEIRA este workspace pode ver.

    O cartão da casa e o compartilhado com `access='full'`. Compartilhado como
    `use` fica de fora: o workspace lança compras nele e vê o próprio subtotal,
    mas limite e fatura continuam sendo do dono.
    """
    from app.models.credit_card import CardAccessLevel, CardWorkspaceAccess, CreditCard

    return or_(
        CreditCard.workspace_id == workspace_id,
        CreditCard.id.in_(
            select(CardWorkspaceAccess.card_id)
            .where(CardWorkspaceAccess.workspace_id == workspace_id)
            .where(CardWorkspaceAccess.access == CardAccessLevel.full)
        ),
    )


def accounts_of_workspace(workspace_id: int):
    """Contas de pagamento disponíveis neste workspace: as dele + as compartilhadas."""
    from app.models.payment_account import PaymentAccount, PaymentAccountWorkspaceShare

    return or_(
        PaymentAccount.workspace_id == workspace_id,
        PaymentAccount.id.in_(
            select(PaymentAccountWorkspaceShare.account_id).where(
                PaymentAccountWorkspaceShare.workspace_id == workspace_id
            )
        ),
    )


def financings_of_workspace(workspace_id: int):
    """Financiamentos que compõem o endividamento deste workspace."""
    from app.models.financing import Financing, FinancingWorkspaceShare

    return or_(
        Financing.workspace_id == workspace_id,
        Financing.id.in_(
            select(FinancingWorkspaceShare.financing_id).where(
                FinancingWorkspaceShare.workspace_id == workspace_id
            )
        ),
    )


def card_scope(workspace_id: int, membership):
    """Predicado de leitura de cartões: o meu, o da casa, ou aquele em que eu comprei.

    Três ramos, cada um por um motivo:

    1. `owner_user_id == eu` — é meu cartão.
    2. `owner_user_id IS NULL` — cartão compartilhado legado (ver `CreditCard`):
       esconder o que sempre foi de todos quebraria workspace em uso.
    3. tenho compra nele — caso legítimo de precisar achar em que fatura caiu a
       minha despesa, mesmo sendo cartão de outra pessoa.

    O ramo 3 ainda expõe limite e total comprometido do dono; separar "usar" de
    "ver a fatura inteira" é o que `CardWorkspaceAccess` resolve na Onda 2.
    """
    if has_full_access(membership):
        return true()
    from app.models.credit_card import CreditCard

    return or_(
        CreditCard.owner_user_id == membership.user_id,
        CreditCard.owner_user_id.is_(None),
        CreditCard.id.in_(
            select(Transaction.credit_card_id)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.credit_card_id.is_not(None))
            .where(involvement_filter(membership.user_id))
        ),
    )


def participant_scope(columns: Iterable, membership):
    """Predicado para recurso com DOIS lados (acerto: quem paga e quem recebe)."""
    if has_full_access(membership):
        return true()
    return or_(*[coluna == membership.user_id for coluna in columns])


def involved_transaction_ids(session, workspace_id: int, membership):
    """IDs das transações visíveis ao membro no workspace — para escopar tabelas
    FILHAS (anexos, itens, parcelas) sem repetir o predicado de envolvimento.

    Devolve `None` quando o acesso é completo, sinalizando "não precisa filtrar":
    materializar a lista inteira de IDs de um workspace grande só para depois
    ignorá-la seria desperdício.
    """
    if has_full_access(membership):
        return None
    return session.exec(
        select(Transaction.id)
        .where(Transaction.workspace_id == workspace_id)
        .where(involvement_filter(membership.user_id))
    ).all()


def get_visible_transaction(
    session,
    workspace_id: int,
    transaction_id: int,
    membership,
    *,
    detail: str = "Lançamento não encontrado",
):
    """Transação do workspace visível a ESTE membro, ou 404.

    Junta as três verificações que antes viviam soltas e repetidas — workspace,
    soft-delete e agora envolvimento — num lugar só. Vale sobretudo para os
    ANEXOS: `attachments.py` resolvia a transação por workspace e nada mais, então
    o recibo de um lançamento alheio era servido a qualquer membro. Passando por
    aqui, o anexo herda a visibilidade do lançamento de graça, em upload, listagem
    e download.
    """
    statement = (
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .where(Transaction.workspace_id == workspace_id)
        .where(Transaction.deleted_at.is_(None))
        .where(transaction_scope(membership))
    )
    transacao = session.exec(statement).first()
    if not transacao:
        raise HTTPException(status_code=404, detail=detail)
    return transacao


# ---------------------------------------------------------------------------
# Guardas de registro único
# ---------------------------------------------------------------------------

def assert_can_read(owner_user_id: Optional[int], membership, *, detail: str = "Não encontrado"):
    """404 quando o registro existe mas não é meu e eu não tenho acesso completo.

    404 e não 403: 403 confirma a existência, e a existência já vaza (quantos
    lançamentos o outro tem, se aquele cartão é dele).
    """
    if has_full_access(membership):
        return
    if owner_user_id != membership.user_id:
        raise HTTPException(status_code=404, detail=detail)


def can_write(
    owner_user_id: Optional[int], membership, *, null_is_shared: bool = False
) -> bool:
    """`admin+` altera qualquer registro; `member` só o próprio.

    O que fazer com `owner_user_id is None` depende do que o `None` SIGNIFICA na
    tabela, e as duas coisas existem aqui:

    - **Autoria perdida** (`Transaction.created_by_user_id`, `Attachment`,
      `Settlement`): é registro pessoal cujo autor não foi gravado. Exige `admin+`
      — `null_is_shared=False`, o padrão. Antes, seis rotas usavam
      `not in (None, membership.user_id)`, o que fazia de TODO registro sem autoria
      um registro de todo mundo, editável e apagável por qualquer member.

    - **Recurso da casa** (`CreditCard.owner_user_id`, `PaymentAccount`,
      `RecurringExpense`): o `None` é a modelagem dizendo "isto é compartilhado",
      não um dado faltando. Exige `null_is_shared=True`, e qualquer member mexe —
      que é o comportamento de sempre e não é o vazamento que estamos fechando.

    A distinção é explícita justamente porque, implícita, ela era um bug.
    """
    if role_level(membership.role) >= role_level(WorkspaceRole.admin):
        return True
    if owner_user_id is None:
        return null_is_shared
    return owner_user_id == membership.user_id


def assert_can_write(
    owner_user_id: Optional[int],
    membership,
    *,
    detail: str = "Você só pode alterar os próprios registros",
    null_is_shared: bool = False,
):
    """Forma ÚNICA da trava de autoria em mutações.

    Substitui os quatro formatos que existiam espalhados por sete arquivos, cada
    um apoiado numa coluna diferente (`user_id`, `created_by_user_id`,
    `uploaded_by_user_id`, `from_user_id`) e com regras sutilmente distintas para
    o caso `None`.
    """
    if not can_write(owner_user_id, membership, null_is_shared=null_is_shared):
        raise HTTPException(status_code=403, detail=detail)
