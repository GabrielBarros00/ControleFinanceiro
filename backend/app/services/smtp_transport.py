"""Como falar com o servidor de e-mail — descoberto, não adivinhado.

Até aqui o transporte era uma linha: `smtplib.SMTP(host, porta)` mais STARTTLS.
Funciona enquanto a porta configurada estiver aberta **a partir do servidor onde
o app roda** — e é exatamente isso que um VPS não garante.

A cicatriz é do deploy de produção: o provedor do servidor bloqueia a SAÍDA em
25, 465 e 587 (medida antispam padrão em VPS), e o provedor de e-mail publica
portas alternativas justamente para esse caso — 2587, 2465, 2525. O sintoma do
bloqueio não se parece com um problema de rede: é um `TimeoutError` de socket
vinte segundos depois, indistinguível de senha errada para quem lê a tela. E a
resposta certa estava a um teste de conexão de cinco segundos de distância.

Então é isso que este módulo faz, uma vez, e guarda o resultado:

1. sonda as portas candidatas do mesmo host **em paralelo** (TCP puro, 5s);
2. entrega pela primeira que completa o handshake, na ordem de preferência;
3. memoriza o endpoint que funcionou — os envios seguintes vão direto nele.

O TLS também é decidido pelo que o servidor diz, não pelo que o `.env` supõe:
porta de SSL implícito abre a conexão já cifrada, e nas demais o STARTTLS entra
quando anunciado. Com credenciais na mão e sem STARTTLS anunciado, a rota é
recusada — senha em texto claro não é um modo degradado aceitável.

Três regras impedem que "tentar de novo" vire dano:

- só falha de CONEXÃO passa para a próxima porta. Senha recusada, remetente não
  verificado ou destinatário inválido são a mesma resposta em qualquer porta:
  repetir multiplicaria a rejeição no provedor e atrasaria a resposta sem
  nenhuma chance de sucesso;
- depois que a mensagem foi entregue ao servidor, nada é repetido. Uma queda no
  meio do DATA pode significar entregue-e-perdi-a-confirmação, e reenviar por
  outra porta transformaria incerteza em e-mail duplicado;
- descoberta que falha inteira entra em espera (`ESPERA_APOS_FALHA`). Sem isso,
  um SMTP fora do ar faria cada convite pagar a sondagem completa de novo.
"""
from __future__ import annotations

import smtplib
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger("app.email")

# Portas que falam TLS desde o primeiro byte (SMTPS). Nas demais, o TLS entra
# depois do EHLO, por STARTTLS.
PORTAS_SSL_IMPLICITO = frozenset({465, 2465})

# Ordem de preferência quando a porta configurada não responde. Submissão
# autenticada primeiro (587, e a 2587 que Resend e SES publicam como alternativa
# ao bloqueio); depois a 2525, alternativa de Mailgun, SendGrid, Postmark e
# Mailtrap para o mesmo problema; depois as de SSL implícito; e a 25 por último,
# que é a mais bloqueada de todas e a que costuma não aceitar autenticação.
PORTAS_CANDIDATAS = (587, 2587, 2525, 465, 2465, 25)

TIMEOUT_DE_SONDAGEM = 5.0
TIMEOUT_DE_ENTREGA = 15.0
ESPERA_APOS_FALHA = 60.0


class ErroDeEnvio(Exception):
    """Falha de envio já traduzida para quem vai ler na tela de Admin."""


class SemRota(ErroDeEnvio):
    """Nenhum caminho até o servidor — o diagnóstico que faltava."""


class EntregaIncerta(ErroDeEnvio):
    """A conexão caiu com a mensagem já entregue ao servidor.

    Não é repetida por outra porta de propósito: pode ter sido aceita, e o
    reenvio trocaria uma dúvida por uma duplicata garantida.
    """


class _RotaImprestavel(Exception):
    """Interno: este endpoint não serve, o próximo candidato ainda pode servir."""


@dataclass(frozen=True)
class Endpoint:
    host: str
    porta: int

    @property
    def ssl_implicito(self) -> bool:
        return self.porta in PORTAS_SSL_IMPLICITO

    def __str__(self) -> str:
        return f"{self.host}:{self.porta} ({'SSL' if self.ssl_implicito else 'STARTTLS'})"


# --------------------------------------------------------------------------
# Memória da rota descoberta
# --------------------------------------------------------------------------

_trava = threading.Lock()
_rota: Optional[tuple[tuple, Endpoint]] = None
_falha_em: Optional[tuple[tuple, float]] = None


def _assinatura() -> tuple:
    """O que invalida a descoberta: mudou a configuração, esquece o que sabia."""
    return (settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_TLS, settings.SMTP_USER)


