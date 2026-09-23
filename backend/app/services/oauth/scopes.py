"""Escopos OAuth do servidor MCP — o que cada conexão de IA pode fazer.

Um escopo por ÁREA DE RISCO, não por endpoint: a pessoa entende "registrar
lançamentos" e "movimentar contas" na tela de consentimento; ela não entende
`POST /transactions`. `finance.read` é obrigatório porque nenhuma escrita
funciona sem enxergar o que está escrevendo (resolver "Nubank" exige ler os
cartões).

O escopo é só a primeira de três travas: a tool ainda passa pelo papel no espaço
(`require_role`) e pela visibilidade (`access_policy`). Escopo sobra; nunca
autoriza sozinho.
"""
from dataclasses import dataclass
from typing import Iterable, List, Optional

FINANCE_READ = "finance.read"
TRANSACTIONS_WRITE = "transactions.write"
ACCOUNTS_WRITE = "accounts.write"
INCOME_WRITE = "income.write"
SETTLEMENTS_WRITE = "settlements.write"
PLANNING_WRITE = "planning.write"


@dataclass(frozen=True)
class ScopeInfo:
    scope: str
    label: str
    description: str
    required: bool = False


#: Ordem canônica (é a ordem da tela e dos metadados).
SCOPES: tuple[ScopeInfo, ...] = (
    ScopeInfo(
        FINANCE_READ,
        "Ver seus dados financeiros",
        "Lançamentos, faturas, contas, saldos, rendas, dívidas e relatórios — o mesmo que você vê no app.",
        required=True,
    ),
    ScopeInfo(
        TRANSACTIONS_WRITE,
        "Registrar e editar lançamentos",
        "Criar, editar, categorizar, marcar como pago, excluir e importar lançamentos (com parcelas e divisões).",
    ),
    ScopeInfo(
        ACCOUNTS_WRITE,
        "Movimentar contas e cartões",
        "Pagar fatura, transferir entre suas contas e ajustar saldo.",
    ),
    ScopeInfo(
        INCOME_WRITE,
        "Registrar e editar rendas",
        "Lançar rendas e marcar como recebidas ou canceladas.",
    ),
    ScopeInfo(
        SETTLEMENTS_WRITE,
        "Registrar acertos entre pessoas",
        "Registrar e desfazer pagamentos de dívidas entre membros de um espaço.",
    ),
    ScopeInfo(
        PLANNING_WRITE,
        "Planejamento",
        "Criar e editar recorrências, orçamentos e categorias.",
    ),
)

ALL_SCOPES: tuple[str, ...] = tuple(s.scope for s in SCOPES)
REQUIRED_SCOPES: tuple[str, ...] = tuple(s.scope for s in SCOPES if s.required)
_BY_NAME = {s.scope: s for s in SCOPES}

#: Pedidos comuns de clientes genéricos que não significam nada aqui. Aceitos e
#: descartados em vez de recusados: o Claude acrescenta `offline_access` quando
#: quer refresh (e refresh sai sempre), e recusar quebraria a conexão por um
#: escopo que não protege nada.
IGNORED_SCOPES = frozenset({"offline_access"})


class InvalidScope(ValueError):
    pass


def info(scope: str) -> ScopeInfo:
    return _BY_NAME[scope]


def canonical(scopes: Iterable[str]) -> List[str]:
    """Deduplica e ordena pela ordem canônica."""
    pedido = set(scopes)
    return [s for s in ALL_SCOPES if s in pedido]


def parse(value: Optional[str], *, default_all: bool = True) -> List[str]:
    """`"a b c"` → lista canônica. Escopo desconhecido é `InvalidScope`.

    Sem escopo pedido, o padrão é TUDO que o servidor oferece — é o que a
    especificação manda o cliente pedir quando o 401 não sugere nada, e a tela
    de consentimento deixa a pessoa desmarcar as escritas.
    """
    if value is None or not value.strip():
        return list(ALL_SCOPES) if default_all else []
    itens = [s for s in value.split() if s]
    desconhecidos = [s for s in itens if s not in _BY_NAME and s not in IGNORED_SCOPES]
    if desconhecidos:
        raise InvalidScope(f"Escopo(s) desconhecido(s): {' '.join(desconhecidos)}")
    return canonical(s for s in itens if s in _BY_NAME)


def to_string(scopes: Iterable[str]) -> str:
    return " ".join(canonical(scopes))


def split(value: str) -> List[str]:
    return canonical(value.split())
