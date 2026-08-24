from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, ConfigDict

from app.models.user import PlatformRole

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    is_active: bool
    needs_onboarding: bool
    # O papel de plataforma sai aqui porque a interface precisa saber se mostra o
    # item "Admin" na navegação (ADR 0026). É informação sobre SI MESMO — este
    # schema serve `/auth/me` e o próprio cadastro —, não sobre terceiros: a
    # listagem de membros usa `MemberRead`, que não tem este campo.
    #
    # Nada de autorização se apoia neste valor: quem decide é
    # `require_platform_role` no servidor. Esconder o botão é conveniência; se
    # fosse a tranca, bastaria o usuário chamar a rota direto.
    platform_role: PlatformRole
    # Token de cache da foto de perfil: os 8 primeiros do SHA-256 do conteúdo,
    # ou `None` para quem não tem foto. Não é a URL — quem monta a URL é o
    # cliente, a partir do id — e não é o hash inteiro, que seria um
    # identificador global do arquivo sem nenhum ganho para a interface.
    #
    # Existe porque a foto é servida por uma rota autenticada com
    # `Cache-Control: immutable`: sem um valor que mude junto com o conteúdo, a
    # imagem trocada continuaria aparecendo a antiga até o cache expirar.
    avatar_version: Optional[str] = None
    created_at: datetime
