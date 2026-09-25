"""Concorrência otimista: `version` na saída, `expected_version` na escrita.

Num espaço compartilhado duas pessoas (ou uma pessoa e o agente dela, ou o
componente aberto na conversa) podem editar o mesmo lançamento. Sem controle, a
segunda escrita sobrescreve a primeira em silêncio.

**A versão é o estado, não um carimbo.** `updated_at` só muda quando a LINHA
principal é atualizada. Trocar só as tags ou só a divisão mexe em linhas filhas,
e a versão por carimbo não veria a mudança. Aqui a versão é um hash curto do
que a própria tool devolve como estado (valores, divisão, itens, tags, situação):
qualquer mudança visível muda a versão, e nada mais a muda.

A conferência trava a linha antes de comparar (`with_for_update`, que o Postgres
honra e o SQLite ignora sem erro): duas edições simultâneas com a mesma versão
não passam as duas.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Iterable, Optional

from pydantic import BaseModel, Field

from app.mcp.errors import ErrorCode, McpToolError

#: Campos que não fazem parte do estado (link, contagem, a própria versão).
_FORA_DO_ESTADO = frozenset({"version", "app_url", "files", "attachments", "purchase", "created_by"})

#: Use como `expected_version: ExpectedVersion = None`.
ExpectedVersion = Annotated[
    Optional[str],
    Field(
        min_length=6,
        max_length=40,
        pattern=r"^[0-9a-f]+$",
        description=(
            "A `version` lida. Se o registro mudou desde então, volta CONFLICT em vez de "
            "sobrescrever."
        ),
    ),
]


def version_of(estado: BaseModel | dict[str, Any], *, ignore: Iterable[str] = ()) -> str:
    dados = estado.model_dump(mode="json") if isinstance(estado, BaseModel) else dict(estado)
    fora = _FORA_DO_ESTADO | set(ignore)
    dados = {k: v for k, v in dados.items() if k not in fora}
    corpo = json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:16]


def check(expected: Optional[str], atual: str, *, what: str = "O lançamento") -> None:
    if expected is None or expected == atual:
        return
    raise McpToolError(
        ErrorCode.CONFLICT,
        f"{what} mudou desde a sua leitura (outra pessoa, o app ou outra conversa). Leia de novo e "
        "confirme com o usuário antes de alterar.",
        details={"expected_version": expected, "current_version": atual},
    )
