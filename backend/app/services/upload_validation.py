"""Validação de arquivo enviado pelo cliente — a parte que não depende de para
que serve o arquivo.

Vivia dentro de `api/routes/attachments.py`, e a foto de perfil precisava das
mesmas três coisas: allowlist de tipo, conferência de MAGIC BYTES e leitura que
aborta antes de carregar o arquivo inteiro na memória. Duplicar significaria
duas listas de assinaturas para manter em dia — e a que não recebe a correção é
sempre a que abre o buraco.

O que NÃO mora aqui: quais tipos cada fluxo aceita, e qual é o limite de
tamanho. Recibo aceita PDF; foto de perfil, não. Cada rota declara a sua
allowlist e o seu teto, e passa aqui para conferir.
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

_READ_CHUNK = 64 * 1024

# Assinaturas de conteúdo: o Content-Type declarado pelo cliente não basta — o
# CONTEÚDO precisa bater com o tipo (SEC-003). Sem isto, um `.html` com script
# entra como "image/png" e volta a ser servido pela rota de download.
MAGIC_PREFIXES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}

# Imagens que o app aceita em qualquer fluxo. `attachments` acrescenta o PDF.
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def content_matches_type(content_type: str, data: bytes) -> bool:
    """O WebP é caso à parte: o cabeçalho é `RIFF` + 4 bytes de tamanho +
    `WEBP`, então o prefixo simples não serve."""
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return any(data.startswith(p) for p in MAGIC_PREFIXES.get(content_type, ()))


async def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Lê em chunks e interrompe assim que o limite estoura — sem carregar um
    arquivo arbitrariamente grande na memória antes de validar."""
    chunks = []
    size = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise HTTPException(status_code=400, detail=f"Arquivo excede o limite de {max_mb} MB")
        chunks.append(chunk)
    return b"".join(chunks)
