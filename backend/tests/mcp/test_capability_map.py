"""O mapa de capacidades tem denominador: toda rota do app está lá, e nada além delas.

Rota nova no REST sem decisão aqui reprova — é o que impede uma funcionalidade
de nascer "esquecida" pelo agente (ou exposta por acidente, sem motivo escrito).
"""
from __future__ import annotations

from app.main import app
from app.mcp.capability_map import FICHAS, ROTAS
from app.mcp.registry import REGISTRY
from app.mcp.server import get_server


def _rotas_do_openapi() -> set[str]:
    # Só as rotas do produto: `tests/api/test_error_format.py` pendura rotas-bomba
    # (`/trigger-500`) no app e elas sobrevivem ao resto da sessão.
    caminhos = app.openapi()["paths"]
    return {
        f"{metodo.upper()} {caminho}"
        for caminho, ops in caminhos.items()
        if caminho == "/" or caminho.startswith("/api/")
        for metodo in ops
    }


def test_toda_rota_do_app_tem_decisao():
    do_app = _rotas_do_openapi()
    assert len(do_app) > 150  # denominador: a varredura enxerga o app
    faltando = sorted(do_app - set(ROTAS))
    sobrando = sorted(set(ROTAS) - do_app)
    assert not faltando, f"rotas sem decisão no capability_map: {faltando}"
    assert not sobrando, f"entradas do capability_map que não existem mais: {sobrando}"


def test_cada_rota_tem_tool_ou_motivo():
    for chave, rota in ROTAS.items():
        assert rota.capacidade, chave
        assert rota.tools or rota.nota, f"{chave}: sem tool e sem motivo"


def test_tools_citadas_existem_e_toda_tool_e_citada():
    get_server()
    citadas = {t for r in ROTAS.values() for t in r.tools}
    assert citadas <= set(REGISTRY), citadas - set(REGISTRY)
    assert set(REGISTRY) <= citadas, f"tools sem funcionalidade do app mapeada: {set(REGISTRY) - citadas}"
    assert set(FICHAS) == set(REGISTRY), set(FICHAS) ^ set(REGISTRY)


def test_capability_map_md_em_dia():
    from app.mcp.docs import DESTINO_MAPA, render_capability_map

    assert DESTINO_MAPA.read_text(encoding="utf-8") == render_capability_map(), "rode `python -m app.mcp.docs` e comite"
