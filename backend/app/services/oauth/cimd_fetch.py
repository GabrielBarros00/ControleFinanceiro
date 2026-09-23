"""Busca de Client ID Metadata Document (CIMD) sem virar SSRF.

No CIMD o `client_id` é uma URL e o authorization server a busca. Quem escolhe a
URL é quem inicia o fluxo — qualquer um, sem autenticação —, então esta função é
um "faça um GET onde eu mandar" a partir de dentro da rede do backend. As
defesas, em camadas:

1. **Forma da URL**: só `https`, porta 443 (implícita ou explícita), com host e
   caminho, sem credenciais nem fragmento. Porta arbitrária é o jeito clássico de
   sondar serviço interno.
2. **Endereço**: o nome é resolvido UMA vez, todo IP precisa ser público
   (`is_global`), e a conexão vai para ESSE IP — a URL pedida ao `httpx` leva o
   IP, com o nome original no `Host` e no SNI (o certificado continua conferido
   contra o nome). Sem isso o `httpx` resolveria o nome de novo, e um DNS
   malicioso responderia IP público na checagem e interno na conexão (DNS
   rebinding) — a requisição sairia antes de qualquer conferência. O IP do par
   ainda é conferido depois de conectar, como segunda linha.
3. **Resposta**: sem seguir redirect, 5 s de timeout, no máximo 64 KB, só JSON.
4. **TLS verificado**: um serviço interno raramente tem certificado válido para
   um domínio público arbitrário, o que torna a sondagem cega mesmo no pior caso.

O resultado nunca é devolvido a quem pediu além de "cliente inválido" — não há
canal para ler conteúdo de volta.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from typing import Callable, Tuple
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 64 * 1024
TIMEOUT_SECONDS = 5.0
MIN_TTL_SECONDS = 300
MAX_TTL_SECONDS = 86_400


class CimdFetchError(ValueError):
    """O documento não pôde ser obtido com segurança (mensagem sem detalhe interno)."""


def valid_cimd_url(url: str) -> bool:
    """A URL tem a forma aceita para um `client_id` CIMD? (sem rede)"""
    if not url or len(url) > 512:
        return False
    try:
        partes = urlsplit(url)
        porta = partes.port
    except ValueError:
        return False
    return (
        partes.scheme == "https"
        and bool(partes.hostname)
        and not partes.username
        and not partes.password
        and not partes.fragment
        and porta in (None, 443)
        and partes.path not in ("", "/")
    )


def _ip_publico(endereco: str) -> bool:
    try:
        ip = ipaddress.ip_address(endereco.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise CimdFetchError("não foi possível resolver o endereço do cliente") from exc
    # Na ordem do sistema (RFC 6724), como o `socket.create_connection` tentaria.
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


MAX_ENDERECOS = 3


def _url_no_ip(ip: str, caminho: str) -> str:
    """URL com o IP JÁ VALIDADO no lugar do nome: só o caminho vem de quem pediu."""
    endereco = ipaddress.ip_address(ip.split("%", 1)[0])
    anfitriao = f"[{endereco.compressed}]" if endereco.version == 6 else endereco.compressed
    return f"https://{anfitriao}{caminho}"


def _ttl(cache_control: str | None) -> int:
    ttl = MIN_TTL_SECONDS
    for diretiva in (cache_control or "").lower().split(","):
        diretiva = diretiva.strip()
        if diretiva.startswith("max-age="):
            try:
                ttl = int(diretiva.split("=", 1)[1])
            except ValueError:
                pass
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, ttl))


def _conecta(cliente: httpx.Client, enderecos: list[str], host: str, caminho: str) -> httpx.Response:
    """Abre a resposta no primeiro IP validado que aceitar conexão (os outros são reserva)."""
    for i, ip in enumerate(enderecos):
        pedido = cliente.build_request(
            "GET", _url_no_ip(ip, caminho), headers={"Host": host}, extensions={"sni_hostname": host}
        )
        try:
            return cliente.send(pedido, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if i == len(enderecos) - 1:
                raise
    raise CimdFetchError("não foi possível buscar o documento do cliente")  # pragma: no cover — lista nunca vazia


def fetch_client_metadata(
    url: str,
    *,
    resolver: Callable[[str], list[str]] = _resolve,
    transport: httpx.BaseTransport | None = None,
) -> Tuple[dict, int]:
    """Busca e decodifica o documento. Devolve `(documento, ttl_em_segundos)`.

    `resolver`/`transport` existem para os testes (nenhum teste fala com a rede).
    """
    if not valid_cimd_url(url):
        raise CimdFetchError("client_id não é uma URL https válida")
    try:
        pedida = httpx.URL(url)
        host = pedida.raw_host.decode("ascii")  # IDNA: o que vai no DNS, no Host e no SNI
    except (httpx.InvalidURL, UnicodeError) as exc:
        raise CimdFetchError("client_id não é uma URL https válida") from exc
    caminho = pedida.raw_path.decode("ascii")
    enderecos = resolver(host)
    if not enderecos or not all(_ip_publico(e) for e in enderecos):
        raise CimdFetchError("o endereço do cliente não é público")

    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "ControleFinanceiro-OAuth/1.0 (+client-id-metadata)",
            },
        ) as cliente:
            resposta = _conecta(cliente, enderecos[:MAX_ENDERECOS], host, caminho)
            try:
                fluxo = resposta.extensions.get("network_stream")
                par = fluxo.get_extra_info("server_addr") if fluxo is not None else None
                if par and not _ip_publico(str(par[0])):
                    raise CimdFetchError("o endereço do cliente não é público")
                if resposta.status_code != 200:
                    raise CimdFetchError("o documento do cliente não está disponível")
                tipo = (resposta.headers.get("content-type") or "").split(";")[0].strip().lower()
                if tipo not in ("application/json", "application/jwk-set+json") and not tipo.endswith("+json"):
                    raise CimdFetchError("o documento do cliente não é JSON")
                corpo = bytearray()
                for pedaco in resposta.iter_bytes():
                    corpo.extend(pedaco)
                    if len(corpo) > MAX_BYTES:
                        raise CimdFetchError("o documento do cliente é grande demais")
                ttl = _ttl(resposta.headers.get("cache-control"))
            finally:
                resposta.close()
    except CimdFetchError:
        raise
    except httpx.HTTPError as exc:
        raise CimdFetchError("não foi possível buscar o documento do cliente") from exc

    try:
        documento = json.loads(bytes(corpo).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CimdFetchError("o documento do cliente não é JSON válido") from exc
    if not isinstance(documento, dict):
        raise CimdFetchError("o documento do cliente não é um objeto JSON")
    return documento, ttl
