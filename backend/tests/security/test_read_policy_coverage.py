"""Tripwire: nenhum GET de workspace escapa da política de visibilidade (ADR 0018).

`test_privacy_matrix.py` prova que os endpoints de HOJE estão escopados. Este
arquivo protege o AMANHÃ: percorre o router de verdade e falha quando aparece uma
leitura nova que não consulta a política nem foi declarada como dispensada.

Por que existe: o vazamento que a auditoria encontrou não veio de ninguém decidir
expor dado alheio — veio de 15 rotas escritas em momentos diferentes, cada uma
filtrando `workspace_id + deleted_at` porque era o que a rota vizinha fazia. Sem um
teste que force a decisão, a 16ª nasce igual. Aqui o custo de acertar é uma linha;
o de errar é uma falha de teste com o nome do endpoint.

Mesmo espírito do `test_model_registry.py`: uma varredura que impede o esquecimento
de reabrir um problema já resolvido.
"""
import inspect
import re

from tests.support.rotas import rotas_da_api

# Símbolos que contam como "esta rota consultou a política"
_SIMBOLOS_DE_POLITICA = (
    "access_policy",
    "assert_can_read",
    "card_scope",
    "get_visible_transaction",
    "has_full_access",
    "income_of_workspace",
    "income_visible_to",
    "involvement_filter",
    "involved_transaction_ids",
    "owner_scope",
    "participant_scope",
    "scope_transactions",
    "shared_or_mine_scope",
    "transaction_scope",
    "viewer_user_id",
    "full_access",
)

# Leituras DISPENSADAS, cada uma com o motivo. Acrescentar aqui é uma decisão
# consciente sobre dado alheio — é exatamente o ponto de atrito que o teste quer
# criar. Chave: "<módulo>.<função>".
_DISPENSADAS = {
    # Vocabulário compartilhado do workspace, não valor financeiro: sem categoria
    # e sem tag ninguém consegue classificar a própria despesa.
    "categories.list_categories": "vocabulário compartilhado (não é valor)",
    "tags.list_tags": "vocabulário compartilhado (não é valor)",
    # Gate de PAPEL, mais estrito que o de acesso: só admin+ (require_role).
    "audit.list_audit": "require_role(admin) — gate de papel",
    "members.list_invites": "require_role(admin) — gate de papel",
    # Quem é membro e com que papel não é dado financeiro; e-mail já é mascarado
    # para viewer em `_member_read`.
    "members.list_members": "identidade dos membros, com e-mail mascarado",
    # Metadado do próprio workspace (nome, moeda-base, contagem de membros).
    "workspaces.get_workspace": "metadado do workspace, não valor",
    "workspaces.preview_base_currency_change": "require_role(admin) — gate de papel",
    # Cotação de moeda é dado público de mercado, igual para todo mundo.
    "analytics.get_exchange_rate": "cotação pública de mercado",
    # Já filtra por dono INCONDICIONALMENTE (ADR 0017), mais estrito que a
    # política: nem owner nem admin veem a meta pessoal de outro membro.
    "analytics.list_estimates": "filtro por dono incondicional (mais estrito)",
}


def _rotas_de_leitura():
    for rota in rotas_da_api():
        if "GET" not in rota.methods or "{workspace_id}" not in rota.path:
            continue
        yield rota


def _fontes_relacionadas(funcao) -> str:
    """Fonte da função MAIS a dos helpers do próprio módulo que ela chama.

    Quase toda rota delega a visibilidade a um `_get_x_or_404`, então olhar só o
    corpo da rota daria falso negativo. Uma expansão de um nível resolve os casos
    reais sem virar análise estática de verdade.
    """
    try:
        fonte = inspect.getsource(funcao)
    except (OSError, TypeError):
        return ""

    modulo = inspect.getmodule(funcao)
    partes = [fonte]
    for nome, obj in vars(modulo).items():
        if not nome.startswith("_") or not inspect.isfunction(obj):
            continue
        # Só helpers efetivamente chamados nesta rota
        if re.search(rf"\b{re.escape(nome)}\s*\(", fonte):
            try:
                partes.append(inspect.getsource(obj))
            except (OSError, TypeError):
                pass
    return "\n".join(partes)


def test_todo_get_de_workspace_consulta_a_politica():
    rotas = list(_rotas_de_leitura())
    assert rotas, "o router não devolveu nenhuma leitura de workspace — teste inútil"

    sem_politica = []
    for rota in rotas:
        modulo = rota.endpoint.__module__.split(".")[-1]
        chave = f"{modulo}.{rota.endpoint.__name__}"
        if chave in _DISPENSADAS:
            continue
        fonte = _fontes_relacionadas(rota.endpoint)
        if not any(simbolo in fonte for simbolo in _SIMBOLOS_DE_POLITICA):
            sem_politica.append(f"{chave}  ({rota.path})")

    assert not sem_politica, (
        "Leitura de workspace sem política de visibilidade (ADR 0018):\n  "
        + "\n  ".join(sem_politica)
        + "\n\nEscope a consulta com app.domain.access_policy, ou — se a rota"
        "\ngenuinamente não expõe dado financeiro alheio — declare em"
        "\n_DISPENSADAS, com o motivo."
    )


def test_dispensas_nao_apodrecem():
    """Dispensa de rota que não existe mais é lixo que esconde a próxima.

    Sem isto, renomear uma rota deixaria a dispensa antiga no arquivo e a rota
    nova entraria sem política, sem ninguém notar.
    """
    existentes = {
        f"{r.endpoint.__module__.split('.')[-1]}.{r.endpoint.__name__}"
        for r in _rotas_de_leitura()
    }
    orfas = sorted(set(_DISPENSADAS) - existentes)
    assert not orfas, f"Dispensas apontando para rotas que não existem mais: {orfas}"
