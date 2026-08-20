"""Contrato tipado da área administrativa (ADR 0026) e da porta de cadastro.

Estas rotas não declaravam `response_model` nenhum, e o efeito no artefato
gerado é pior que `Dict[str, Any]`: o `api.gen.ts` recebia `unknown` puro, sem
sequer saber que a resposta é um objeto. O frontend preenchia o vazio com
interfaces escritas à mão.

**Tudo aqui é METADADO.** Contagem, tamanho, data, papel, configuração — nenhum
campo destes schemas carrega valor de lançamento, saldo ou limite de outra
pessoa, e `tests/security/test_admin_sem_vazamento_financeiro.py` reprova quem
tentar acrescentar. Os bytes de anexo são tamanho de arquivo, não dinheiro.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.models.user import PlatformRole


class AdminOverviewRead(BaseModel):
    """Os números do SITE — quantos, quanto ocupam, quantos entraram."""
    usuarios_total: int
    usuarios_ativos: int
    usuarios_novos_30d: int
    workspaces: int
    lancamentos: int
    anexos_bytes: int
    anexos_qtd: int
    convites_pendentes: int
    sessoes_vivas: int
    #: `None` quando o dialeto não sabe medir (SQLite em dev).
    banco_bytes: Optional[int] = None


class AdminHealthRead(BaseModel):
    """Saúde operacional: o que está crescendo e o que ficou para trás."""
    #: Data da cotação mais recente no store — se atrasa, a conversão para de
    #: acompanhar o mercado em silêncio.
    cambio_ultima_data: Optional[Any] = None
    cambio_cotacoes: int
    banco_bytes: Optional[int] = None
    anexos_bytes: int
    sessoes_expiradas_pendentes_de_expurgo: int
    auditoria_linhas: int
    auditoria_mais_antiga: Optional[datetime] = None


class AdminUserRead(BaseModel):
    """Uma pessoa como o operador do site a enxerga.

    As três contagens do fim são de VOLUME (quantos workspaces, quantos
    lançamentos, quantos bytes) — nunca de valor.
    """
    id: int
    name: str
    email: str
    is_active: bool
    platform_role: PlatformRole
    created_at: datetime
    deleted_at: Optional[datetime] = None
    needs_onboarding: bool
    last_login_at: Optional[datetime] = None
    workspaces: int
    lancamentos: int
    anexos_bytes: int


class AdminUserListRead(BaseModel):
    total: int
    items: List[AdminUserRead] = []
    limit: int
    offset: int


class AdminUserPatchRead(BaseModel):
    """O estado da conta DEPOIS do PATCH — só o que mudou importa aqui."""
    id: int
    name: str
    email: str
    is_active: bool
    platform_role: PlatformRole


class AdminUserDeleteRead(BaseModel):
    """Exclusão LÓGICA: a linha continua sendo referência de FK e da trilha."""
    status: str
    id: int


class RevokeSessionsRead(BaseModel):
    revogadas: int


class SettingKeyRead(BaseModel):
    """Uma chave de configuração e DE ONDE o valor vigente vem.

    `sobrescrito` é o que impede a tela de mentir: sem ele, um número que ainda
    acompanha o `.env` aparece igual a um gravado no banco, e o operador muda a
    variável de ambiente esperando um efeito que não vem.
    """
    nome: str
    descricao: str
    origem_ambiente: Optional[str] = None
    sobrescrito: bool


class SettingsRead(BaseModel):
    #: Valores EFETIVOS (banco sobrepondo ambiente). Heterogêneo de propósito:
    #: cada chave tem seu próprio tipo, validado por `app_settings`.
    valores: Dict[str, Any]
    chaves: List[SettingKeyRead] = []
    #: Teto do nginx, em bytes. Vem junto porque afrouxar `upload_max_bytes`
    #: acima dele não tem efeito: o proxy corta antes de o backend ver o corpo.
    limite_nginx_bytes: int


class SettingsPutRead(BaseModel):
    valores: Dict[str, Any]


class TestEmailRead(BaseModel):
    """Resultado do e-mail de teste, com o erro NA TELA.

    Antes disto, descobrir SMTP mal configurado exigia provocar um convite de
    verdade e ler o log do container — quem não tem acesso ao host não descobria,
    e o sintoma ("o convite não chegou") é indistinguível de spam.
    """
    enviado: bool
    #: `False` = não há SMTP configurado; os links saem no log do backend.
    configurado: bool
    #: A mensagem de erro do provedor, quando houve erro.
    detalhe: Optional[str] = None
    #: Rota de saída efetivamente usada (host:porta), redescoberta a cada teste.
    rota: Optional[str] = None


class RegistrationPolicyRead(BaseModel):
    """A porta da frente — PÚBLICO de propósito (ADR 0026).

    Existe para a tela dizer "é só por convite" ANTES de a pessoa preencher o
    formulário inteiro. Não vaza nada além do que qualquer um obtém tentando se
    cadastrar uma vez: quem pode convidar e quantos convites existem NÃO saem
    daqui.
    """
    mode: str
    aceita_cadastro: bool
    exige_convite: bool
    #: Janela de bootstrap aberta — é o que torna o primeiro acesso de um deploy
    #: novo possível PELO NAVEGADOR. Não revela o e-mail do administrador: quem
    #: decide continua sendo a comparação com `SUPERADMIN_EMAIL` no register.
    primeiro_acesso: bool
