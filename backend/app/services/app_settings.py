"""Configuração do site alterável em runtime (ADR 0026).

Resolve cada chave numa cascata de três degraus:

    AppSetting (banco)  →  Settings (.env)  →  padrão embutido

O degrau do meio é o que faz este módulo valer a pena. Sem ele, ligar a tela de
Admin exigiria semear a tabela com os valores atuais, e a partir daí o `.env`
viraria decoração: o operador mudaria `ATTACHMENT_QUOTA_BYTES`, reiniciaria, e
nada aconteceria — porque uma linha gravada meses antes continuaria vencendo, em
silêncio. Com a cascata, a ausência de linha significa "acompanhe o ambiente", e
gravar é uma decisão consciente que a tela mostra como tal.

CACHE — o dicionário é de processo e vive enquanto o processo viver. É seguro
pela mesma razão que o `ConnectionManager` do WebSocket e o `RateLimiter` são: o
deploy roda `--workers 1`, fixado no `backend/Dockerfile` por causa do WS. Se um
dia houver um segundo worker, este cache passa a servir valor velho no worker que
não recebeu a escrita, e a saída é a mesma dos outros dois — um backend
compartilhado (Redis), não um TTL, que só transforma "errado para sempre" em
"errado por 30 segundos".
"""
import json
from decimal import Decimal
from typing import Any, Callable, Dict, Optional

from sqlmodel import Session

from app.core.config import settings
from app.models.app_setting import AppSetting


class RegistrationMode:
    """Quem pode criar conta no site."""

    open = "open"                # qualquer pessoa com a URL
    invite_only = "invite_only"  # só com convite válido (padrão)
    closed = "closed"            # ninguém, nem com convite


class WhoCanInvite:
    admins_only = "admins_only"
    all_users = "all_users"      # padrão: quem já está dentro pode chamar alguém


# Teto de `upload_max_bytes`. NÃO é preferência: é o `client_max_body_size 6m` do
# `frontend/nginx.conf`, que fica NA FRENTE do backend. Um valor maior aqui não
# libera nada — o nginx corta a requisição com 413 antes de o FastAPI ver o
# primeiro byte, e o usuário recebe uma página de erro do nginx em vez da
# mensagem do app. Subir de verdade exige mexer nos dois lugares e refazer a
# imagem do frontend; enquanto isso não acontece, a tela recusa o valor
# explicando o porquê, em vez de aceitar uma configuração que não vale.
NGINX_BODY_LIMIT_BYTES = 6 * 1024 * 1024


def _positivo(maximo: Any = None) -> Callable[[Any], int]:
    """Inteiro positivo, com teto opcional.

    `maximo` aceita um CALLABLE além de um número porque alguns tetos não são
    preferência nossa: são a configuração de outro componente, lida do ambiente
    no boot. Congelá-los na importação deste módulo funcionaria hoje e mentiria
    no dia em que a suíte — ou um deploy — mudasse a variável.
    """
    def valida(valor: Any) -> int:
        try:
            n = int(valor)
        except (TypeError, ValueError):
            raise ValueError("precisa ser um número inteiro")
        if n <= 0:
            raise ValueError("precisa ser maior que zero")
        teto = maximo() if callable(maximo) else maximo
        if teto is not None and n > teto:
            raise ValueError(f"não pode passar de {teto}")
        return n
    return valida


def _um_de(*aceitos: str) -> Callable[[Any], str]:
    def valida(valor: Any) -> str:
        texto = str(valor)
        if texto not in aceitos:
            raise ValueError(f"precisa ser um de: {', '.join(aceitos)}")
        return texto
    return valida


