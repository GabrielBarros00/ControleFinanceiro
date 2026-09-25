"""O `_meta` do componente para cada ESCRITA, montado num lugar só.

Toda escrita desenha o resultado (ADR 0035 §11): o lançamento criado com Editar e
Desfazer, a diferença do que mudou, o que foi excluído com Desfazer. O que muda de
tool para tool é pouco — qual vista, qual modo e qual tool desfaz — e mora aqui,
a partir da saída estruturada que a tool já devolve. Os handlers não repetem nada.

O `undo` é só um convite: o componente chama a tool com os argumentos daqui, e o
servidor aplica TODAS as regras de novo na hora do clique (permissão, versão,
trava de paga).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.mcp import ui_meta
from app.mcp.registry import ToolCall, ToolOutput
from app.models.transaction import Transaction

Montador = Callable[[ToolCall, dict], dict]

#: Campos de um lançamento que o "desfazer a edição" sabe voltar sozinho. Mudou
#: divisão, itens, cartão ou moeda? O desfazer não é oferecido: voltar isso é uma
#: edição completa, e o componente oferece "Editar" em vez de adivinhar.
_DESFAZ_EDICAO = {"title", "description", "date", "amount", "category", "tags", "settled"}


def _tx(call: ToolCall, dados: dict, chave: str = "transaction") -> Optional[Transaction]:
    tx = (dados.get(chave) or {}).get("id")
    return call.session.get(Transaction, tx) if tx else None


def _criado(call: ToolCall, dados: dict) -> dict:
    tx = _tx(call, dados)
    if tx is None:
        return {"view": "transaction", "mode": "created"}
    escopo = "purchase" if tx.installment_group_id else "installment"
    return ui_meta.transaction_meta(
        call, tx, mode="created", app_url=dados["transaction"].get("app_url", ""),
        undo_action=ui_meta.undo("transactions_delete", {"transaction_id": tx.id, "scope": escopo}),
    )


def _desfaz_edicao(antes: dict, depois: dict, mudou: list[str]) -> Optional[dict]:
    efetivas = set(mudou)
    if "amount" in efetivas and len(antes.get("split") or []) <= 1:
        # Numa despesa de uma pessoa só, pagador e divisão acompanham o valor: são
        # consequência, e voltar o valor os volta também.
        efetivas -= {"payers", "split"}
    if not efetivas or not efetivas <= _DESFAZ_EDICAO:
        return None
    if "amount" in efetivas and (antes.get("items") or len(antes.get("split") or []) > 1 or antes.get("foreign")):
        return None
    mudou = sorted(efetivas)
    args: dict[str, Any] = {"transaction_id": depois["id"], "expected_version": depois.get("version")}
    for campo in mudou:
        if campo == "category":
            if antes.get("category"):
                args["category_id"] = antes["category"]["id"]
            else:
                args["remove_category"] = True
        elif campo == "description":
            args["description"] = antes.get("description") or ""
        else:
            args[campo] = antes.get(campo)
    return ui_meta.undo("transactions_update", args)


def _editado(call: ToolCall, dados: dict) -> dict:
    tx = _tx(call, dados)
    if tx is None:
        return {"view": "transaction", "mode": "updated"}
    return ui_meta.transaction_meta(
        call, tx, mode="updated", app_url=dados["transaction"].get("app_url", ""),
        undo_action=_desfaz_edicao(dados.get("previous") or {}, dados["transaction"], dados.get("changed") or []),
    )


def _excluido(call: ToolCall, dados: dict) -> dict:
    ids = [d["id"] for d in dados.get("deleted") or []]
    meta: dict[str, Any] = {"view": "transaction", "mode": "deleted"}
    if ids:
        meta["undo"] = ui_meta.undo("transactions_restore", {"transaction_id": ids[0]})
        meta["undo_each"] = [{"transaction_id": i} for i in ids]
    return meta


def _restaurado(call: ToolCall, dados: dict) -> dict:
    tx = _tx(call, dados)
    if tx is None:
        return {"view": "transaction", "mode": "restored"}
    return ui_meta.transaction_meta(
        call, tx, mode="restored", app_url=dados["transaction"].get("app_url", ""),
        undo_action=ui_meta.undo("transactions_delete", {"transaction_id": tx.id}),
    )


def _renda(modo: str, desfaz: Optional[str] = None, chave: str = "income") -> Montador:
    def montar(call: ToolCall, dados: dict) -> dict:
        meta: dict[str, Any] = {"view": "income", "mode": modo}
        renda = dados.get(chave) or {}
        if desfaz and renda.get("id"):
            meta["undo"] = ui_meta.undo(desfaz, {"income_id": renda["id"]})
        return meta
    return montar


def _recorrencia(modo: str, chave: str = "recurring") -> Montador:
    def montar(call: ToolCall, dados: dict) -> dict:
        meta: dict[str, Any] = {"view": "recurring", "mode": modo}
        rec = dados.get(chave) or {}
        if modo == "created" and rec.get("id"):
            meta["undo"] = ui_meta.undo("recurring_delete", {"recurring_id": rec["id"], "kind": rec.get("kind", "expense")}, "Excluir")
        return meta
    return montar


def _recibo(desfaz: Optional[Callable[[dict], Optional[dict]]] = None) -> Montador:
    def montar(call: ToolCall, dados: dict) -> dict:
        meta: dict[str, Any] = {"view": "receipt"}
        acao = desfaz(dados) if desfaz else None
        if acao:
            meta["undo"] = acao
        return meta
    return montar


def _desfaz_pagamento(d: dict) -> Optional[dict]:
    if d.get("replayed") or not d.get("card"):
        return None
    return ui_meta.undo("statements_reopen", {"card_id": d["card"]["id"], "month": d["month"]}, "Estornar")


def _desfaz_parcela(d: dict) -> Optional[dict]:
    if d.get("action") != "pay":
        return None
    return ui_meta.undo("financings_installment", {
        "action": "unpay", "financing_id": d["financing"]["id"], "installment": d["installment"],
    })


def _massa(d: dict) -> dict:
    meta: dict[str, Any] = {"view": "bulk_result"}
    if d.get("action") == "delete" and d.get("transaction_ids"):
        meta["undo_each"] = [{"transaction_id": i} for i in d["transaction_ids"]]
        meta["undo"] = ui_meta.undo("transactions_restore", {"transaction_id": d["transaction_ids"][0]}, "Restaurar todos")
    return meta


MONTADORES: dict[str, Montador] = {
    "transactions_create": _criado,
    "transactions_update": _editado,
    "transactions_delete": _excluido,
    "transactions_restore": _restaurado,
    "income_create": _renda("created", "income_delete"),
    "income_update": _renda("updated"),
    "income_delete": _renda("deleted", "income_restore", chave="deleted"),
    "income_restore": _renda("restored", "income_delete"),
    "recurring_create": _recorrencia("created"),
    "recurring_update": _recorrencia("updated"),
    "recurring_delete": _recorrencia("deleted", chave="deleted"),
    "budgets_set": _recibo(),
    "categories_create": _recibo(lambda d: ui_meta.undo(
        "categories_update", {"space_id": d["space"]["id"], "id": d["id"], "kind": d.get("kind", "category"), "delete": True},
    )),
    "categories_update": _recibo(),
    "statements_pay": _recibo(_desfaz_pagamento),
    "statements_reopen": _recibo(),
    "transfers_create": _recibo(lambda d: None if d.get("replayed") else ui_meta.undo("transfers_delete", {"transfer_id": d["id"]})),
    "transfers_delete": _recibo(),
    "accounts_adjust_balance": _recibo(),
    "settlements_create": _recibo(lambda d: None if d.get("replayed") else ui_meta.undo("settlements_delete", {"settlement_id": d["id"]})),
    "settlements_delete": _recibo(),
    "financings_installment": _recibo(_desfaz_parcela),
    "attachments_add": _recibo(lambda d: ui_meta.undo("attachments_delete", {"attachment_id": d["attachment"]["id"]}, "Remover")),
    "attachments_delete": _recibo(),
    "transactions_bulk_delete": lambda call, d: _massa(d),
    "transactions_bulk_categorize": lambda call, d: _massa(d),
    "transactions_bulk_update": lambda call, d: _massa(d),
    "imports_commit": lambda call, d: {
        "view": "imports", "mode": "created",
        **({"undo": ui_meta.undo(
            "transactions_bulk_preview", {"action": "delete", "filters": {"import_batch_id": d["batch_id"]}},
            "Desfazer importação",
        )} if d.get("batch_id") and d.get("imported") else {}),
    },
}


def build(call: ToolCall, saida: ToolOutput, dados: dict) -> Optional[dict]:
    montador = MONTADORES.get(call.spec.name)
    if montador is None:
        return saida.widget
    meta = montador(call, dados)
    if saida.widget:
        meta = {**saida.widget, **meta}
    return meta
