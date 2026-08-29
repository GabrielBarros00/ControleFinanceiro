"""A cadeia de migração tem UMA cabeça.

Este gate existe por um episódio concreto, e o que ele economiza não é a falha —
é o diagnóstico.

Duas branches abertas do mesmo ponto criaram uma migração cada (ADR 0032 e ADR
0033), ambas com `down_revision` apontando para a mesma revisão. Enquanto viveram
separadas, as duas passavam verdes. No instante em que a primeira entrou na main,
a segunda virou uma cabeça irmã — e `alembic upgrade head` recusa escolher entre
duas.

O estrago foi desproporcional à causa: **cinco jobs vermelhos de uma vez**
(backend, backend-postgres, e2e, e2e-windows, prod-stack), porque todos precisam
do banco migrado. E a mensagem que aparecia estava enterrada no meio de um teste
de outra revisão, dizendo "specify a specific target revision" — que descreve o
sintoma para quem já sabe o que aconteceu, e não diz a ninguém que o conserto é
reancorar o `down_revision` da migração mais nova.

O `alembic check` NÃO pega isto: ele compara os models com o banco, e cada cabeça
sozinha está perfeitamente consistente.
"""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parent.parent


def _script() -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(config)


def test_existe_uma_unica_cabeca():
    cabecas = _script().get_heads()
    assert len(cabecas) == 1, (
        "A cadeia de migração se ramificou: há mais de uma cabeça, e "
        "`alembic upgrade head` recusa escolher entre elas — o que derruba a "
        "migração, a suíte, o e2e e a subida da stack de uma vez.\n\n"
        "Acontece quando duas branches criam uma migração cada a partir do mesmo "
        "ponto. O conserto é reancorar a MAIS NOVA: mude o `down_revision` dela "
        "para a revisão da outra (a que já entrou na main), deixando a cadeia "
        "linear. Não é preciso mesclar nem recriar nada.\n\n"
        f"Cabeças encontradas: {sorted(cabecas)}"
    )


def test_toda_revisao_alcanca_a_base():
    """Nenhuma migração órfã — `down_revision` apontando para revisão inexistente.

    Um `down_revision` com um typo produz uma segunda base, e o sintoma é o mesmo
    do teste acima visto do outro lado: a revisão simplesmente nunca roda, em
    silêncio, até alguém reparar que a coluna não existe em produção.
    """
    script = _script()
    revisoes = {r.revision for r in script.walk_revisions()}
    for revisao in script.walk_revisions():
        anterior = revisao.down_revision
        if anterior is None:
            continue  # a base
        alvos = anterior if isinstance(anterior, (tuple, list)) else (anterior,)
        for alvo in alvos:
            assert alvo in revisoes, (
                f"a revisão {revisao.revision} aponta para {alvo}, que não existe"
            )
