"""O glossário (`CONTEXT.md`) só cita nomes que existem no código.

O valor do glossário é apontar o nome CERTO: "competência da renda é
`Income.received_at`". Se o campo for renomeado e o glossário não, ele passa a
ensinar errado, e em silêncio, porque markdown não quebra build nenhum. Este
teste lê cada nome entre crases do CONTEXT.md e confere contra o código:

- `Classe.atributo`: o arquivo que define a classe tem de conter o atributo;
- identificador com `_` ou em camelCase/PascalCase (`settled_at`, `parseApiDay`,
  `CashFlowService`): tem de aparecer no backend (`app/`) ou no frontend (`src/`);
- nome pontilhado minúsculo (`finance.read`): tem de aparecer literalmente.

Palavra solta minúscula (`owner`, `equal`), caminho e rota ficam de fora: são
genéricos demais para uma busca textual provar alguma coisa.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CONTEXT = RAIZ / "CONTEXT.md"
FONTES = [
    *(RAIZ / "backend" / "app").rglob("*.py"),
    *(RAIZ / "frontend" / "src").rglob("*.ts"),
    *(RAIZ / "frontend" / "src").rglob("*.tsx"),
]

_CLASSE_ATRIBUTO = re.compile(r"^([A-Z][A-Za-z0-9]+)\.([A-Za-z_][A-Za-z0-9_]*)$")
_NOME_INICIAL = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*")


def _textos() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8", errors="replace") for p in FONTES if "__tests__" not in p.parts}


def _definicoes(textos: dict[Path, str]) -> dict[str, str]:
    """Nome da classe → texto do arquivo que a define."""
    defs: dict[str, str] = {}
    for texto in textos.values():
        for nome in re.findall(r"^class ([A-Z][A-Za-z0-9]*)\b", texto, flags=re.M):
            defs.setdefault(nome, texto)
    return defs


def _e_identificador_de_codigo(nome: str) -> bool:
    if "." in nome:
        return True
    tem_minuscula = any(c.islower() for c in nome)
    tem_maiuscula = any(c.isupper() for c in nome)
    return "_" in nome or (tem_minuscula and tem_maiuscula)


def nomes_citados(markdown: str) -> list[str]:
    """Os identificadores de código que o texto cita entre crases."""
    nomes = []
    for trecho in re.findall(r"`([^`\n]+)`", markdown):
        casou = _NOME_INICIAL.match(trecho.strip())
        if not casou:
            continue
        nome = casou.group(0).rstrip(".")
        if _e_identificador_de_codigo(nome):
            nomes.append(nome)
    return sorted(set(nomes))


def nomes_ausentes(markdown: str) -> list[str]:
    textos = _textos()
    corpus = "\n".join(textos.values())
    definicoes = _definicoes(textos)
    ausentes = []
    for nome in nomes_citados(markdown):
        par = _CLASSE_ATRIBUTO.match(nome)
        if par:
            classe, atributo = par.groups()
            arquivo = definicoes.get(classe)
            if arquivo is None or not re.search(rf"\b{re.escape(atributo)}\b", arquivo):
                ausentes.append(nome)
        elif not re.search(rf"(?<![\w.]){re.escape(nome)}(?![\w])", corpus):
            ausentes.append(nome)
    return ausentes


def test_todo_nome_do_glossario_existe_no_codigo():
    markdown = CONTEXT.read_text(encoding="utf-8")
    citados = nomes_citados(markdown)
    # Denominador: se a extração quebrar, o teste passaria vazio.
    assert len(citados) > 60, f"só {len(citados)} nomes extraídos do CONTEXT.md"
    assert nomes_ausentes(markdown) == [], (
        "o CONTEXT.md cita nomes que não existem mais no código. Atualize o glossário "
        "junto com a renomeação"
    )


def test_a_varredura_pega_nome_inventado():
    """Controle: um nome que não existe TEM de ser apontado, nas três formas."""
    falso = (
        "`Income.campo_que_nao_existe`, `ClasseQueNaoExiste.algo`, "
        "`funcao_que_nao_existe`, `parseApiNada`, `escopo.inventado`, e `Income.settled_at`"
    )
    assert nomes_ausentes(falso) == sorted([
        "ClasseQueNaoExiste.algo", "Income.campo_que_nao_existe", "escopo.inventado",
        "funcao_que_nao_existe", "parseApiNada",
    ])