def _booleano(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.lower() in ("true", "false"):
        return valor.lower() == "true"
    raise ValueError("precisa ser verdadeiro ou falso")


class _Chave:
    def __init__(
        self,
        nome: str,
        padrao: Any,
        valida: Callable[[Any], Any],
        env: Optional[str] = None,
        descricao: str = "",
    ):
        self.nome = nome
        self._padrao = padrao
        self.valida = valida
        self.env = env
        self.descricao = descricao

    @property
    def padrao(self) -> Any:
        """Valor quando não há linha no banco: o do `.env`, se a chave tem um."""
        if self.env is not None:
            return getattr(settings, self.env)
        return self._padrao


CHAVES: Dict[str, _Chave] = {
    c.nome: c
    for c in [
        _Chave(
            "registration_mode",
            RegistrationMode.invite_only,
            _um_de(RegistrationMode.open, RegistrationMode.invite_only, RegistrationMode.closed),
            env="REGISTRATION_MODE",
            descricao="Quem pode criar conta no site",
        ),
        _Chave(
            "who_can_invite",
            WhoCanInvite.all_users,
            _um_de(WhoCanInvite.admins_only, WhoCanInvite.all_users),
            descricao="Quem pode gerar convite de cadastro",
        ),
        _Chave(
            "invite_expiry_days", 7, _positivo(maximo=365),
            descricao="Dias até um convite de cadastro expirar",
        ),
        _Chave(
            "user_invite_quota_per_month", 5, _positivo(maximo=1000),
            descricao="Convites que um usuário comum pode gerar por mês",
        ),
        _Chave(
            "attachment_quota_bytes", None, _positivo(), env="ATTACHMENT_QUOTA_BYTES",
            descricao="Teto de anexos por workspace, em bytes",
        ),
        _Chave(
            "upload_max_bytes", None, _positivo(maximo=NGINX_BODY_LIMIT_BYTES),
            env="UPLOAD_MAX_BYTES",
            descricao="Tamanho máximo de um arquivo enviado, em bytes",
        ),
        # O teto é o `IMPORT_MAX_ROWS` do ambiente, e não um número redondo
        # daqui, porque ele já é aplicado ANTES desta chave: `CommitRequest.rows`
        # tem `Field(max_length=settings.IMPORT_MAX_ROWS)`, e o Pydantic recusa o
        # corpo antes de o handler existir. Com um teto maior, a tela gravava
        # 50.000, dizia "Configuração salva", e a importação seguia morrendo em
        # 5.001 linhas com um erro sobre comprimento de lista — a configuração
        # que reporta sucesso e não vale nada. Aqui o admin só APERTA o limite.
        _Chave(
            "import_max_rows", None,
            _positivo(maximo=lambda: settings.IMPORT_MAX_ROWS),
            env="IMPORT_MAX_ROWS",
            descricao="Teto de linhas por importação",
        ),
        _Chave(
            "rate_limit_auth_per_minute", None, _positivo(maximo=10_000),
            env="RATE_LIMIT_AUTH_PER_MINUTE",
            descricao="Tentativas de autenticação por minuto, por IP e rota",
        ),
        _Chave(
            "rate_limit_account_per_minute", None, _positivo(maximo=10_000),
            env="RATE_LIMIT_ACCOUNT_PER_MINUTE",
            descricao="Tentativas de autenticação por minuto, por conta alvo",
        ),
        _Chave(
            "maintenance_mode", False, _booleano,
            descricao="Só administradores acessam o site",
        ),
    ]
}


_cache: Dict[str, Any] = {}


def invalidate_cache() -> None:
    """Descarta o cache. Chamado após escrita e pelos testes."""
    _cache.clear()


def peek_cache(chave: str) -> Any:
    """Valor em cache, ou `None` se ainda não foi lido — SEM tocar o banco.

    Existe para o middleware de manutenção, que roda em toda requisição e não
    pode abrir uma sessão só para descobrir que a manutenção está desligada.
    `None` significa "não sei", não "falso": quem chama decide se vale a ida ao
    banco. Nenhuma chave tem `None` como valor legítimo, então a ambiguidade não
    existe na prática.
    """
    return _cache.get(chave)


def _serializa(valor: Any) -> str:
    # Decimal não é serializável por padrão e chegaria aqui vindo de um `Settings`
    # tipado como Decimal. Texto preserva a precisão; float a perderia.
    if isinstance(valor, Decimal):
        return json.dumps(str(valor))
    return json.dumps(valor)


def get(db: Session, chave: str) -> Any:
    """Valor efetivo de uma chave, com cache."""
    if chave not in CHAVES:
        raise KeyError(f"chave de configuração desconhecida: {chave}")
    if chave in _cache:
        return _cache[chave]

    linha = db.get(AppSetting, chave)
    if linha is None:
        valor = CHAVES[chave].padrao
    else:
        try:
            valor = CHAVES[chave].valida(json.loads(linha.value))
        except (ValueError, json.JSONDecodeError):
            # Linha corrompida (edição manual no banco, migração de formato) não
            # pode derrubar a rota que só queria saber um limite: cai no padrão,
            # que é sempre um valor válido.
            valor = CHAVES[chave].padrao
    _cache[chave] = valor
    return valor


def get_all(db: Session) -> Dict[str, Any]:
    """Todas as chaves com o valor efetivo — o que a tela de Admin mostra."""
    return {nome: get(db, nome) for nome in CHAVES}


def set_value(db: Session, chave: str, valor: Any, user_id: Optional[int] = None) -> Any:
    """Grava uma chave. Só `flush` — o commit é do chamador (ADR 0010).

    O cache é invalidado aqui e não no commit: se a transação for revertida, o
    pior que acontece é uma releitura do banco, que devolve o valor certo. O
    contrário — invalidar só no commit — deixaria a própria transação enxergando
    o valor velho que acabou de escrever.

    ATENÇÃO: invalidar aqui é necessário e NÃO é suficiente. Entre este `flush` e
    o commit do chamador, outra requisição que leia a mesma chave enxerga o valor
    ANTIGO (a escrita ainda não está visível) e o coloca no cache — onde ele
    ficaria para sempre, porque a invalidação já passou. Por isso quem grava
    invalida DE NOVO depois do commit; ver `admin.put_settings`.
    """
    if chave not in CHAVES:
        raise KeyError(f"chave de configuração desconhecida: {chave}")
    validado = CHAVES[chave].valida(valor)

    linha = db.get(AppSetting, chave)
    if linha is None:
        linha = AppSetting(key=chave, value=_serializa(validado))
        db.add(linha)
    else:
        linha.value = _serializa(validado)
    linha.updated_by_user_id = user_id
    from datetime import datetime, UTC
    linha.updated_at = datetime.now(UTC)
    db.flush()

    invalidate_cache()
    return validado


def is_overridden(db: Session, chave: str) -> bool:
    """Se o valor que está VALENDO veio do banco, ou ainda acompanha o `.env`.

    "Existe linha" não é a mesma pergunta, e responder por ela fazia a tela
    mentir nos dois casos em que `get` descarta a linha: valor corrompido (edição
    manual, migração de formato) e valor que deixou de passar na validação porque
    o teto mudou — baixar `IMPORT_MAX_ROWS` no `.env` invalida um número maior
    gravado antes. Nos dois, a tela mostrava o valor do ambiente com a marca de
    "gravado no banco", e o operador ia procurar no lugar errado.

    A checagem repete a de `get` de propósito: são a MESMA decisão, e o dia em
    que divergirem é o dia em que a tela volta a mentir.
    """
    linha = db.get(AppSetting, chave)
    if linha is None:
        return False
    try:
        CHAVES[chave].valida(json.loads(linha.value))
    except (ValueError, json.JSONDecodeError):
        return False
    return True
