from typing import Literal, Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX

#: Escopo do orçamento. `workspace` = meta da CASA (comparada com o gasto total);
#: `personal` = meta do MEMBRO (comparada com a parte dele nos splits).
EstimateScope = Literal["workspace", "personal"]

class MonthlyEstimateBase(BaseModel):
    category: str = Field(max_length=NAME_MAX)
    amount: Decimal
    month: str # YYYY-MM
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    category_id: Optional[int] = None

class MonthlyEstimateCreate(MonthlyEstimateBase):
    amount: Decimal = Field(ge=0, le=MAX_MONEY)
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    # A rota traduz para `owner_user_id` (None = casa). O default mantém o
    # comportamento anterior para clientes que não conhecem o campo.
    scope: EstimateScope = "workspace"

class MonthlyEstimateRead(MonthlyEstimateBase):
    id: int
    workspace_id: int
    user_id: int
    # None = meta da casa; preenchido = meta pessoal daquele membro
    owner_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Derivado, não persistido: uma coluna `scope` ao lado de `owner_user_id`
    # seria duas fontes para o mesmo fato, com chance de discordarem.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def scope(self) -> EstimateScope:
        return "personal" if self.owner_user_id is not None else "workspace"
