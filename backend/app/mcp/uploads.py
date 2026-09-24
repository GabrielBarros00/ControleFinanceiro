"""Anexar um arquivo do computador do usuário pelo terminal (ADR 0035).

Os agentes de terminal (Claude Code, Codex, Gemini CLI) têm os arquivos do usuário
e um shell, mas o arquivo NÃO passa pela conversa: em base64, uma foto de 3 MB
seriam ~4 milhões de caracteres de argumento de tool. O caminho é outro:

1. `attachments_upload_link` confere que a pessoa vê e pode editar o lançamento
   e emite um token de USO ÚNICO (`cfm_up_…`, 10 minutos), amarrado ao usuário, à
   concessão OAuth e àquele lançamento — na mesma tabela das confirmações de
   massa (`mcpconfirmation`), só o SHA-256 guardado;
2. o agente roda `curl -H "Authorization: Bearer cfm_up_…" -F file=@recibo.jpg
   <site>/api/v1/mcp/uploads`, e o arquivo vai do disco direto para o app;
3. a rota confere tudo de novo NA HORA do envio e grava pelo MESMO comando da
   tela (`services/commands/attachments.py`): tipos, conteúdo real, cota, trava.

O token vai no CABEÇALHO, não na URL: URL fica gravada no log do app, do nginx e
do proxy. Arquivo recusado (tipo, tamanho, cota) não gasta o link; o reenvio do
mesmo token depois do sucesso devolve o resultado anterior, sem anexar de novo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.mcp import McpConfirmation
from app.models.oauth import OAuthGrant
from app.models.user import User
from app.services.oauth.crypto import UPLOAD_PREFIX, sha256_hex

ACAO = "attachment_upload"
CAMINHO = "/api/v1/mcp/uploads"


@dataclass(frozen=True)
class Envio:
    registro: McpConfirmation
    user: User
    grant: OAuthGrant
    workspace_id: int
    transaction_id: int


def _recusa() -> HTTPException:
    # A mesma resposta para "não existe", "expirou", "revogado" e "de outra
    # ação": o motivo não ajuda quem tenta adivinhar um token.
    return HTTPException(
        status_code=401,
        detail="Link de envio inválido ou expirado. Peça um novo ao assistente (attachments_upload_link).",
    )


def token_do_cabecalho(authorization: str | None) -> str:
    esquema, _, valor = (authorization or "").partition(" ")
    valor = valor.strip()
    if esquema.lower() != "bearer" or not valor.startswith(UPLOAD_PREFIX) or len(valor) > 200:
        raise _recusa()
    return valor


def confere(session: Session, token: str) -> Envio:
    """O envio que este token autoriza, conferido agora (e não na emissão)."""
    registro = session.exec(
        select(McpConfirmation).where(McpConfirmation.token_hash == sha256_hex(token))
    ).first()
    if registro is None or registro.action != ACAO or not registro.target_ids:
        raise _recusa()
    expira = registro.expires_at if registro.expires_at.tzinfo else registro.expires_at.replace(tzinfo=UTC)
    if registro.used_at is None and expira <= datetime.now(UTC):
        raise _recusa()
    grant = session.get(OAuthGrant, registro.grant_id) if registro.grant_id else None
    user = session.get(User, registro.user_id)
    # Revogar a conexão (ou desativar a conta) invalida o link na hora, como
    # invalida o token de acesso.
    if grant is None or grant.revoked_at is not None or user is None or not user.is_active:
        raise _recusa()
    workspace_id = int((registro.params or {}).get("workspace_id", 0))
    if not workspace_id:
        raise _recusa()
    return Envio(registro, user, grant, workspace_id, int(registro.target_ids[0]))