def _lembra(assinatura: tuple, endpoint: Endpoint) -> None:
    global _rota, _falha_em
    with _trava:
        _rota = (assinatura, endpoint)
        _falha_em = None


def _conhecida(assinatura: tuple) -> Optional[Endpoint]:
    with _trava:
        if _rota is not None and _rota[0] == assinatura:
            return _rota[1]
    return None


def _marca_falha(assinatura: tuple) -> None:
    global _falha_em
    with _trava:
        _falha_em = (assinatura, time.monotonic())


def _em_espera(assinatura: tuple) -> bool:
    with _trava:
        if _falha_em is None or _falha_em[0] != assinatura:
            return False
        return (time.monotonic() - _falha_em[1]) < ESPERA_APOS_FALHA


def esquece_rota() -> None:
    """Zera a memória. Usada pela suíte e pelo teste da tela de Admin."""
    global _rota, _falha_em
    with _trava:
        _rota = None
        _falha_em = None


def endpoint_em_uso() -> Optional[Endpoint]:
    """A rota que está valendo, para a tela dizer por onde o e-mail saiu."""
    return _conhecida(_assinatura())


# --------------------------------------------------------------------------
# Sondagem
# --------------------------------------------------------------------------

def _resolve(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def _alcancavel(host: str, porta: int, timeout: float) -> bool:
    """Um TCP puro, aberto e fechado. É o teste que separa bloqueio de senha."""
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            return True
    except OSError:
        return False


def _sonda(candidatos: list[Endpoint]) -> list[Endpoint]:
    """Testa todos os candidatos ao mesmo tempo, e devolve na ordem de preferência.

    Em paralelo porque em série o pior caso é a soma dos timeouts: seis portas
    bloqueadas a cinco segundos cada seriam trinta segundos de requisição
    pendurada — mais do que o operador espera antes de concluir que travou.
    """
    with ThreadPoolExecutor(max_workers=len(candidatos)) as pool:
        abertas = list(
            pool.map(lambda e: _alcancavel(e.host, e.porta, TIMEOUT_DE_SONDAGEM), candidatos)
        )
    return [endpoint for endpoint, aberta in zip(candidatos, abertas) if aberta]


def _candidatos() -> list[Endpoint]:
    host = settings.SMTP_HOST or ""
    portas = [settings.SMTP_PORT]
    portas += [p for p in PORTAS_CANDIDATAS if p != settings.SMTP_PORT]
    return [Endpoint(host, porta) for porta in portas]


# --------------------------------------------------------------------------
# Entrega
# --------------------------------------------------------------------------

def _e_falha_de_rota(exc: BaseException) -> bool:
    """Vale a pena tentar outra porta com esta exceção?

    A pergunta é mais sutil do que parece porque `smtplib.SMTPException` herda de
    `OSError`: um `except OSError` pegaria "senha recusada" junto com "timeout" e
    faria o app repetir em cinco portas uma credencial que está errada em todas.
    """
    if isinstance(exc, (
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
        smtplib.SMTPNotSupportedError,
        smtplib.SMTPHeloError,
    )):
        return True
    if isinstance(exc, smtplib.SMTPException):
        # Resposta do servidor (autenticação, remetente, destinatário): idêntica
        # em qualquer porta.
        return False
    # Sobra o que é rede: timeout, recusa de conexão, DNS e erro de TLS
    # (`ssl.SSLError` também é `OSError`) — inclusive o de falar SSL implícito
    # com uma porta que esperava STARTTLS.
    return isinstance(exc, OSError)


def _conecta(endpoint: Endpoint) -> smtplib.SMTP:
    if endpoint.ssl_implicito:
        return smtplib.SMTP_SSL(
            endpoint.host,
            endpoint.porta,
            timeout=TIMEOUT_DE_ENTREGA,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(endpoint.host, endpoint.porta, timeout=TIMEOUT_DE_ENTREGA)


def _protege(smtp: smtplib.SMTP, endpoint: Endpoint, credenciais: bool) -> None:
    """Liga o TLS conforme o servidor ANUNCIA, não conforme o `.env` supõe."""
    smtp.ehlo()
    anuncia = smtp.has_extn("starttls")

    # `credenciais` no OU não é redundância com `SMTP_TLS`: quem escreveu
    # `SMTP_TLS=False` com senha no arquivo pediu, sem saber, para a chave de API
    # atravessar a internet legível. Se o servidor oferece STARTTLS, sobe-se.
    if anuncia and (settings.SMTP_TLS or credenciais):
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()  # a lista de extensões muda depois do STARTTLS
        return

    if credenciais:
        raise _RotaImprestavel(
            f"{endpoint}: o servidor não oferece STARTTLS e há senha a enviar — "
            "recusado para não mandar a credencial em texto claro"
        )
    if settings.SMTP_TLS:
        logger.warning("smtp_sem_starttls", endpoint=str(endpoint))


def _encerra(smtp: smtplib.SMTP) -> None:
    """QUIT best-effort.

    Sem isto, um servidor que responde algo diferente de 221 no QUIT levantaria
    `SMTPResponseException` **depois da mensagem entregue** — o `__exit__` do
    `smtplib` faz exatamente isso —, e o envio bem-sucedido apareceria no log
    como falha.
    """
    try:
        smtp.quit()
    except Exception:
        try:
            smtp.close()
        except Exception:
            pass


def _entrega(endpoint: Endpoint, msg: EmailMessage) -> None:
    usuario, senha = settings.SMTP_USER, settings.SMTP_PASSWORD
    credenciais = bool(usuario and senha)

    try:
        smtp = _conecta(endpoint)
        try:
            if not endpoint.ssl_implicito:
                _protege(smtp, endpoint, credenciais)
            if credenciais:
                smtp.login(usuario, senha)
            try:
                smtp.send_message(msg)
            except Exception as exc:
                if _e_falha_de_rota(exc):
                    raise EntregaIncerta(
                        f"{endpoint}: a conexão caiu com a mensagem já enviada "
                        f"({exc}). Não foi reenviada por outra porta para não "
                        "duplicar o e-mail."
                    ) from exc
                raise
        finally:
            _encerra(smtp)
    except (_RotaImprestavel, EntregaIncerta):
        raise
    except Exception as exc:
        if _e_falha_de_rota(exc):
            raise _RotaImprestavel(f"{endpoint}: {exc}") from exc
        raise


# --------------------------------------------------------------------------
# Ponto de entrada
# --------------------------------------------------------------------------

def entrega(msg: EmailMessage, *, redescobrir: bool = False) -> Endpoint:
    """Entrega `msg` pela melhor rota disponível e devolve qual foi.

    `redescobrir` existe para UM chamador: o botão "enviar e-mail de teste" da
    tela de Admin. Quem clica nele acabou de mexer no firewall ou no provedor e
    quer a resposta de agora — não a rota memorizada, nem a espera do último
    fracasso.
    """
    assinatura = _assinatura()

    if not redescobrir:
        conhecida = _conhecida(assinatura)
        if conhecida is not None:
            try:
                _entrega(conhecida, msg)
                return conhecida
            except _RotaImprestavel as exc:
                # A rota que funcionava caiu (firewall novo, porta desativada
                # pelo provedor): esquece e descobre de novo, agora.
                logger.warning("smtp_rota_caiu", endpoint=str(conhecida), erro=str(exc))
                esquece_rota()

        if _em_espera(assinatura):
            raise SemRota(
                f"envio de e-mail em espera: a descoberta de rota até "
                f"{settings.SMTP_HOST} falhou há menos de "
                f"{int(ESPERA_APOS_FALHA)}s e não será repetida a cada mensagem."
            )

    try:
        endpoint = _descobre_e_entrega(msg)
    except ErroDeEnvio:
        _marca_falha(assinatura)
        raise

    _lembra(assinatura, endpoint)
    return endpoint


def _descobre_e_entrega(msg: EmailMessage) -> Endpoint:
    candidatos = _candidatos()
    host = candidatos[0].host

    if not _resolve(host):
        raise SemRota(
            f"o host {host!r} não resolve em DNS a partir deste servidor — "
            "confira SMTP_HOST (é o endereço do servidor de e-mail, não o do seu domínio)."
        )

    alcancaveis = _sonda(candidatos)
    if not alcancaveis:
        portas = ", ".join(str(c.porta) for c in candidatos)
        raise SemRota(
            f"nenhuma porta de {host} respondeu a partir deste servidor "
            f"(testadas: {portas}). É o sintoma clássico de VPS que bloqueia a "
            "SAÍDA de SMTP contra spam: peça a liberação ao provedor do servidor "
            "ou use uma porta alternativa do provedor de e-mail (2587, 2465, 2525)."
        )

    recusas: list[str] = []
    for endpoint in alcancaveis:
        try:
            _entrega(endpoint, msg)
        except _RotaImprestavel as exc:
            recusas.append(str(exc))
            continue
        if endpoint != candidatos[0] or recusas:
            logger.info(
                "smtp_rota_detectada",
                endpoint=str(endpoint),
                configurada=str(candidatos[0]),
                recusadas=recusas,
            )
        return endpoint

    raise SemRota(
        f"as portas abertas de {host} não completaram o handshake SMTP: "
        + "; ".join(recusas)
    )
