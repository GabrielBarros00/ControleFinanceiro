"""Baixar um arquivo que o app de chat entregou por URL, sem virar SSRF.

No ChatGPT, um arquivo que a pessoa pôs na conversa chega à tool como
`{download_url, file_id, mime_type, file_name}` (`openai/fileParams`). Quem baixa é
o servidor, e a URL vem do modelo — então é o mesmo problema do CIMD: um "faça um
GET onde eu mandar" de dentro da rede do backend. As defesas são as de
`services/oauth/cimd_fetch.py`, reaproveitadas, com duas diferenças:

- **Lista de hosts permitidos** (`MCP_FILE_URL_HOSTS`, sufixos): só o domínio de
  arquivos do app de chat. Uma URL de qualquer outro lugar é recusada antes da
  rede, e a lista vazia desliga o recurso.
- **Conteúdo binário até o teto do anexo**, com o tipo conferido depois pelos
  bytes (`upload_validation`), como no envio pela tela.
"""
from __future__ import annotations

from typing import Callable, Iterable, Tuple

import httpx

from app.services.oauth.cimd_fetch import _conecta, _ip_publico, _resolve, valid_cimd_url

TIMEOUT_SECONDS = 15.0


class RemoteFileError(ValueError):
    """O arquivo não pôde ser obtido com segurança (mensagem sem detalhe interno)."""


def host_permitido(host: str, sufixos: Iterable[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    for sufixo in sufixos:
        s = sufixo.strip().lower().lstrip(".")
        if s and (host == s or host.endswith("." + s)):
            return True
    return False


def fetch_file(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    max_bytes: int,
    resolver: Callable[[str], list[str]] = _resolve,
    transport: httpx.BaseTransport | None = None,
) -> Tuple[bytes, str]:
    """Baixa o arquivo. Devolve `(conteúdo, content-type informado pelo servidor)`."""
    sufixos = [s for s in allowed_hosts if s.strip()]
    if not sufixos:
        raise RemoteFileError("o envio de arquivo pela conversa está desligado neste servidor")
    if not valid_cimd_url(url):
        raise RemoteFileError("o endereço do arquivo não é uma URL https válida")
    try:
        pedida = httpx.URL(url)
        host = pedida.raw_host.decode("ascii")
    except (httpx.InvalidURL, UnicodeError) as exc:
        raise RemoteFileError("o endereço do arquivo não é uma URL https válida") from exc
    if not host_permitido(host, sufixos):
        raise RemoteFileError("o arquivo não vem do app de chat")
    caminho = pedida.raw_path.decode("ascii")
    try:
        enderecos = resolver(host)
    except ValueError as exc:
        raise RemoteFileError("não foi possível resolver o endereço do arquivo") from exc
    if not enderecos or not all(_ip_publico(e) for e in enderecos):
        raise RemoteFileError("o endereço do arquivo não é público")

    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "ControleFinanceiro-MCP/1.0 (+attachment)"},
        ) as cliente:
            resposta = _conecta(cliente, enderecos[:3], host, caminho)
            try:
                fluxo = resposta.extensions.get("network_stream")
                par = fluxo.get_extra_info("server_addr") if fluxo is not None else None
                if par and not _ip_publico(str(par[0])):
                    raise RemoteFileError("o endereço do arquivo não é público")
                if resposta.status_code != 200:
                    raise RemoteFileError("o arquivo não está mais disponível (o link do app de chat expira)")
                tipo = (resposta.headers.get("content-type") or "").split(";")[0].strip().lower()
                corpo = bytearray()
                for pedaco in resposta.iter_bytes():
                    corpo.extend(pedaco)
                    if len(corpo) > max_bytes:
                        raise RemoteFileError(f"o arquivo passa do limite de {max_bytes // (1024 * 1024)} MB")
            finally:
                resposta.close()
    except RemoteFileError:
        raise
    except httpx.HTTPError as exc:
        raise RemoteFileError("não foi possível baixar o arquivo") from exc
    return bytes(corpo), tipo
