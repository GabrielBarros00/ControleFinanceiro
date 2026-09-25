"""Comandos de PLANEJAMENTO do espaço: meta do mês e categoria.

Movidos de `api/routes/analytics.py` e `api/routes/categories.py` sem mudança
de regra (ADR 0035): só o `commit` saiu — quem chama (rota REST ou pipeline do
MCP) comanda a transação.
"""
from datetime import datetime, UTC
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.category import Category
from app.models.estimate import MonthlyEstimate
from app.models.tag import Tag, TransactionTagLink
from app.models.workspace import WorkspaceMembership
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.schemas.estimate import MonthlyEstimateCreate
from app.schemas.tag import TagCreate, TagUpdate
from app.services.event_service import publish_event


def _validate_estimate_category(session: Session, workspace_id: int, category_id) -> None:
    if category_id is None:
        return
    from app.models.category import Category
    category = session.get(Category, category_id)
    if not category or category.workspace_id != workspace_id or category.deleted_at:
        raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")


def _ensure_estimate_owner(estimate: MonthlyEstimate, membership: WorkspaceMembership) -> None:
    """Meta PESSOAL só o próprio dono altera ou remove.

    Não é uma questão de papel: é a meta de gasto de uma pessoa, não um número
    do workspace. Admin manda no orçamento da casa; na meta pessoal de outro
    membro, não.
    """
    if estimate.owner_user_id is not None and estimate.owner_user_id != membership.user_id:
        raise HTTPException(
            status_code=403, detail="Esta é a meta pessoal de outro membro"
        )


def _estimate_owner(estimate_in: MonthlyEstimateCreate, membership: WorkspaceMembership):
    """Escopo → dono. `personal` é sempre do PRÓPRIO usuário: ninguém define a
    meta pessoal de outra pessoa (nem admin — é dado dela, não do workspace)."""
    return membership.user_id if estimate_in.scope == "personal" else None


def create_estimate(
    session: Session,
    workspace_id: int,
    estimate_in: MonthlyEstimateCreate,
    membership: WorkspaceMembership,
) -> Tuple[MonthlyEstimate, bool]:
    """Upsert da meta; devolve `(meta, criada)` — `False` quando atualizou uma existente."""
    _validate_estimate_category(session, workspace_id, estimate_in.category_id)
    owner_user_id = _estimate_owner(estimate_in, membership)
    campos = estimate_in.model_dump(exclude={"scope"})

    # Idempotente por (workspace, DONO, category_id, mês). A chave é o
    # category_id (FK), não o rótulo de texto: com o texto, um `category`
    # vazio/constante colapsava TODOS os orçamentos do mês num só, e dois textos
    # diferentes para a mesma categoria criavam duplicatas. O dono entrou junto
    # quando o orçamento ganhou escopo — senão definir a minha meta sobrescreveria
    # a da casa. (`== None` vira `IS NULL` no SQLAlchemy.)
    existing = session.exec(
        select(MonthlyEstimate)
        .where(MonthlyEstimate.workspace_id == workspace_id)
        .where(MonthlyEstimate.owner_user_id == owner_user_id)
        .where(MonthlyEstimate.category_id == estimate_in.category_id)
        .where(MonthlyEstimate.month == estimate_in.month)
        .where(MonthlyEstimate.deleted_at.is_(None))
    ).first()
    if existing:
        for key, value in campos.items():
            setattr(existing, key, value)
        session.add(existing)
        publish_event(session, workspace_id, "estimate.updated", "estimate", existing.id, membership.user_id)
        return existing, False

    db_estimate = MonthlyEstimate(
        **campos,
        workspace_id=workspace_id,
        user_id=membership.user_id,
        owner_user_id=owner_user_id,
    )
    session.add(db_estimate)
    session.flush()
    publish_event(session, workspace_id, "estimate.created", "estimate", db_estimate.id, membership.user_id)
    return db_estimate, True


def update_estimate(
    session: Session,
    workspace_id: int,
    estimate_id: int,
    estimate_in: MonthlyEstimateCreate,
    membership: WorkspaceMembership,
) -> MonthlyEstimate:
    estimate = session.get(MonthlyEstimate, estimate_id)
    if not estimate or estimate.workspace_id != workspace_id or estimate.deleted_at:
        raise HTTPException(status_code=404, detail="Estimativa não encontrada")
    _ensure_estimate_owner(estimate, membership)

    _validate_estimate_category(session, workspace_id, estimate_in.category_id)
    for key, value in estimate_in.model_dump(exclude={"scope"}).items():
        setattr(estimate, key, value)
    session.add(estimate)
    publish_event(session, workspace_id, "estimate.updated", "estimate", estimate.id, membership.user_id)
    return estimate


