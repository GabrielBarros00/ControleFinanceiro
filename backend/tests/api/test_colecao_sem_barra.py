"""Toda coleção responde COM e SEM a barra final (armadilha do 307).

O redirecionamento automático do Starlette responde 307, e nesse salto o
**cookie de sessão não acompanha**: a URL com a barra "errada" devolve 401 em vez
de funcionar. O projeto já tinha eliminado isso em `me_accounts`, `me_cards`,
`me_financing`, `me_income` e `admin` — e as duas coleções MAIS usadas, listar e
criar workspace e listar e criar lançamento, tinham ficado de fora.

O teste é uma VARREDURA e não uma lista: a coleção que nascer amanhã já entra.
"""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _formas_por_rota():
    """(método, caminho-base) → formas registradas (com e/ou sem barra)."""
    formas = {}
    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue
        caminho = rota.path
        com_barra = caminho.endswith("/") and len(caminho) > 1
        base = caminho[:-1] if com_barra else caminho
        for metodo in rota.methods - {"HEAD", "OPTIONS"}:
            formas.setdefault((metodo, base), set()).add(com_barra)
    return formas


def test_rota_com_barra_final_tem_sempre_a_irma_sem_barra():
    """A assimetria que quebra cliente, e só ela.

    A pergunta NÃO é "toda rota aceita as duas formas" — `/health` e
    `/auth/login` nascem sem barra e ninguém os chama com ela; exigir alias para
    todas seria ~78 rotas a mais sem defeito nenhum atrás.

    A pergunta é mais estreita: **existe alguma rota que só responde COM a barra?**
    Essa é a que quebra, porque a forma natural que um cliente escreve é a sem
    barra — e é ela que vira 307 e perde o cookie. Era o caso de listar/criar
    workspace e listar/criar lançamento, as duas coleções mais usadas do app.
    """
    so_com_barra = [
        f"{metodo} {base}"
        for (metodo, base), variantes in sorted(_formas_por_rota().items())
        if variantes == {True}
    ]
    assert not so_com_barra, (
        "rotas que só respondem com a barra final — a forma sem barra vira 307 "
        "e a sessão se perde: " + "; ".join(so_com_barra)
    )


@pytest.mark.parametrize("sufixo", ["", "/"])
def test_listar_lancamentos_funciona_com_e_sem_barra(sufixo, setup_data, override_get_session):
    """O caso concreto: sem a rota irmã, esta chamada voltava 401."""
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    res = client.get(f"/api/v1/workspaces/{ws.id}/transactions{sufixo}", headers=headers)
    assert res.status_code == 200, f"barra='{sufixo}' devolveu {res.status_code}"


@pytest.mark.parametrize("sufixo", ["", "/"])
def test_listar_workspaces_funciona_com_e_sem_barra(sufixo, setup_data, override_get_session):
    res = client.get(f"/api/v1/workspaces{sufixo}", headers=setup_data["headers1"])
    assert res.status_code == 200, f"barra='{sufixo}' devolveu {res.status_code}"
