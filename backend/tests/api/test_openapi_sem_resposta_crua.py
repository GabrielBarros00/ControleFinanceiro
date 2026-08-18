"""Nenhuma rota pode devolver um objeto sem forma declarada.

O que este teste guarda não é estilo — é o contrato com o frontend. Sem
`response_model` (ou com `Dict[str, Any]`), o OpenAPI diz "objeto e boa sorte", o
`npm run typegen` gera `{[key: string]: unknown}` — ou `unknown` puro — e o
cliente preenche o vazio com interfaces escritas à mão que divergem em silêncio.

Isso já custou caro duas vezes:

- o ADR 0022 registra `/me/*` devolvendo `Dict[str, Any]` com o frontend mantendo
  interfaces manuais divergentes;
- a confirmação da troca de moeda-base — operação que REESCREVE todo o histórico
  financeiro — passou a exibir "undefined renda(s), undefined fatura(s)" com o
  TypeScript verde e o CI verde, porque não havia tipo para divergir.

Sem allowlist, de propósito. Uma exceção "temporária" aqui é como as nove rotas
de antes nasceram: nenhuma delas foi decidida, todas foram herdadas.
"""
import pytest

from app.main import app

#: As TRÊS rotas que não devolvem JSON. Não é uma allowlist de dívida: é a lista
#: fechada do que responde outra coisa — bytes de arquivo e redirecionamentos de
#: OAuth. Uma rota nova aqui é uma decisão, não um esquecimento.
ROTAS_SEM_CORPO_JSON = {
    # Devolve o ANEXO (`FileResponse`), não metadados.
    ("/api/v1/workspaces/{workspace_id}/attachments/{attachment_id}", "get"),
    # Redirecionam para o provedor e de volta (`RedirectResponse`).
    ("/api/v1/auth/google/login", "get"),
    ("/api/v1/auth/google/callback", "get"),
}


def _schema_de_resposta(operacao: dict) -> dict | None:
    """O schema do corpo 200/201, já resolvido para o dict do OpenAPI."""
    for codigo in ("200", "201"):
        resposta = operacao.get("responses", {}).get(codigo)
        if not resposta:
            continue
        conteudo = resposta.get("content", {}).get("application/json")
        # Sem `content` = sem corpo declarado (204, arquivo, redirect).
        return conteudo.get("schema") if conteudo else None
    return None


def _rotas_com_resposta_json():
    spec = app.openapi()
    for caminho, metodos in spec["paths"].items():
        for metodo, operacao in metodos.items():
            if metodo not in ("get", "post", "put", "patch", "delete"):
                continue
            if (caminho, metodo) in ROTAS_SEM_CORPO_JSON:
                continue
            yield caminho, metodo, operacao


def _e_objeto_sem_forma(schema: dict | None) -> bool:
    """`{}`, `{"type": "object"}` solto ou `additionalProperties: true`.

    São as três formas que `Dict[str, Any]` e a ausência de `response_model`
    produzem — todas indistinguíveis de "não sei o que isto devolve".
    """
    if schema is None:
        return False
    if not schema:
        return True
    if schema.get("additionalProperties") is True:
        return True
    if schema.get("type") == "object" and not schema.get("properties") and "$ref" not in schema:
        return True
    # Lista de objetos sem forma vale o mesmo: `List[Dict[str, Any]]`.
    if schema.get("type") == "array":
        return _e_objeto_sem_forma(schema.get("items"))
    return False


@pytest.mark.parametrize(
    "caminho,metodo,operacao",
    [pytest.param(c, m, o, id=f"{m.upper()} {c}") for c, m, o in _rotas_com_resposta_json()],
)
def test_resposta_tem_forma_declarada(caminho, metodo, operacao):
    schema = _schema_de_resposta(operacao)
    assert not _e_objeto_sem_forma(schema), (
        f"{metodo.upper()} {caminho} devolve um objeto sem forma no OpenAPI. "
        "Declare um `response_model` Pydantic em `app/schemas/` — senão o "
        "`api.gen.ts` gera `unknown` e o frontend volta a escrever o tipo à mão."
    )


def test_a_varredura_esta_realmente_vendo_as_rotas():
    """Controle: um filtro quebrado tornaria o teste acima um no-op silencioso.

    Sem isto, um `continue` mal colocado deixaria zero rotas parametrizadas e a
    suíte ficaria verde por não checar nada.
    """
    rotas = list(_rotas_com_resposta_json())
    assert len(rotas) > 100, f"esperava a API inteira, vi {len(rotas)} rotas"
    com_json = [r for r in rotas if _schema_de_resposta(r[2]) is not None]
    assert len(com_json) > 100, f"só {len(com_json)} rotas com corpo JSON — filtro quebrado?"