def create_category(
    session: Session,
    workspace_id: int,
    category_in: CategoryCreate,
    membership: WorkspaceMembership,
) -> Category:
    name = category_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome da categoria é obrigatório")

    # Nome único por workspace; criar com nome de categoria excluída reativa a
    # antiga em vez de bloquear para sempre (CAT-001, mesmo padrão das tags)
    existing = session.exec(
        select(Category).where(Category.workspace_id == workspace_id, Category.name == name)
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail=f"Categoria '{name}' já existe neste workspace")
        existing.deleted_at = None
        existing.color = category_in.color
        existing.icon = category_in.icon
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        category = existing
    else:
        category = Category(
            **{**category_in.model_dump(), "name": name}, workspace_id=workspace_id
        )
        session.add(category)
    session.flush()
    publish_event(session, workspace_id, "category.created", "category", category.id, membership.user_id)
    return category


# ---------------------------------------------------------------------------
# Categoria e tag: editar e excluir (movido de `api/routes/categories.py` e
# `api/routes/tags.py` sem mudança de regra)
# ---------------------------------------------------------------------------

def get_category_or_404(session: Session, workspace_id: int, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if not category or category.workspace_id != workspace_id or category.deleted_at:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return category


def update_category(
    session: Session,
    workspace_id: int,
    category_id: int,
    category_in: CategoryUpdate,
    membership: WorkspaceMembership,
) -> Category:
    category = get_category_or_404(session, workspace_id, category_id)
    update_data = category_in.model_dump(exclude_unset=True)
    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nome da categoria é obrigatório")
        clash = session.exec(
            select(Category).where(
                Category.workspace_id == workspace_id,
                Category.name == name,
                Category.deleted_at.is_(None),
            )
        ).first()
        if clash and clash.id != category.id:
            raise HTTPException(status_code=400, detail=f"Categoria '{name}' já existe neste workspace")
        update_data["name"] = name
    for key, value in update_data.items():
        setattr(category, key, value)
    category.updated_at = datetime.now(UTC)
    session.add(category)
    publish_event(session, workspace_id, "category.updated", "category", category.id, membership.user_id)
    session.flush()
    return category


def delete_category(
    session: Session, workspace_id: int, category_id: int, membership: WorkspaceMembership
) -> Category:
    category = get_category_or_404(session, workspace_id, category_id)
    category.deleted_at = datetime.now(UTC)
    session.add(category)
    publish_event(session, workspace_id, "category.deleted", "category", category.id, membership.user_id)
    session.flush()
    return category


def get_tag_or_404(session: Session, workspace_id: int, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if not tag or tag.workspace_id != workspace_id or tag.deleted_at:
        raise HTTPException(status_code=404, detail="Tag não encontrada")
    return tag


def _tag_name_taken(session: Session, workspace_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
    stmt = select(Tag).where(
        Tag.workspace_id == workspace_id,
        Tag.name == name,
        Tag.deleted_at.is_(None),
    )
    existing = session.exec(stmt).first()
    return existing is not None and existing.id != exclude_id


def create_tag(
    session: Session, workspace_id: int, tag_in: TagCreate, membership: WorkspaceMembership
) -> Tag:
    name = tag_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome da tag é obrigatório")

    # Reativação (TAG-001): criar com nome de tag excluída volta a antiga à vida
    # em vez de bloquear para sempre
    existing = session.exec(
        select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name)
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail=f"Tag '{name}' já existe neste workspace")
        existing.deleted_at = None
        existing.color = tag_in.color
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        tag = existing
    else:
        tag = Tag(workspace_id=workspace_id, name=name, color=tag_in.color)
        session.add(tag)
    session.flush()
    publish_event(session, workspace_id, "tag.created", "tag", tag.id, membership.user_id)
    return tag


def update_tag(
    session: Session, workspace_id: int, tag_id: int, tag_in: TagUpdate, membership: WorkspaceMembership
) -> Tag:
    tag = get_tag_or_404(session, workspace_id, tag_id)
    update_data = tag_in.model_dump(exclude_unset=True)
    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nome da tag é obrigatório")
        if _tag_name_taken(session, workspace_id, name, exclude_id=tag.id):
            raise HTTPException(status_code=400, detail=f"Tag '{name}' já existe neste workspace")
        update_data["name"] = name

    for key, value in update_data.items():
        setattr(tag, key, value)
    tag.updated_at = datetime.now(UTC)
    session.add(tag)
    publish_event(session, workspace_id, "tag.updated", "tag", tag.id, membership.user_id)
    session.flush()
    return tag


def delete_tag(session: Session, workspace_id: int, tag_id: int, membership: WorkspaceMembership) -> Tag:
    tag = get_tag_or_404(session, workspace_id, tag_id)

    # Remove vínculos para a tag não continuar aparecendo nas transações
    for link in session.exec(
        select(TransactionTagLink).where(TransactionTagLink.tag_id == tag.id)
    ).all():
        session.delete(link)

    tag.deleted_at = datetime.now(UTC)
    session.add(tag)
    publish_event(session, workspace_id, "tag.deleted", "tag", tag_id, membership.user_id)
    session.flush()
    return tag
