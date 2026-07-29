from decimal import Decimal
from typing import Annotated, Any, Dict, Optional
from pydantic import BaseModel, BeforeValidator, EmailStr, Field

from app.domain.query_policy import normalize_currency_code

# Teto de qualquer valor monetário de ENTRADA. As colunas são NUMERIC(20,2), e
# nenhum schema impunha limite: um POST com 1e30 virava
# `DataError: numeric field overflow` → 500 no Postgres, enquanto o SQLite de dev
# aceitava calado. Erro de cliente tem de ser 422, e o comportamento não pode
# depender do banco.
MAX_MONEY = Decimal("9999999999999999.99")

# Tetos de texto livre. Só Transaction e Workspace tinham limite; o resto aceitava
# título de 5.000 caracteres, que estoura o layout de toda lista onde aparece.
TITLE_MAX = 200
DESCRIPTION_MAX = 2000
NAME_MAX = 120


def normalize_email(value: Any) -> Any:
    """Caixa baixa + trim. Ponto único de normalização de e-mail.

    Sem isto `Joao@x.com` e `joao@x.com` viravam DUAS contas (a unique é na
    string crua), um convite para uma delas era recusado para a outra
    (`invite.email != current_user.email`) e o `forgot-password` não encontrava
    a conta — respondendo o genérico "se o email estiver cadastrado" e deixando
    a pessoa sem saída.
    """
    return value.strip().lower() if isinstance(value, str) else value


# E-mail validado E normalizado. O BeforeValidator roda ANTES da validação de
# formato, então a normalização vale para o valor que chega ao banco.
NormalizedEmail = Annotated[EmailStr, BeforeValidator(normalize_email)]
# Para campos que aceitam string livre (login não valida formato: quem erra o
# e-mail deve receber "email ou senha incorretos", não um 422 que confirma que
# o formato existe).
NormalizedEmailStr = Annotated[str, BeforeValidator(normalize_email)]


def _normalize_optional_currency(value: Any) -> Any:
    """`None`/vazio segue como None (a rota resolve para a moeda-base)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return normalize_currency_code(value)


# Moeda validada E normalizada na BORDA. Um código inventado agora é 422 com
# mensagem, não um registro persistido que some calado de todas as agregações
# (que filtram `currency == base_currency`). Mesmo princípio do MAX_MONEY acima:
# erro de cliente é 422, e o comportamento não pode depender do banco nem da
# disponibilidade da fonte de câmbio.
CurrencyCode = Annotated[str, BeforeValidator(normalize_currency_code)]
# Para campos opcionais: None = "não informada" → a rota resolve com
# `resolve_currency` (moeda-base do workspace).
OptionalCurrencyCode = Annotated[
    Optional[str], BeforeValidator(_normalize_optional_currency)
]

class ErrorDetail(BaseModel):
    code: str = Field(..., description="Código estável de erro para tratamento lógico.")
    message: str = Field(..., description="Mensagem de erro legível para o usuário em PT-BR.")
    details: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Detalhes adicionais do erro (ex: erros de validação por campo).")

class ErrorResponse(BaseModel):
    error: ErrorDetail
