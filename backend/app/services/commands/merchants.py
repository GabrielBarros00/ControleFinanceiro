"""Comandos do ESTABELECIMENTO (ADR 0038): vocabulário do espaço.

Mesma forma de categoria e tag: nome único no espaço, reativação pelo nome,
exclusão lógica. Um apelido pertence a UM estabelecimento do espaço — senão o
vínculo automático teria dois candidatos para o mesmo título.

O vínculo automático é só por apelido EXATO (normalizado). Parecido não vincula:
a tela e o agente sugerem, a pessoa decide.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Dict, Iterable, List, Optional

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from app.models.category import Category
from app.models.merchant import Merchant, normaliza_estabelecimento
from app.models.recurring import RecurringExpense
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership
from app.schemas.merchant import MerchantCreate, MerchantMerge, MerchantUpdate
from app.services.event_service import publish_event


def list_merchants(session: Session, workspace_id: int) -> List[Merchant]:
    return list(session.exec(
        select(Merchant).where(Merchant.workspace_id == workspace_id, Merchant.deleted_at.is_(None))
        .order_by(Merchant.name, Merchant.id)
    ).all())


def get_merchant_or_404(session: Session, workspace_id: int, merchant_id: int) -> Merchant:
    m = session.get(Merchant, merchant_id)
    if m is None or m.workspace_id != workspace_id or m.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Estabelecimento não encontrado")
    return m


def mapa_de_chaves(session: Session, workspace_id: int) -> Dict[str, Merchant]:
    """Grafia normalizada → estabelecimento, para vincular muitos títulos de uma vez."""
    mapa: Dict[str, Merchant] = {}
    for m in list_merchants(session, workspace_id):
        for chave in m.chaves():
            mapa.setdefault(chave, m)
    return mapa


def do_titulo(session: Session, workspace_id: int, titulo: str,
              mapa: Optional[Dict[str, Merchant]] = None) -> Optional[Merchant]:
    """O estabelecimento cujo nome ou apelido é EXATAMENTE o título (normalizado)."""
    chave = normaliza_estabelecimento(titulo)
    if not chave:
        return None
    return (mapa if mapa is not None else mapa_de_chaves(session, workspace_id)).get(chave)


def pelo_nome(session: Session, workspace_id: int, nome: str) -> Optional[Merchant]:
    """O de nome igual (sem caixa). Vem antes do apelido: um nome que normaliza
    para vazio ("7-11") não tem chave, e sem isto seria recriado a cada uso."""
    alvo = nome.strip().lower()
    return next((m for m in list_merchants(session, workspace_id) if m.name.strip().lower() == alvo), None)


def _apelidos(brutos: Iterable[str]) -> List[str]:
    vistos: List[str] = []
    for a in brutos:
        chave = normaliza_estabelecimento(a)
        if chave and chave not in vistos:
            vistos.append(chave)
    return vistos


def _valida(session: Session, workspace_id: int, m: Merchant) -> None:
    """Nome livre no espaço, apelido de ninguém mais, categoria do espaço."""
    for outro in list_merchants(session, workspace_id):
        if outro.id == m.id:
            continue
        if outro.name.strip().lower() == m.name.strip().lower():
            raise HTTPException(status_code=400, detail=f"Estabelecimento '{m.name}' já existe neste espaço")
        repetidos = m.chaves() & outro.chaves()
        if repetidos:
            raise HTTPException(
                status_code=409,
                detail=f"O apelido '{sorted(repetidos)[0]}' já é do estabelecimento '{outro.name}'. "
                       "Mescle os dois ou tire o apelido de lá.",
            )
    if m.default_category_id is not None:
        categoria = session.get(Category, m.default_category_id)
        if categoria is None or categoria.workspace_id != workspace_id or categoria.deleted_at is not None:
            raise HTTPException(status_code=400, detail="Categoria inválida para este espaço")


def create_merchant(session: Session, workspace_id: int, body: MerchantCreate,
                    membership: WorkspaceMembership) -> Merchant:
    nome = body.name.strip()
    # Reativação: criar com o nome de um excluído o traz de volta (como a tag).
    existente = session.exec(
        select(Merchant).where(Merchant.workspace_id == workspace_id, Merchant.name == nome)
    ).first()
    if existente is not None and existente.deleted_at is None:
        raise HTTPException(status_code=400, detail=f"Estabelecimento '{nome}' já existe neste espaço")
    m = existente or Merchant(workspace_id=workspace_id, name=nome)
    m.deleted_at = None
    m.aliases = _apelidos(body.aliases)
    m.default_category_id = body.default_category_id
    m.updated_at = datetime.now(UTC)
    _valida(session, workspace_id, m)
    session.add(m)
    session.flush()
    publish_event(session, workspace_id, "merchant.created", "merchant", m.id, membership.user_id)
    return m


def update_merchant(session: Session, workspace_id: int, merchant_id: int, body: MerchantUpdate,
                    membership: WorkspaceMembership) -> Merchant:
    m = get_merchant_or_404(session, workspace_id, merchant_id)
    dados = body.model_dump(exclude_unset=True)
    if "name" in dados and dados["name"] is not None:
        m.name = dados["name"].strip()
    if "aliases" in dados and dados["aliases"] is not None:
        m.aliases = _apelidos(dados["aliases"])
    if "default_category_id" in dados:
        m.default_category_id = dados["default_category_id"]
    m.updated_at = datetime.now(UTC)
    _valida(session, workspace_id, m)
    session.add(m)
    session.flush()
    publish_event(session, workspace_id, "merchant.updated", "merchant", m.id, membership.user_id)
    return m


def delete_merchant(session: Session, workspace_id: int, merchant_id: int,
                    membership: WorkspaceMembership) -> Merchant:
    """Exclusão lógica. Os lançamentos e recorrências perdem o vínculo (como a tag):
    um estabelecimento excluído apontado por eles apareceria sem nome em lugar nenhum."""
    m = get_merchant_or_404(session, workspace_id, merchant_id)
    for modelo in (Transaction, RecurringExpense):
        session.execute(update(modelo).where(modelo.merchant_id == m.id).values(merchant_id=None))
    m.deleted_at = datetime.now(UTC)
    session.add(m)
    session.flush()
    publish_event(session, workspace_id, "merchant.deleted", "merchant", m.id, membership.user_id)
    return m


def merge_merchant(session: Session, workspace_id: int, merchant_id: int, body: MerchantMerge,
                   membership: WorkspaceMembership) -> Merchant:
    """"McDonald's" e "MC DONALDS" são o mesmo: o de origem some, e os lançamentos,
    as recorrências, o nome e os apelidos dele passam para o que fica."""
    origem = get_merchant_or_404(session, workspace_id, merchant_id)
    destino = get_merchant_or_404(session, workspace_id, body.into_id)
    if origem.id == destino.id:
        raise HTTPException(status_code=400, detail="Escolha outro estabelecimento para mesclar")
    for modelo in (Transaction, RecurringExpense):
        session.execute(update(modelo).where(modelo.merchant_id == origem.id).values(merchant_id=destino.id))
    herdados = [c for c in sorted(origem.chaves()) if c not in destino.chaves()]
    origem.deleted_at = datetime.now(UTC)
    origem.aliases = []
    session.add(origem)
    session.flush()
    destino.aliases = [*destino.aliases, *herdados]
    destino.updated_at = datetime.now(UTC)
    session.add(destino)
    session.flush()
    publish_event(session, workspace_id, "merchant.updated", "merchant", destino.id, membership.user_id)
    publish_event(session, workspace_id, "merchant.deleted", "merchant", origem.id, membership.user_id)
    return destino


def resolve_merchant(
    session: Session, workspace_id: int, membership: WorkspaceMembership, *,
    merchant_id: Optional[int] = None, merchant_name: Optional[str] = None, titulo: Optional[str] = None,
) -> Optional[Merchant]:
    """O estabelecimento de um lançamento novo ou editado.

    - `merchant_id`: esse (do espaço, vivo);
    - `merchant_name`: o que tem esse nome ou apelido; sem nenhum, um novo com esse nome;
    - só o título: o de apelido EXATO, ou nenhum.
    """
    if merchant_id is not None:
        return get_merchant_or_404(session, workspace_id, merchant_id)
    if merchant_name is not None and merchant_name.strip():
        achado = pelo_nome(session, workspace_id, merchant_name) or do_titulo(session, workspace_id, merchant_name)
        if achado is not None:
            return achado
        return create_merchant(session, workspace_id, MerchantCreate(name=merchant_name.strip()[:120]), membership)
    if titulo:
        return do_titulo(session, workspace_id, titulo)
    return None
