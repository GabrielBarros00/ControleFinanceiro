"""Envio de Web Push (ADR 0033).

Não há Firebase nem app nativo: Web Push é padrão, e o "servidor de push" é o do
próprio navegador (Google para Chrome, Mozilla para Firefox, Apple para Safari).
O endpoint de cada inscrição diz para qual deles falar.

## As três peças, e por que só uma virou dependência

1. **VAPID** — um JWT ES256 que identifica esta origem para o serviço de push.
   Sai do `PyJWT[crypto]`, que já é dependência.
2. **Cifragem do corpo** (aes128gcm, RFC 8291/8188) — `http_ece`, a única peça
   nova. É o que NÃO se escreve à mão: são primitivas padrão (ECDH P-256, HKDF,
   AES-GCM), mas errar um byte de contexto no HKDF não estoura em teste nenhum —
   o push sai, o serviço aceita, e o navegador descarta em silêncio.
3. **Transporte** — `httpx`, que já é dependência.

## Formato das chaves

Base64url sem padding, que é o formato do Web Push:

- **pública**: ponto não comprimido (65 bytes, começa com `0x04`). É exatamente o
  que o navegador recebe como `applicationServerKey`, então ela viaja até o
  frontend sem conversão nenhuma.
- **privada**: o escalar de 32 bytes.

Gere o par com `python -m scripts.gerar_vapid`.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, UTC
from typing import Optional
from urllib.parse import urlparse

import http_ece
import httpx
import jwt
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import Session, select

from app.core.config import settings
from app.models.push_subscription import PushSubscription

logger = structlog.get_logger(__name__)

# Validade do JWT do VAPID. O RFC 8292 impõe teto de 24h; 12h dá folga para
# relógio dessincronizado dos dois lados sem chegar perto do limite.
_VALIDADE_JWT = timedelta(hours=12)

# Quanto tempo o serviço de push guarda a mensagem se o aparelho estiver
# desligado. Um dia: um aviso de vencimento entregue depois disso já perdeu o
# sentido — e insistir mais tempo só entrega notícia velha.
_TTL_SEGUNDOS = 86400

_TIMEOUT = httpx.Timeout(10.0)


def push_habilitado() -> bool:
    """Há par VAPID configurado?

    Sem chave a funcionalidade se desliga sozinha em vez de quebrar: a interface
    não oferece nada e o job não tenta enviar. É o que mantém o ambiente de
    desenvolvimento (que não terá chave) utilizável.
    """
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _b64url_decode(valor: str) -> bytes:
    """Base64url sem padding — o padding é opcional no formato e quase nunca vem."""
    return base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))


def b64url_encode(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def gerar_par_vapid() -> tuple[str, str]:
    """Par novo (pública, privada) em base64url. Usado pelo script de geração."""
    privada = ec.generate_private_key(ec.SECP256R1())
    publica_bytes = privada.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    privada_bytes = privada.private_numbers().private_value.to_bytes(32, "big")
    return b64url_encode(publica_bytes), b64url_encode(privada_bytes)


def _chave_privada() -> ec.EllipticCurvePrivateKey:
    escalar = int.from_bytes(_b64url_decode(settings.VAPID_PRIVATE_KEY or ""), "big")
    return ec.derive_private_key(escalar, ec.SECP256R1())


def _cabecalho_vapid(endpoint: str) -> str:
    """`Authorization: vapid t=<jwt>, k=<chave pública>`.

    O `aud` é a ORIGEM do endpoint (`https://fcm.googleapis.com`), não o endpoint
    inteiro: mandar o caminho junto faz o serviço recusar com 401.
    """
    origem = urlparse(endpoint)
    token = jwt.encode(
        {
            "aud": f"{origem.scheme}://{origem.netloc}",
            "exp": int((datetime.now(UTC) + _VALIDADE_JWT).timestamp()),
            # Contato do responsável por esta origem, para o serviço de push
            # falar com alguém se ela passar a se comportar mal. Não autentica.
            "sub": settings.VAPID_SUBJECT,
        },
        _chave_privada(),
        algorithm="ES256",
    )
    return f"vapid t={token}, k={settings.VAPID_PUBLIC_KEY}"


class InscricaoMorta(Exception):
    """O serviço de push disse que esta inscrição não existe mais (404/410)."""


def enviar_para_inscricao(inscricao: PushSubscription, corpo: bytes) -> None:
    """Envia UM push. Levanta `InscricaoMorta` quando a inscrição morreu.

    Qualquer outra falha (rede, 5xx do serviço) sobe como `httpx.HTTPError` — o
    chamador decide se registra e segue. Um aparelho fora do ar não pode
    interromper o aviso dos outros.
    """
    cifrado = http_ece.encrypt(
        corpo,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=_b64url_decode(inscricao.p256dh),
        auth_secret=_b64url_decode(inscricao.auth),
        version="aes128gcm",
    )

    resposta = httpx.post(
        inscricao.endpoint,
        content=cifrado,
        headers={
            "Authorization": _cabecalho_vapid(inscricao.endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(_TTL_SEGUNDOS),
        },
        timeout=_TIMEOUT,
    )

    # 404/410 é a resposta definitiva de que o navegador desinstalou o app ou
    # revogou a permissão. Qualquer outro erro pode ser transitório.
    if resposta.status_code in (404, 410):
        raise InscricaoMorta(inscricao.endpoint)
    resposta.raise_for_status()


def enviar_para_usuario(db: Session, user_id: int, payload: bytes) -> int:
    """Manda para TODOS os aparelhos da pessoa. Devolve quantos aceitaram.

    Apaga as inscrições mortas no caminho — é o único momento em que se descobre
    que um aparelho sumiu, porque não há evento de desinstalação.

    Não faz commit (ADR 0010).
    """
    if not push_habilitado():
        return 0

    inscricoes = list(
        db.exec(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
    )
    entregues = 0
    for inscricao in inscricoes:
        try:
            enviar_para_inscricao(inscricao, payload)
        except InscricaoMorta:
            db.delete(inscricao)
        except Exception as erro:  # rede, 5xx, timeout
            # Registrado e engolido de propósito: um aparelho fora do ar não pode
            # impedir o aviso de chegar aos outros nem derrubar o job inteiro.
            logger.warning(
                "push_falhou", user_id=user_id, erro=str(erro), tipo=type(erro).__name__
            )
        else:
            inscricao.last_success_at = datetime.now(UTC)
            entregues += 1
    return entregues


def registrar(
    db: Session,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
) -> PushSubscription:
    """Grava (ou reaponta) a inscrição deste navegador. Não faz commit.

    Reinscrever no mesmo navegador devolve o MESMO endpoint. Quando isso
    acontece com outra pessoa logada, a linha muda de dono — que é o
    comportamento correto: a anterior não pode seguir recebendo as contas dela
    num aparelho que agora é de outra (ADR 0018).
    """
    existente = db.exec(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first()
    if existente:
        existente.user_id = user_id
        existente.p256dh = p256dh
        existente.auth = auth
        existente.user_agent = user_agent
        return existente

    inscricao = PushSubscription(
        user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=user_agent
    )
    db.add(inscricao)
    db.flush()
    return inscricao


def remover(db: Session, *, user_id: int, endpoint: str) -> bool:
    """Desinscreve este navegador. Não faz commit."""
    inscricao = db.exec(
        select(PushSubscription)
        .where(PushSubscription.endpoint == endpoint)
        .where(PushSubscription.user_id == user_id)
    ).first()
    if not inscricao:
        return False
    db.delete(inscricao)
    return True
