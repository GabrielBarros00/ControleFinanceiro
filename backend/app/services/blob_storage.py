"""Primitivas de arquivo para o conteúdo que mora FORA do banco.

Nasceu quando a foto de perfil precisou das mesmas garantias que os anexos já
tinham (ADR 0007/0016) e não podia herdá-las: `AttachmentStorage` é escopado por
workspace — chave `{workspace_id}/…`, cota por workspace, trava por workspace —
e o avatar é da PESSOA, não de uma casa. Copiar as noventa linhas teria criado a
segunda implementação de escrita atômica do projeto, e a segunda seria a que não
recebe as correções.

O que fica aqui é só o que independe de quem é o dono do conteúdo: resolver a
chave dentro da raiz, gravar sem deixar arquivo truncado, ler devolvendo `None`
quando o objeto sumiu, e apagar sem transformar um arquivo ausente em erro. As
decisões de domínio — como se monta a chave, quem pode ler, o que conta cota —
continuam em cada fachada.

Tudo compartilha a MESMA raiz (`ATTACHMENT_STORAGE_DIR`, o volume
`attachments_data` do compose): é um volume só para restaurar, e o namespace é
separado pelo prefixo da chave.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger("app.blobs")


class BlobStorageError(Exception):
    """Falha de I/O no armazenamento (o chamador traduz para 5xx/404)."""


def raiz() -> Path:
    """Raiz do armazenamento. Lida a cada chamada (e não no import) para o teste
    poder apontá-la a um diretório temporário."""
    return Path(settings.ATTACHMENT_STORAGE_DIR).expanduser().resolve()


def caminho_de(chave: str) -> Path:
    """Caminho absoluto da chave, garantido dentro da raiz.

    Defesa em profundidade: as chaves são geradas a partir de inteiros e hex,
    mas nada impede alguém de passar uma chave lida do banco.
    """
    base = raiz()
    caminho = (base / chave).resolve()
    if not caminho.is_relative_to(base):
        raise BlobStorageError("Chave fora do diretório de armazenamento")
    return caminho


def gravar(chave: str, dados: bytes) -> str:
    """Grava os bytes e devolve a chave. Idempotente: objeto já existente (mesmo
    conteúdo, porque a chave vem do hash) não é reescrito.

    A escrita é ATÔMICA (arquivo temporário + rename no mesmo diretório): uma
    queda no meio do upload deixaria um arquivo truncado que passaria pela
    validação de tamanho e corromperia o conteúdo em silêncio.

    O `mkdir` está DENTRO do try: o modo mais provável de falha em produção é o
    diretório raiz não ser gravável pelo usuário do processo (volume novo nasce
    root, container roda como `appuser`), e isso acontece no mkdir, não no open.
    Fora do try virava `OSError` cru → 500, em vez do 503 com mensagem que as
    rotas já sabem emitir.
    """
    destino = caminho_de(chave)
    if destino.exists():
        return chave

    temporario = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(temporario, "wb") as arquivo:
            arquivo.write(dados)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    except OSError as exc:
        temporario.unlink(missing_ok=True)
        raise BlobStorageError(f"Falha ao gravar o conteúdo: {exc}") from exc
    return chave


def ler(chave: str) -> Optional[bytes]:
    """Bytes do objeto, ou `None` se o arquivo não está lá.

    `None` em vez de exceção porque o chamador precisa distinguir "sumiu do
    disco" (problema de operação: volume não montado, restore parcial) de "não
    existe no banco" — e responder de forma inteligível em vez de 500.
    """
    try:
        caminho = caminho_de(chave)
    except BlobStorageError:
        logger.error("blob_chave_invalida", chave=chave)
        return None
    try:
        return caminho.read_bytes()
    except FileNotFoundError:
        logger.error("blob_ausente_no_disco", chave=chave, caminho=str(caminho))
        return None
    except OSError as exc:
        logger.error("blob_falha_de_leitura", chave=chave, erro=str(exc))
        return None


def apagar(chave: str) -> bool:
    """Apaga o objeto. Best-effort: arquivo já ausente não é erro (a linha do
    banco é a fonte de verdade do que existe)."""
    try:
        caminho = caminho_de(chave)
    except BlobStorageError:
        return False
    try:
        caminho.unlink(missing_ok=True)
    except OSError as exc:
        # Não propaga: falhar a exclusão por causa do arquivo deixaria a linha
        # viva e o usuário sem saída. O órfão é recuperável; a linha presa não.
        logger.error("blob_falha_ao_remover", chave=chave, erro=str(exc))
        return False
    return True


def apagar_arvore(prefixo: str) -> None:
    """Remove um subdiretório inteiro do armazenamento."""
    try:
        alvo = caminho_de(prefixo)
    except BlobStorageError:
        return
    shutil.rmtree(alvo, ignore_errors=True)
