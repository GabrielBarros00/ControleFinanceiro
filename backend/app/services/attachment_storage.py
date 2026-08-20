"""Conteúdo dos anexos FORA do banco (ADR 0007).

O banco guarda metadados + `sha256` + a chave de armazenamento; os bytes vivem
num diretório (volume, em produção). Isso tira do dump do Postgres um peso que
cresce com recibos e não com finanças, e abre o caminho para object storage
depois — o seam é esta classe.

**Endereçamento pelo conteúdo:** a chave é `{workspace}/{sha[:2]}/{sha}`. Dois
uploads do mesmo arquivo no mesmo workspace apontam para o MESMO objeto, então
reenviar o comprovante não duplica bytes. A contrapartida é que apagar um anexo
não pode apagar o arquivo cegamente: a rota confere se sobrou alguma linha
apontando para a mesma chave (`storage_key_em_uso`).

O prefixo por workspace mantém o isolamento visível no disco (facilita export e
exclusão de um workspace inteiro) e evita um diretório com milhões de entradas.

As primitivas de arquivo (raiz, escrita atômica, leitura tolerante, remoção
best-effort) moram em `blob_storage` desde que o avatar passou a precisar das
mesmas garantias — o que fica aqui é o que é DO ANEXO: a forma da chave, o
escopo por workspace e a contabilidade de referências da deduplicação.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence

import structlog
from sqlalchemy import true as sa_true
from sqlmodel import select

from app.services import blob_storage
from app.services.blob_storage import BlobStorageError

if TYPE_CHECKING:
    from app.models.attachment import Attachment

logger = structlog.get_logger("app.attachments")


# O nome antigo continua sendo o que as rotas capturam. É um ALIAS, e não uma
# subclasse: `except AttachmentStorageError` precisa pegar o que `blob_storage`
# levanta, e uma subclasse deixaria passar exatamente esses casos.
AttachmentStorageError = BlobStorageError


class AttachmentStorage:
    @staticmethod
    def root() -> Path:
        return blob_storage.raiz()

    @staticmethod
    def build_key(workspace_id: int, sha256: str) -> str:
        """Chave determinística a partir do CONTEÚDO — nunca de nome de arquivo
        enviado pelo cliente (que é o vetor clássico de path traversal)."""
        sha = sha256.lower()
        return f"{int(workspace_id)}/{sha[:2]}/{sha}"

    @classmethod
    def save(cls, workspace_id: int, sha256: str, data: bytes) -> str:
        """Grava os bytes e devolve a `storage_key`."""
        return blob_storage.gravar(cls.build_key(workspace_id, sha256), data)

    @classmethod
    def read(cls, storage_key: str) -> Optional[bytes]:
        return blob_storage.ler(storage_key)

    @classmethod
    def delete(cls, storage_key: str) -> bool:
        return blob_storage.apagar(storage_key)

    @classmethod
    def delete_workspace(cls, workspace_id: int) -> None:
        """Remove o diretório inteiro de um workspace.

        **Ferramenta de operação, não do fluxo do app**: `DELETE /workspaces/{id}`
        é SOFT (a linha fica com `deleted_at`), então apagar os bytes ali destruiria
        os recibos de um workspace que ainda pode ser restaurado — irreversível
        contra uma exclusão reversível. Use isto ao purgar um workspace em
        definitivo, depois de decidir que não há volta.
        """
        blob_storage.apagar_arvore(str(int(workspace_id)))


def keys_to_free(db, attachments: Sequence["Attachment"]) -> List[str]:
    """Chaves que ficarão SEM nenhuma linha apontando para elas.

    O armazenamento é endereçado por conteúdo e dedupica dentro do workspace:
    dois anexos do mesmo comprovante compartilham o objeto. Apagar o arquivo
    junto com a primeira linha levaria o segundo anexo — ainda listado na UI —
    a devolver "conteúdo indisponível".

    Chamar ANTES de remover as linhas; o resultado é aplicado com
    `free_keys` DEPOIS do commit.
    """
    from app.models.attachment import Attachment as _Attachment

    ids = {a.id for a in attachments if a.id is not None}
    chaves = {a.storage_key for a in attachments if a.storage_key}
    if not chaves:
        return []

    ainda_em_uso = set(
        db.exec(
            select(_Attachment.storage_key).where(
                _Attachment.storage_key.in_(chaves),
                _Attachment.id.not_in(ids) if ids else sa_true(),
            )
        ).all()
    )
    return sorted(chaves - ainda_em_uso)


def free_keys(keys: Sequence[str]) -> None:
    """Apaga os objetos das chaves liberadas. Chamar **depois do commit**.

    A ordem importa: se o arquivo sumisse antes e a transação desse rollback, a
    linha continuaria viva apontando para um recibo que não existe mais. Um
    arquivo órfão é desperdício de disco e recuperável; um recibo quebrado, não.
    """
    for key in keys:
        AttachmentStorage.delete(key)
