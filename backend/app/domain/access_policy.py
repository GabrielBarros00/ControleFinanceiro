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

**E os dois só governam dado DO WORKSPACE** (ADR 0021). Cartão, conta,
financiamento e renda são da PESSOA: não têm `workspace_id`, não aparecem em
consulta escopada por workspace e o único gate deles é `personal_scope` —
`full_workspace` não os alcança em papel nenhum. A Onda 2 tentou o meio-termo
(recurso no workspace + tabela de compartilhamento com nível `use`/`full`) e o
nível `full` nunca chegou a ser consultado: todo cartão compartilhado entregava
limite e fatura inteira a quem tivesse acesso completo no destino. Privacidade que
depende de cada endpoint lembrar de filtrar é privacidade que uma auditoria
encontra quebrada.

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
    "assert_can_write",
    "assert_owns",
    "can_write",
    "effective_access",
    "get_visible_transaction",
    "has_full_access",
    "involved_transaction_ids",
    "involvement_filter",
    "owner_scope",
    "owner_scope_for",
    "participant_scope",
    "personal_scope",
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
    """Predicado de leitura para recurso DO WORKSPACE com dono declarado: tudo com
    acesso completo, só o meu sem ele.

    Vale para o que continua morando no workspace — recorrência de despesa e meta
    de orçamento. **Não** vale para recurso pessoal: use `personal_scope`, que não
    abre para `full_workspace` (ADR 0021).
    """
    return owner_scope_for(column, None if has_full_access(membership) else membership.user_id)


def shared_or_mine_scope(column, membership):
    """Predicado para recurso DO WORKSPACE cujo dono `NULL` significa "da casa".

    Sobrou um caso depois do ADR 0021: `RecurringExpense`. O aluguel que todos
    rateiam é da casa e nasce sem dono; a assinatura que só uma pessoa paga tem
    dono. Cartão e conta também tinham dono opcional e NÃO estão mais aqui — o
    `None` deles significava "conta bancária de todo mundo", que era a modelagem
    dizendo o contrário do que o usuário esperava.

    Note a assimetria deliberada com `can_write`: a linha sem dono é VISÍVEL a
    todos e alterável só por `admin+`. Ver é inofensivo; mexer no que não tem dono
    declarado é o que fazia de todo registro legado um registro de todo mundo.
    """
    if has_full_access(membership):
        return true()
    return or_(column.is_(None), column == membership.user_id)


def personal_scope(column, user_id: int):
    """Predicado de leitura de RECURSO PESSOAL: só o dono, e ponto (ADR 0021).

    Renda, cartão, conta e financiamento não têm `workspace_id` e não são
    alcançáveis por consulta de workspace nenhuma. Este predicado é o único gate
    deles, e **não consulta `financial_access`** — a assimetria é a lição da
    auditoria da Onda 4:

        `financial_access=full_workspace` governa dado DO WORKSPACE
        (total da casa, lançamento alheio, composição por categoria).
        Recurso pessoal ele NÃO alcança, em nenhum papel.

    A versão anterior (`owner_scope`) devolvia `true()` para quem tinha acesso
    completo, e era assim que um `admin` continuava lendo limite, fatura e compras
    do cartão de outra pessoa. Trocar o modelo sem trocar o predicado teria
    reaberto o vazamento por baixo.
    """
    return column == user_id


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

def assert_owns(owner_user_id: Optional[int], user_id: int, *, detail: str = "Não encontrado"):
    """404 quando o RECURSO PESSOAL não é meu (ADR 0021).

    Par de `personal_scope` para o acesso por id. Não recebe `membership` de
    propósito: não há papel nem acesso financeiro que responda por recurso pessoal,
    e aceitar o parâmetro convidaria a consultá-lo.

    404 e não 403 — 403 confirmaria que o cartão existe, e a existência já vaza.
    """
    if owner_user_id != user_id:
        raise HTTPException(status_code=404, detail=detail)


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
