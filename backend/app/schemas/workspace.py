from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.common import NormalizedEmail, OptionalCurrencyCode

from app.models.workspace import FinancialAccess, WorkspaceRole, InviteStatus


class WorkspaceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class WorkspaceCreate(WorkspaceBase):
    # Moeda-base já na criação. Sem este campo todo workspace nascia "BRL" e a
    # única forma de mudar era o PUT, que dispara a reconversão de TODO o
    # histórico (BaseCurrencyService) — uma operação pesada e sujeita a
    # `MissingRates` para um workspace ainda vazio.
    base_currency: OptionalCurrencyCode = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    # Moeda-base das agregações (ADR 0006). Existia no modelo e em toda consulta
    # desde a Onda 5, mas nenhuma rota permitia alterá-la — ficava BRL para sempre.
    # Mesma validação de todo campo de moeda do app (`isalpha()` sozinho aceitava
    # "ÁÁÁ", que viraria uma moeda-base impossível de casar com qualquer cotação).
    base_currency: OptionalCurrencyCode = None


class WorkspaceRead(WorkspaceBase):
    id: int
    base_currency: str = "BRL"
    created_at: datetime
    updated_at: datetime
    # Quem criou/é dono e quantos membros — para o switcher indicar "de quem é"
    # quando o workspace é compartilhado (member_count > 1)
    owner_user_id: Optional[int] = None
    owner_name: Optional[str] = None
    member_count: int = 1


class MemberRead(BaseModel):
    user_id: int
    role: WorkspaceRole
    financial_access: FinancialAccess
    user_name: str
    user_email: str
    joined_at: datetime


class MemberUpdate(BaseModel):
    role: WorkspaceRole
    # Visibilidade financeira é separada do papel (ADR 0018). Ausente = não mexe,
    # para o PATCH de papel não redefinir o acesso sem querer.
    financial_access: Optional[FinancialAccess] = None


class InviteCreate(BaseModel):
    email: NormalizedEmail
    role: WorkspaceRole = WorkspaceRole.member
    # Default FECHADO (ADR 0018): quem entra vê o que o envolve, e abrir para os
    # números da casa é ato explícito de quem convida. O papel `member` continua
    # sendo o default porque `viewer` deixaria o convidado sem poder lançar a
    # própria parte — inútil num app colaborativo.
    financial_access: FinancialAccess = FinancialAccess.involved_only
    expires_days: int = Field(default=7, ge=1, le=30)


class InviteLinkCreate(BaseModel):
    role: WorkspaceRole = WorkspaceRole.member
    financial_access: FinancialAccess = FinancialAccess.involved_only
    # Validação no SCHEMA (antes `expires_days` era conferido na rota e
    # `max_uses` não era conferido em lugar nenhum: `max_uses=0` criava um link
    # JÁ esgotado, porque o gate é `uses >= max_uses` → 0 >= 0).
    expires_days: int = Field(default=7, ge=1, le=30)
    # Default 1, não ilimitado. Link é a via menos controlada que existe aqui
    # (qualquer usuário logado com o token entra), e `None` durante 7 dias
    # significava "quantas pessoas quiserem" para quem só queria convidar uma.
    # Quem precisa de vários usos pede explicitamente.
    #
    # `le=1000` é o mesmo teto do convite de cadastro do administrador, e vale
    # aqui pela razão mais forte: um `WorkspaceInvite` também autoriza criar
    # CONTA NO SITE (ADR 0026). Sem teto, `max_uses=999999` num site
    # `invite_only` era um link de cadastro público, válido por até 30 dias,
    # emitido por qualquer usuário no próprio workspace.
    max_uses: Optional[int] = Field(default=1, ge=1, le=1000)


class InviteRead(BaseModel):
    id: int
    workspace_id: int
    email: Optional[str]
    role: WorkspaceRole
    financial_access: FinancialAccess
    status: InviteStatus
    expires_at: datetime
    max_uses: Optional[int]
    uses: int
    created_at: datetime


class InviteLinkRead(InviteRead):
    token: str
    url: str


class InviteInfoRead(BaseModel):
    """Informações públicas (para usuário logado) de um convite por token."""
    workspace_name: str
    role: WorkspaceRole
    invited_by: Optional[str]
    valid: bool
    reason: Optional[str] = None


class BaseCurrencyPreviewRead(BaseModel):
    """Dry-run da troca de moeda-base: o tamanho da reescrita, antes de confirmar.

    Tipado — e não `Dict[str, Any]` — porque a divergência aqui é cara. O
    frontend mantinha uma `interface` escrita à mão com `incomes`, `statements` e
    `financings`; o ADR 0021 tirou renda, fatura e financiamento do workspace e o
    serviço passou a devolver `settlements`, `estimates` e `recurring`. Nada
    acusou: o OpenAPI dizia só "objeto", o `api.gen.ts` não ganhava tipo, o
    TypeScript ficava verde — e a confirmação de uma operação que REESCREVE todo
    o histórico financeiro passou a exibir "undefined renda(s), undefined
    fatura(s) e undefined financiamento(s)".

    Só entidades DO WORKSPACE entram na conta. Renda, cartão, conta e
    financiamento são pessoais e seguem `User.report_currency`: reescrevê-los
    porque um workspace trocou de base seria o workspace mexendo no cadastro de
    cada membro — e, em quem participa de dois, o segundo desfaria o primeiro.
    """
    from_currency: str
    to_currency: str
    transactions: int
    settlements: int
    estimates: int
    recurring: int
    #: Datas sem cotação. Não vazia = a troca é abortada inteira (ADR 0006).
    missing_rates: List[str]
