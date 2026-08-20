"""Foto de perfil — bytes fora do banco, como os anexos (ADR 0007/0016).

Por que não reusar `AttachmentStorage` inteiro: aquele é escopado por WORKSPACE
em tudo — a chave começa pelo `workspace_id`, a cota é por workspace, e o upload
trava o workspace antes de somar a cota. A foto é da PESSOA e a acompanha em
todos os espaços (mesma lógica que levou cartão, conta e renda para fora do
workspace no ADR 0021). As primitivas de arquivo são as mesmas e vêm de
`blob_storage`; o que muda é a chave e quem manda nela.

**Chave `avatars/{sha[:2]}/{sha}`** — endereçada pelo CONTEÚDO, como a dos
anexos, e nunca pelo id do usuário. Duas consequências que valem dizer em voz
alta:

1. o prefixo literal `avatars/` nunca colide com o dos anexos, que começa
   sempre por um inteiro (`{workspace_id}/…`);
2. duas pessoas com a mesma foto compartilham um arquivo só — então trocar a
   própria foto NÃO pode apagar o objeto sem antes conferir se sobrou alguém
   apontando para ele. É o mesmo cuidado de `keys_to_free` nos anexos, e é o que
   `chave_em_uso` faz aqui.

Não há cota: é um objeto por conta, com teto de 1 MiB na rota. A pessoa não
consegue acumular avatares — o anterior é liberado a cada troca.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from sqlmodel import Session, select

from app.models.user import User
from app.services import blob_storage


def build_key(sha256: str) -> str:
    sha = sha256.lower()
    return f"avatars/{sha[:2]}/{sha}"


def salvar(dados: bytes) -> tuple[str, str]:
    """Grava a foto e devolve `(storage_key, sha256)`."""
    sha = hashlib.sha256(dados).hexdigest()
    return blob_storage.gravar(build_key(sha), dados), sha


def ler(storage_key: str) -> Optional[bytes]:
    return blob_storage.ler(storage_key)


def chave_em_uso(db: Session, storage_key: str, ignorando_user_id: int) -> bool:
    """Alguém ALÉM desta pessoa ainda aponta para esta chave?

    Sem esta pergunta, trocar a própria foto apagaria o arquivo de quem tivesse
    subido a mesma imagem — e o avatar do outro passaria a devolver 404 sem
    ninguém ter mexido nele.
    """
    outro = db.exec(
        select(User.id).where(
            User.avatar_key == storage_key,
            User.id != ignorando_user_id,
        ).limit(1)
    ).first()
    return outro is not None


def liberar(db: Session, storage_key: Optional[str], do_usuario: int) -> None:
    """Apaga o objeto se nenhuma outra conta o referencia.

    Chamar **depois do commit** que já removeu a referência desta conta: se o
    arquivo sumisse antes e a transação desse rollback, sobraria uma linha
    apontando para uma foto que não existe mais. Órfão é desperdício de disco e
    recuperável; referência quebrada, não.
    """
    if not storage_key:
        return
    if chave_em_uso(db, storage_key, do_usuario):
        return
    blob_storage.apagar(storage_key)
