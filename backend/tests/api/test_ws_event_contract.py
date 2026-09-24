"""Contrato de tempo real entre backend e frontend.

Todo tipo passado a publish_event() precisa existir em
`frontend/src/lib/ws-events.ts` (WS_EVENT_TYPES) — é lá que o cliente decide
o que invalidar. Um tipo novo que não esteja na lista chega ao navegador e não
atualiza tela nenhuma, falha silenciosa que já aconteceu com `recurring_income.*`
e `tag.*`.

Também garante o inverso: toda rota que MUTA estado publica algum evento (senão
a mudança só aparece para quem deu F5).
"""
import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
WS_EVENTS_TS = BACKEND.parent / "frontend" / "src" / "lib" / "ws-events.ts"

# Rotas que mudam a requisição mas não o estado do workspace (dry-run, auth,
# leitura disfarçada de POST) — não têm o que transmitir.
SEM_EVENTO_ESPERADO = {
    "register", "login", "logout", "refresh_session", "change_password",
    "forgot_password", "reset_password",
    "preview_transaction",        # dry-run: não persiste nada
    "preview_recurring",          # idem: POST só porque leva corpo (ADR 0030)
    "parse_csv",                  # só interpreta o arquivo
    "parse_account_statement",    # idem, o extrato de conta (ADR 0037)
    "simulate_early_settlement",  # simulação de quitação
    "create_workspace",           # ninguém está na sala do ws que acabou de nascer
    # Notificações são de escopo PESSOAL, não de workspace: o canal de tempo
    # real é por sala de workspace, e o destinatário de um convite ainda NÃO é
    # membro. Marcar como lida também é um ato do próprio usuário, na aba dele —
    # não há a quem transmitir.
    "mark_notification_read",
    "mark_all_notifications_read",
    # Moeda de relatório é ajuste PESSOAL (ADR 0020): muda só como os números do
    # próprio usuário são expressos, e o canal de tempo real é por sala de
    # WORKSPACE — não existe sala para a qual transmitir. Quem mudou já recebe o
    # valor novo na resposta.
    "set_report_currency",
    # Onboarding cria a renda e o cartão do próprio usuário, que são recursos
    # PESSOAIS (ADR 0021) — não pertencem a workspace nenhum e não há sala para
    # a qual transmitir. Quem acabou de preencher o formulário é a única pessoa
    # a quem esse dado interessa, e ele já chega na resposta.
    "finish_onboarding",
}


def _published_event_types() -> set[str]:
    tipos = set()
    padrao = re.compile(r'publish_event\(\s*[^)]*?"([a-z_]+\.[a-z_]+)"', re.S)
    for py in APP.rglob("*.py"):
        tipos.update(padrao.findall(py.read_text(encoding="utf-8")))
    return tipos


def _frontend_event_types() -> set[str]:
    texto = WS_EVENTS_TS.read_text(encoding="utf-8")
    bloco = texto.split("WS_EVENT_TYPES = [", 1)[1].split("] as const", 1)[0]
    return set(re.findall(r"'([a-z_]+\.[a-z_]+)'", bloco))


def test_frontend_conhece_todo_evento_publicado():
    backend = _published_event_types()
    frontend = _frontend_event_types()
    assert backend, "nenhum publish_event encontrado — regex quebrou?"

    faltando = backend - frontend
    assert not faltando, (
        f"Eventos publicados que o frontend não trata: {sorted(faltando)}. "
        f"Adicione a WS_EVENT_TYPES em {WS_EVENTS_TS.name} e mapeie o prefixo."
    )


def test_frontend_nao_lista_evento_inexistente():
    """Lista inflada esconde tipo removido e dá falsa sensação de cobertura."""
    orfaos = _frontend_event_types() - _published_event_types()
    assert not orfaos, f"Eventos listados no frontend que o backend não publica: {sorted(orfaos)}"


# Módulos de RECURSO PESSOAL (ADR 0021): renda, cartão, conta e financiamento
# são de uma pessoa só e não moram em workspace nenhum. O canal de tempo real é
# por SALA DE WORKSPACE — não existe sala para a qual transmitir, e inventar uma
# seria transmitir dado pessoal a uma sala de outras pessoas. Quem mudou já
# recebe o valor novo na resposta, e é a única pessoa a quem isso interessa.
#
# `me_financing.py` publica evento no caso em que a mudança TOCA um workspace
# (pagar a parcela criando a despesa lá), então não está isento por inteiro — as
# rotas dele que não publicam são as que só mexem no cadastro pessoal.
#
# `me_push.py` é o caso mais extremo da regra: uma inscrição de push é de uma
# pessoa E de um NAVEGADOR dela. Não há sala para transmitir, e transmitir seria
# contar a outras pessoas em que aparelhos alguém recebe aviso (ADR 0018/0033).
#
# `me_balance.py` é o caso mais forte da regra depois do `me_push`: saldo,
# extrato, ajuste e transferência são o dado mais sensível que o app guarda
# (ADR 0034/§38). Transmiti-los para a sala de um workspace entregaria o extrato
# bancário de uma pessoa a quem apenas divide despesa com ela.
#
# `me_settlements.py` é leitura, com UMA exceção: o credor declarando em qual
# conta o acerto caiu (ADR 0034). Isso não muda nada do acerto que os outros
# membros veem — o valor, a direção e a data seguem iguais —, e transmiti-lo
# entregaria à sala do espaço a conta bancária de quem recebeu.
MODULOS_PESSOAIS = {
    "me_income.py", "me_cards.py", "me_accounts.py", "me_balance.py",
    "me_financing.py", "me_push.py", "me_settlements.py",
}

