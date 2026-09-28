"""O histórico de UM lançamento, lido da trilha de auditoria.

Uma regra só para os dois leitores: a tool `transactions_history` do MCP e a rota
`GET .../transactions/{id}/history` da tela. Nasceu dentro da tool, e a tela não
tinha como mostrar "quem mudou isto, e o que era antes" — o agente de IA sabia
responder, o app não.

A trilha guarda a foto da linha a cada gravação (`AuditLog.new_values`); o
histórico é a diferença entre fotos seguidas, só nos campos que dizem algo a quem
lê (o resto é interno: ids de fatura, carimbos). Divisão, itens e tags não entram
na foto, então a mudança só deles aparece como `detail_only`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import List, Optional

from sqlmodel import Session, select

from app.domain.dates import local_day, to_local
from app.models.audit import AuditLog
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction
from app.models.user import User

#: Campo da trilha → nome na saída. Só estes aparecem.
CAMPOS = {
    "title": "title", "description": "description", "total_amount": "amount", "currency": "currency",
    "transaction_date": "date", "billing_month": "billing_month", "status": "status",
    "settled_at": "settled_on", "payment_method": "payment_method", "credit_card_id": "card",
    "statement_shift": "statement_shift", "split_mode": "split_mode",
}

#: Campos que o app recalcula sozinho ao gravar (não são edição de ninguém).
DERIVADOS = frozenset({"billing_month", "statement_shift"})


@dataclass
class Mudanca:
    campo: str
    antes: Optional[str] = None
    depois: Optional[str] = None


@dataclass
class Registro:
    #: Quando, no fuso da conta (AAAA-MM-DD HH:MM).
    quando: str
    #: created | updated | deleted | restored | cancelled | paid | reopened
    acao: str
    por_id: Optional[int]
    por_nome: Optional[str]
    via_ia: bool
    #: O app de IA que fez a mudança, quando via IA.
    cliente: Optional[str]
    mudancas: List[Mudanca] = field(default_factory=list)
    #: Mudou só divisão, itens ou tags (a trilha não guarda o antes/depois deles).
    so_detalhe: bool = False


def _valor(campo: str, valor, cartoes: dict[int, str]) -> Optional[str]:
    if valor is None:
        return None
    if campo in ("transaction_date", "settled_at"):
        try:
            return local_day(dt.datetime.fromisoformat(str(valor))).isoformat()
        except ValueError:
            return str(valor)
    if campo == "credit_card_id":
        return cartoes.get(int(valor), f"cartão {valor}")
    return str(valor)


def historico(session: Session, tx: Transaction) -> List[Registro]:
    """Os registros do lançamento, mais recentes primeiro.

    Não confere visibilidade: quem chama já resolveu `tx` pelo gate dele
    (`get_visible_transaction` na rota, `visible_transaction` na tool).
    """
    linhas = session.exec(
        select(AuditLog)
        .where(
            AuditLog.resource_type == "Transaction",
            AuditLog.resource_id == tx.id,
            AuditLog.workspace_id == tx.workspace_id,
        )
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()
    ids_de_pessoa = {r.user_id for r in linhas if r.user_id}
    pessoas = dict(session.exec(select(User.id, User.name).where(User.id.in_(ids_de_pessoa))).all()) if ids_de_pessoa else {}
    ids_de_cartao = {int(c) for r in linhas if (c := (r.new_values or {}).get("credit_card_id"))}
    cartoes = dict(session.exec(
        select(CreditCard.id, CreditCard.name).where(CreditCard.id.in_(ids_de_cartao))
    ).all()) if ids_de_cartao else {}

    registros: list[Registro] = []
    anterior: dict = {}
    for r in linhas:
        atual = r.new_values or {}
        origem = r.origin or ""
        via_ia = origem.startswith("mcp:")
        acao = getattr(r.action, "value", r.action)
        mudancas: list[Mudanca] = []
        if acao == "create" or not anterior:
            acao_saida = "created"
        else:
            for campo, rotulo in CAMPOS.items():
                antes, depois = anterior.get(campo), atual.get(campo)
                if antes != depois:
                    mudancas.append(Mudanca(rotulo, _valor(campo, antes, cartoes), _valor(campo, depois, cartoes)))
            if anterior.get("deleted_at") is None and atual.get("deleted_at"):
                acao_saida = "deleted"
            elif anterior.get("deleted_at") and not atual.get("deleted_at"):
                acao_saida = "restored"
            elif anterior.get("status") != atual.get("status") and atual.get("status") in ("cancelled", "paid"):
                acao_saida = atual["status"]
            elif anterior.get("status") == "paid" and atual.get("status") == "confirmed":
                acao_saida = "reopened"
            else:
                acao_saida = "updated"
        if atual:
            anterior = atual
        registro = Registro(
            quando=to_local(r.created_at).strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            acao=acao_saida,
            por_id=r.user_id,
            por_nome=pessoas.get(r.user_id, "?") if r.user_id else None,
            via_ia=via_ia,
            cliente=origem[4:] if via_ia else None,
            mudancas=mudancas,
            so_detalhe=acao_saida == "updated" and not mudancas,
        )
        # A mesma gravação costuma gerar duas linhas seguidas (a fatura é
        # reancorada no mesmo flush): junta com a anterior se foi a mesma pessoa,
        # pelo mesmo caminho, no mesmo minuto. Na criação, só junta o que é
        # derivado (fatura, competência): uma edição de verdade logo depois de
        # criar aparecia como parte do "Criado", com o antes → depois dentro dele.
        ultimo = registros[-1] if registros else None
        if (
            ultimo is not None and ultimo.quando == registro.quando and ultimo.via_ia == registro.via_ia
            and ultimo.por_id == registro.por_id
            and registro.acao == "updated" and ultimo.acao != "deleted"
            and (ultimo.acao != "created" or all(m.campo in DERIVADOS for m in registro.mudancas))
        ):
            vistos = {m.campo for m in ultimo.mudancas}
            ultimo.mudancas.extend(m for m in registro.mudancas if m.campo not in vistos)
            ultimo.so_detalhe = ultimo.so_detalhe and registro.so_detalhe
            continue
        registros.append(registro)
    registros.reverse()
    return registros
