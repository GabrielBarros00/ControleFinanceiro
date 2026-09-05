"""A busca global não pode ser a porta dos fundos da privacidade (ADR 0018).

## Por que este arquivo existe ANTES da funcionalidade

Uma busca é, por definição, uma consulta que **atravessa todas as listas** —
lançamentos de todos os espaços, rendas, acertos, faturas. Cada uma dessas
listas tem hoje o seu filtro de visibilidade, aplicado no `select` que a monta.
Uma rota nova que varre tudo é exatamente o lugar onde alguém escreve
`where(Transaction.title.contains(termo))` e esquece o `scope_transactions` —
e o efeito não é uma tela errada: é um membro restrito lendo "Terapia" na busca,
uma despesa que a lista de lançamentos esconde dele.

O plano desta onda diz, com todas as letras, que **sem este teste a tarefa não
entra**. Ele é escrito primeiro e visto vermelho primeiro.

## O cenário

O mesmo `casa` de `test_privacy_matrix.py`, por três razões: ele já monta os
cinco perfis (papel × acesso), já tem uma despesa SÓ do dono e outra
compartilhada, e é o arquivo que qualquer pessoa vai abrir para entender a
matriz. Repetir a montagem noutro lugar seria criar uma segunda verdade sobre
quem vê o quê.

## O que se garante

1. Quem tem acesso completo acha a despesa solo do dono.
2. Quem é restrito **não acha** — nem por título exato, nem por pedaço.
3. Quem é restrito acha o que o envolve (senão a busca não serve para nada, e o
   teste acima seria satisfeito por uma rota que devolve lista vazia).
4. Quem não é membro do espaço não acha nada dele.
5. Renda é pessoal (ADR 0021): ninguém acha a renda de outra pessoa.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User

# O fixture `casa` vem daqui — a matriz de privacidade é a mesma.
from .test_privacy_matrix import casa_fixture  # noqa: F401

client = TestClient(app)


def _h(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


def _buscar(user: User, termo: str):
    r = client.get("/api/v1/me/search", params={"q": termo}, headers=_h(user))
    assert r.status_code == 200, r.text
    return r.json()


def _titulos(corpo) -> list[str]:
    """Todos os títulos de todos os grupos — a busca é multi-tipo."""
    achados = []
    for grupo in corpo.get("groups", []):
        achados.extend(item["title"] for item in grupo.get("items", []))
    return achados


@pytest.mark.parametrize("perfil", ["dono", "admin", "member_completo"])
def test_quem_ve_a_casa_acha_a_despesa_da_casa(casa, perfil):
    """Controle positivo: sem ele, "não devolver nada" passaria em tudo abaixo."""
    titulos = _titulos(_buscar(casa["u"][perfil], "Terapia"))
    assert "Terapia do dono" in titulos, (
        f"{perfil} tem acesso completo e não achou a despesa na busca — a rota "
        "está filtrando demais, e uma busca que não acha não é usada"
    )


@pytest.mark.parametrize("perfil", ["member_restrito", "viewer_restrito"])
def test_restrito_nao_acha_o_que_a_lista_esconde_dele(casa, perfil):
    """O furo que este arquivo existe para impedir."""
    titulos = _titulos(_buscar(casa["u"][perfil], "Terapia"))
    assert "Terapia do dono" not in titulos, (
        f"VAZAMENTO: {perfil} achou na busca uma despesa que a lista de "
        "lançamentos esconde dele (ADR 0018)"
    )


@pytest.mark.parametrize("perfil", ["member_restrito", "viewer_restrito"])
def test_restrito_acha_o_que_o_envolve(casa, perfil):
    """Contrapeso: a busca continua servindo para quem é restrito."""
    titulos = _titulos(_buscar(casa["u"][perfil], "Mercado"))
    assert "Mercado da casa" in titulos, (
        f"{perfil} tem split nessa despesa e não a achou — a correção de "
        "privacidade virou exclusão cega"
    )


def test_quem_nao_e_membro_nao_acha_nada_do_espaco(casa, db_session):
    """Isolamento entre espaços, na rota nova."""
    forasteiro = User(name="Forasteiro", email="fora@busca.com", password_hash="h")
    db_session.add(forasteiro)
    db_session.commit()
    db_session.refresh(forasteiro)

    titulos = _titulos(_buscar(forasteiro, "Mercado"))
    assert titulos == [], (
        f"VAZAMENTO: quem não é membro do espaço achou {titulos} na busca"
    )


def test_renda_de_outra_pessoa_nunca_aparece(casa):
    """Renda é pessoal e não pertence a espaço nenhum (ADR 0021)."""
    titulos = _titulos(_buscar(casa["u"]["member_restrito"], "Salário"))

    assert "Salário do dono" not in titulos, (
        "VAZAMENTO: a busca devolveu a renda de outra pessoa"
    )
    # E a própria continua aparecendo — de novo, o contrapeso.
    assert "Salário do restrito" in titulos


def test_busca_curta_demais_nao_varre_o_banco(casa):
    """Um caractere casaria com quase tudo e viria caro; a rota recusa."""
    r = client.get(
        "/api/v1/me/search", params={"q": "a"}, headers=_h(casa["u"]["dono"]),
    )
    assert r.status_code == 422, (
        f"esperava recusa para termo de 1 caractere, veio {r.status_code}"
    )