# Módulo de PLATAFORMA (ADR 0026): mesma razão dos pessoais, num terceiro eixo.
# Papel de usuário, configuração do site e convite de cadastro não pertencem a
# workspace nenhum, e o canal de tempo real é por SALA DE WORKSPACE. Não há sala
# para a qual transmitir — e transmitir seria pior que não transmitir: um evento
# de "usuário desativado" chegando à sala de uma casa contaria a todos os membros
# dela uma decisão administrativa que não é assunto daquela casa.
#
# As consequências que os membros PRECISAM ver já chegam por outros caminhos: uma
# conta desativada perde as sessões na hora, e quem sai de um workspace continua
# publicando `member.*` pela rota de membros, que não é deste módulo.
MODULOS_DE_PLATAFORMA = {"admin.py"}

# Integração com agentes de IA (ADR 0035): o authorization server OAuth e a tela
# "Integrações com IA" mexem em CONEXÕES da própria pessoa (concessões e tokens),
# que não pertencem a workspace nenhum. Mesma razão dos módulos pessoais: não há
# sala para a qual transmitir — e transmitir contaria à casa quais aplicativos de
# IA alguém conectou. O que um agente MUDA em um workspace passa pelos comandos
# (`services/commands`), que publicam o evento como a tela publicaria.
MODULOS_DE_CONEXAO = {"oauth.py", "ai_integrations.py"}


def _comandos_que_publicam() -> set[str]:
    """Funções de `services/commands/*` que publicam evento — direto ou por um
    helper do próprio módulo (um nível, como o `_full_edit` da edição completa).

    Desde o ADR 0035 a rota REST de escrita é uma casca: chama o comando, comita
    e responde. O evento continua sendo publicado, só que um nível abaixo — e é
    esse nível que a varredura precisa enxergar para não aprovar uma rota que
    delega a um comando MUDO.
    """
    publicam: set[str] = set()
    for py in sorted((APP / "services" / "commands").glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        funcoes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

        def publica_direto(no) -> bool:
            return any(
                isinstance(n, ast.Call) and getattr(n.func, "id", "") == "publish_event"
                for n in ast.walk(no)
            )

        diretas = {nome for nome, no in funcoes.items() if publica_direto(no)}
        for nome, no in funcoes.items():
            chama = {getattr(n.func, "id", "") for n in ast.walk(no) if isinstance(n, ast.Call)}
            if nome in diretas or chama & diretas:
                publicam.add(nome)
    return publicam


def _mutating_routes_without_event() -> list[str]:
    achados = []
    comandos = _comandos_que_publicam()
    for py in sorted((APP / "api" / "routes").glob("*.py")):
        if py.name in MODULOS_PESSOAIS or py.name in MODULOS_DE_PLATAFORMA or py.name in MODULOS_DE_CONEXAO:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            muta = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in ("post", "put", "patch", "delete")
                for d in node.decorator_list
            )
            if not muta or node.name in SEM_EVENTO_ESPERADO:
                continue
            publica = any(
                isinstance(n, ast.Call)
                and (
                    getattr(n.func, "id", "") == "publish_event"
                    # `tx_cmd.create_transaction(...)`: delega a um comando que publica
                    or (isinstance(n.func, ast.Attribute) and n.func.attr in comandos)
                )
                for n in ast.walk(node)
            )
            if not publica:
                achados.append(f"{py.name}::{node.name}")
    return achados


def test_varredura_de_comandos_enxerga_os_comandos():
    """Sem denominador a varredura aprova qualquer rota que delegue a um comando
    — inclusive se a leitura dos comandos quebrar e devolver vazio."""
    assert {"create_transaction", "update_transaction", "delete_transaction"} <= _comandos_que_publicam()


def test_toda_rota_mutante_publica_evento():
    faltando = _mutating_routes_without_event()
    assert not faltando, (
        "Rotas que mudam estado sem publicar evento (a mudança não chega em "
        f"tempo real a ninguém): {faltando}"
    )


@pytest.mark.parametrize("tipo", sorted(_published_event_types()))
def test_tipo_segue_o_formato_recurso_ponto_acao(tipo):
    assert re.fullmatch(r"[a-z_]+\.[a-z_]+", tipo), f"formato inesperado: {tipo}"
