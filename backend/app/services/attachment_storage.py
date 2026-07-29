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
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence

import structlog
from sqlalchemy import true as sa_true
from sqlmodel import select

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.attachment import Attachment

logger = structlog.get_logger("app.attachments")


class AttachmentStorageError(Exception):
    """Falha de I/O no armazenamento (o chamador traduz para 5xx/404)."""


class AttachmentStorage:
    @staticmethod
    def root() -> Path:
        """Raiz do armazenamento. Lida a cada chamada (e não no import) para o
        teste poder apontá-la a um diretório temporário."""
        return Path(settings.ATTACHMENT_STORAGE_DIR).expanduser().resolve()

    @staticmethod
    def build_key(workspace_id: int, sha256: str) -> str:
        """Chave determinística a partir do CONTEÚDO — nunca de nome de arquivo
        enviado pelo cliente (que é o vetor clássico de path traversal)."""
        sha = sha256.lower()
        return f"{int(workspace_id)}/{sha[:2]}/{sha}"

    @classmethod
    def _path(cls, storage_key: str) -> Path:
        raiz = cls.root()
        caminho = (raiz / storage_key).resolve()
        # Defesa em profundidade: a chave é gerada aqui a partir de um int e de
        # um hex, mas nada impede alguém de passar uma chave lida do banco.
        if not caminho.is_relative_to(raiz):
            raise AttachmentStorageError("Chave de anexo fora do diretório de armazenamento")
        return caminho

    @classmethod
    def save(cls, workspace_id: int, sha256: str, data: bytes) -> str:
        """Grava os bytes e devolve a `storage_key`. Idempotente: se o objeto já
        existe (mesmo conteúdo), não reescreve.

        A escrita é ATÔMICA (arquivo temporário + rename no mesmo diretório):
        uma queda no meio do upload deixaria um arquivo truncado que passaria
        pela validação de tamanho e corromperia o recibo em silêncio.

        O `mkdir` está DENTRO do try: o modo mais provável de falha em produção é
        o diretório raiz não ser gravável pelo usuário do processo (volume novo
        nasce root, container roda como `appuser`), e isso acontece no mkdir, não
        no open. Fora do try virava `OSError` cru → 500, em vez do 503 com
        mensagem que a rota já sabe emitir.
        """
        key = cls.build_key(workspace_id, sha256)
        destino = cls._path(key)
        if destino.exists():
            return key

        temporario = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            with open(temporario, "wb") as arquivo:
                arquivo.write(data)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.replace(temporario, destino)
        except OSError as exc:
            temporario.unlink(missing_ok=True)
            raise AttachmentStorageError(f"Falha ao gravar o anexo: {exc}") from exc
        return key

    @classmethod
    def read(cls, storage_key: str) -> Optional[bytes]:
        """Bytes do objeto, ou `None` se o arquivo não está lá.

        `None` em vez de exceção porque o chamador precisa distinguir "sumiu do
        disco" (problema de operação: volume não montado, restore parcial) de
        "não existe no banco" — e responder de forma inteligível em vez de 500.
        """
        try:
            caminho = cls._path(storage_key)
        except AttachmentStorageError:
            logger.error("anexo_chave_invalida", storage_key=storage_key)
            return None
        try:
            return caminho.read_bytes()
        except FileNotFoundError:
            logger.error("anexo_ausente_no_disco", storage_key=storage_key, caminho=str(caminho))
            return None
        except OSError as exc:
            logger.error("anexo_falha_de_leitura", storage_key=storage_key, erro=str(exc))
            return None

    @classmethod
    def delete(cls, storage_key: str) -> bool:
        """Apaga o objeto. Best-effort: arquivo já ausente não é erro (a linha do
        banco é a fonte de verdade do que existe)."""
        try:
            caminho = cls._path(storage_key)
        except AttachmentStorageError:
            return False
        try:
            caminho.unlink(missing_ok=True)
        except OSError as exc:
            # Não propaga: falhar o DELETE por causa do arquivo deixaria a linha
            # viva e o usuário sem saída. O órfão é recuperável; a linha presa não.
            logger.error("anexo_falha_ao_remover", storage_key=storage_key, erro=str(exc))
            return False
        return True

    @classmethod
    def delete_workspace(cls, workspace_id: int) -> None:
        """Remove o diretório inteiro de um workspace.

        **Ferramenta de operação, não do fluxo do app**: `DELETE /workspaces/{id}`
        é SOFT (a linha fica com `deleted_at`), então apagar os bytes ali destruiria
        os recibos de um workspace que ainda pode ser restaurado — irreversível
        contra uma exclusão reversível. Use isto ao purgar um workspace em
        definitivo, depois de decidir que não há volta.
        """
        try:
            alvo = cls._path(str(int(workspace_id)))
        except AttachmentStorageError:
            return
        shutil.rmtree(alvo, ignore_errors=True)


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
