"""Todo corpo de requisição da API recusa campo desconhecido (auditoria 2026-09-26, A1).

O padrão do Pydantic é `extra="ignore"`: um campo que o schema não tem é jogado
fora em silêncio. Foi assim que a importação de extrato mandava `category_id` a
um schema que não o tinha, a API respondia sucesso, e a despesa ficava "Sem
categoria" (C1). Com `extra="forbid"`, o mesmo erro vira um 422 que diz o nome do
campo — na hora, e não semanas depois, numa tela sem categoria.

A varredura parte das rotas (a travessia pública do FastAPI, `rotas_da_api`) e
desce pelos modelos aninhados — a lista de pagadores dentro do lançamento
também é entrada.
"""
import typing

from pydantic import BaseModel, ConfigDict

from tests.support.rotas import rotas_da_api

# Piso: hoje são 69. Pega o colapso da travessia (varredura verde por não ver
# nada), não a remoção normal de uma rota.
_PISO = 60


def _modelos_em(tipo, achados: set) -> None:
    if typing.get_origin(tipo) is not None:
        for argumento in typing.get_args(tipo):
            _modelos_em(argumento, achados)
        return
    if isinstance(tipo, type) and issubclass(tipo, BaseModel) and tipo not in achados:
        achados.add(tipo)
        for campo in tipo.model_fields.values():
            _modelos_em(campo.annotation, achados)


def _corpos_de_requisicao() -> set:
    achados: set = set()
    for rota in rotas_da_api():
        for parametro in rota.dependant.body_params:
            _modelos_em(parametro.field_info.annotation, achados)
    return achados


def _frouxos(modelos) -> list[str]:
    return sorted(
        f"{m.__module__}.{m.__name__}" for m in modelos if m.model_config.get("extra") != "forbid"
    )


def test_todo_corpo_de_requisicao_recusa_campo_desconhecido():
    corpos = _corpos_de_requisicao()
    assert len(corpos) >= _PISO, f"a varredura viu só {len(corpos)} modelos (piso {_PISO})"
    frouxos = _frouxos(corpos)
    assert frouxos == [], (
        "Schema de ENTRADA sem `model_config = ConfigDict(extra=\"forbid\")` — um campo "
        "que ele não tem seria descartado em silêncio (foi o defeito C1):\n  "
        + "\n  ".join(frouxos)
    )


def test_o_detector_enxerga_um_modelo_frouxo_e_um_aninhado():
    """Controle: sem esta prova, um erro na varredura a deixaria verde para sempre."""

    class Parte(BaseModel):
        valor: int

    class Entrada(BaseModel):
        model_config = ConfigDict(extra="forbid")
        partes: list[Parte]

    achados: set = set()
    _modelos_em(Entrada, achados)
    assert achados == {Entrada, Parte}
    assert _frouxos(achados) == [f"{Parte.__module__}.{Parte.__name__}"]
