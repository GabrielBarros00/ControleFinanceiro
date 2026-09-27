"""Nenhum modelo do app é construído com um campo que ele não tem.

Os schemas Pydantic do app usam o padrão `extra="ignore"`: um argumento com nome
que o modelo não conhece é DESCARTADO, sem erro. Foi assim que a importação de
extrato perdeu a categoria das despesas — `TransactionCreate(category_id=...)`,
campo que não existe (a categoria mora no item-sombra) — e respondeu "importado"
por meses, com 94% de cobertura na linha do defeito (auditoria de 2026-09-26, C1).

A varredura lê o código de `app/`, acha toda chamada `Modelo(campo=...)` cujo
`Modelo` resolve — pelos imports do próprio arquivo — para uma classe Pydantic do
app, e confere cada `campo` contra os campos (e aliases) dela. Resolver pelo
import, e não pelo nome solto, é o que evita confundir homônimos: há dois
`FinancingOut` e dois `DeleteResult` em módulos diferentes.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Iterator, Optional

from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parent.parent
APP = RAIZ / "app"

#: Chamadas conferidas hoje: ~380. O piso existe para pegar COLAPSO (a varredura
#: deixar de resolver os nomes e passar verde varrendo o vazio), não para vigiar
#: o número exato.
PISO = 300


def _modulo_de(caminho: Path) -> str:
    return ".".join(caminho.relative_to(RAIZ).with_suffix("").parts)


def _nomes_importados(arvore: ast.AST, modulo: str) -> dict[str, tuple[str, str]]:
    """`nome local → (módulo de origem, nome lá)`, de TODO `from x import y` do
    arquivo — inclusive os de dentro de função, que o app usa para evitar ciclo."""
    nomes: dict[str, tuple[str, str]] = {}
    for no in ast.walk(arvore):
        if not isinstance(no, ast.ImportFrom) or no.module is None:
            continue
        origem = no.module
        if no.level:
            base = modulo.split(".")[: -no.level]
            origem = ".".join([*base, no.module])
        for alias in no.names:
            nomes[alias.asname or alias.name] = (origem, alias.name)
    return nomes


def _classe(nome: str, modulo: str, importados: dict[str, tuple[str, str]]) -> Optional[type]:
    try:
        if nome in importados:
            origem, original = importados[nome]
            alvo = getattr(importlib.import_module(origem), original, None)
        else:
            alvo = getattr(importlib.import_module(modulo), nome, None)
    except ImportError:
        return None
    if isinstance(alvo, type) and issubclass(alvo, BaseModel) and alvo.__module__.startswith("app."):
        return alvo
    return None


def _aceitos(cls: type) -> set[str]:
    campos = cls.model_fields
    aceitos = set(campos) | {f.alias for f in campos.values() if f.alias}
    # Relacionamentos de tabela SQLModel também são argumentos legítimos.
    aceitos |= set(getattr(cls, "__sqlmodel_relationships__", {}) or {})
    return aceitos


def argumentos_desconhecidos(fonte: str, modulo: str) -> Iterator[tuple[int, str, list[str]] | None]:
    """Para cada chamada conferida: `None` se está certa, ou `(linha, modelo, campos)`."""
    arvore = ast.parse(fonte)
    importados = _nomes_importados(arvore, modulo)
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Name):
            continue
        chaves = [k.arg for k in no.keywords if k.arg]
        if not chaves:
            continue
        cls = _classe(no.func.id, modulo, importados)
        if cls is None or cls.model_config.get("extra") == "allow":
            continue
        desconhecidos = [c for c in chaves if c not in _aceitos(cls)]
        yield (no.lineno, cls.__name__, desconhecidos) if desconhecidos else None


def test_nenhum_modelo_recebe_campo_que_nao_tem():
    conferidas, erros = 0, []
    for caminho in sorted(APP.rglob("*.py")):
        modulo = _modulo_de(caminho)
        for achado in argumentos_desconhecidos(caminho.read_text(encoding="utf-8"), modulo):
            conferidas += 1
            if achado:
                linha, modelo, campos = achado
                erros.append(f"{caminho.relative_to(RAIZ)}:{linha}: {modelo}({', '.join(campos)})")

    assert conferidas >= PISO, (
        f"só {conferidas} chamadas conferidas (piso: {PISO}) — a varredura deixou de "
        "resolver os modelos e estaria passando verde sem medir nada"
    )
    assert not erros, (
        "argumento que o modelo não tem é DESCARTADO em silêncio pelo Pydantic:\n  "
        + "\n  ".join(erros)
    )


def test_a_varredura_pega_o_defeito_que_motivou_ela():
    """Controle: o caso real (C1) tem de ser acusado, e o certo não."""
    errado = (
        "from app.schemas.transaction import TransactionCreate\n"
        "TransactionCreate(title='x', category_id=1)\n"
    )
    certo = (
        "from app.schemas.transaction import TransactionItemCreate\n"
        "TransactionItemCreate(title='x', amount=1, category_id=1)\n"
    )
    modulo = "app.services.commands.account_imports"
    assert list(argumentos_desconhecidos(errado, modulo)) == [(2, "TransactionCreate", ["category_id"])]
    assert list(argumentos_desconhecidos(certo, modulo)) == [None]
