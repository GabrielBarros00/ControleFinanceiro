"""Acertos entre pessoas na camada PESSOAL — todas as casas de uma vez (ADR 0027).

`DebtService` responde "quem deve a quem NESTA casa". Quem participa de duas casas
não tinha onde perguntar *"com quem eu me acerto, somando tudo?"*: era preciso
entrar em cada workspace e somar de cabeça. Este serviço faz a mesma pergunta do
`/me/overview` — varre `workspaces_do_usuario` e agrega — só que preservando as
LINHAS (com quem, quanto), que é o que falta ao `to_pay`/`to_receive` de lá.

Três regras que não se negociam aqui:

1. **Não se compensa saldo entre workspaces.** Dever 100 na Casa e ter 100 a
   receber na Viagem não é estar quitado: são pessoas e acordos diferentes. Por
   isso a saída é AGRUPADA por workspace e não existe um "líquido" global — só
   `to_pay` e `to_receive` lado a lado.
2. **O recorte é sempre `involved_only`.** Toda chamada ao `DebtService` passa
   `viewer_user_id=user_id`, inclusive para quem é admin: a camada `/me/*` é a
   visão da PESSOA, e dívida entre terceiros continua sendo assunto da tela do
   workspace.
3. **Nada é descartado por falta de cotação.** Cada grupo vem na moeda-base da
   própria casa, sempre. Só os TOTAIS convertem, e o que não converte sai da soma
   e vai para `excluded_workspaces` com o valor na moeda dele — mais estrito que
   o `/me/overview`, que hoje derruba o workspace inteiro de `by_workspace` e
   devolve só um contador.

A ESCRITA não mora aqui. Registrar acerto continua sendo
`POST /workspaces/{ws}/settlements`, que carrega a direção e o teto do ADR 0009, o
`trava_workspace` contra sobrepagamento concorrente e o `publish_event` (que exige
workspace, porque incrementa `Workspace.event_seq`). A tela global só informa de
qual casa é a linha.
"""
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlmodel import Session, func, or_, select

from app.domain.dates import today_local
from app.domain.query_policy import (
    user_report_currency,
    workspace_base_currency,
    workspaces_do_usuario,
)
from app.models.settlement import Settlement
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
    role_level,
)
from app.services.debt_service import DebtService
from app.services.money_conversion import ZERO, converte

# Teto do histórico global. O da casa não pagina porque uma casa tem dezenas de
# acertos; somando todas, a lista cresce com o número de workspaces.
LIMITE_PADRAO = 50
LIMITE_MAXIMO = 200


def _nomes(db: Session, user_ids: Iterable[int]) -> Dict[int, str]:
    """`{user_id: nome}` em UMA consulta.

    O ledger do workspace devolve só `user_id` — a tela da casa cruza com
    `/{ws}/members` para achar o nome. A tela global não pode fazer isso: seriam N
    chamadas, uma por casa, e o membro de outra casa nem apareceria na lista.
    """
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    return {
        uid: nome
        for uid, nome in db.exec(select(User.id, User.name).where(User.id.in_(ids))).all()
    }


def _pessoas(nomes: Dict[int, str], ids: Iterable[int]) -> List[Dict[str, Any]]:
    """Lista no formato que o componente de ledger do frontend já consome
    (`{user_id, user_name}`), para a tela global reusá-lo sem tradução."""
    return [
        {"user_id": uid, "user_name": nomes.get(uid, f"Membro #{uid}")}
        for uid in sorted({uid for uid in ids if uid is not None})
    ]


def _papeis(db: Session, user_id: int) -> Dict[int, str]:
    """`{workspace_id: papel}` do usuário, numa consulta só.

    `WorkspaceRead` não carrega papel, então a tela global não teria como saber
    onde o botão de registrar acerto pode ficar habilitado — e um botão que sempre
    falha com 403 é pior que um botão ausente.
    """
    return {
        ws_id: papel
        for ws_id, papel in db.exec(
            select(WorkspaceMembership.workspace_id, WorkspaceMembership.role).where(
                WorkspaceMembership.user_id == user_id
            )
        ).all()
    }


def _pode_escrever(papel: Optional[str]) -> bool:
    """Mesmo gate de `require_role(WorkspaceRole.member)` em `settlements.py`."""
    if papel is None:
        return False
    return role_level(papel) >= role_level(WorkspaceRole.member)


def _soma(linhas: List[Dict[str, Any]], campo: str, user_id: int) -> Decimal:
    return sum((linha["amount"] for linha in linhas if linha[campo] == user_id), ZERO)


class PersonalDebtService:
    @staticmethod
    def get_personal_debts(
        db: Session, user_id: int, currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """Saldo consolidado a acertar, agrupado por casa.

        Espelho global do `GET /{ws}/debts`. A conversão dos totais é ancorada em
        HOJE (`today_local`), não no primeiro dia do mês: este saldo é cumulativo
        de todos os meses, então não há um mês a que ancorar a taxa.
        """
        destino = currency or user_report_currency(db, user_id)
        hoje = today_local()
        papeis = _papeis(db, user_id)

        brutos: List[Dict[str, Any]] = []
        ids_para_nomear: Set[int] = set()

        for ws in workspaces_do_usuario(db, user_id):
            # `viewer_user_id` recorta na SAÍDA (ver `_only_involving`): o
            # pareamento guloso precisa de todos os saldos para dar o valor certo,
            # e só depois se esconde o que não me envolve.
            linhas = DebtService.get_workspace_debts(db, ws.id, viewer_user_id=user_id)
            if not linhas:
                # Casa quitada não vira seção na tela. Mesma regra do `by_workspace`
                # da Visão global, onde listar todas as casas com zero tornava o
                # estado vazio inalcançável para quem tem mais de um workspace.
                continue
            papel = papeis.get(ws.id)
            for linha in linhas:
                ids_para_nomear.add(linha["debtor_id"])
                ids_para_nomear.add(linha["creditor_id"])
            brutos.append({
                "workspace_id": ws.id,
                "workspace_name": ws.name,
                "base_currency": workspace_base_currency(db, ws.id),
                "role": papel,
                "can_write": _pode_escrever(papel),
                "net_debts": linhas,
                "to_pay": _soma(linhas, "debtor_id", user_id),
                "to_receive": _soma(linhas, "creditor_id", user_id),
            })

        nomes = _nomes(db, ids_para_nomear)
        grupos: List[Dict[str, Any]] = []
        excluidos: List[Dict[str, Any]] = []
        total_pagar = ZERO
        total_receber = ZERO

        for grupo in brutos:
            base = grupo["base_currency"]
            pagar_conv = converte(db, grupo["to_pay"], base, destino, hoje)
            receber_conv = converte(db, grupo["to_receive"], base, destino, hoje)
            # `converte` devolve o próprio valor quando ele é zero, mesmo sem
            # cotação — zero é zero em qualquer moeda. Só o `None` de um valor
            # DIFERENTE de zero tira a casa do total.
            convertido = pagar_conv is not None and receber_conv is not None
            if convertido:
                total_pagar += pagar_conv
                total_receber += receber_conv
            else:
                excluidos.append({
                    "workspace_id": grupo["workspace_id"],
                    "workspace_name": grupo["workspace_name"],
                    "base_currency": base,
                    "to_pay": grupo["to_pay"],
                    "to_receive": grupo["to_receive"],
                })
            grupo["converted"] = convertido
            grupo["net_debts"] = [
                {
                    **linha,
                    "debtor_name": nomes.get(linha["debtor_id"], f"Membro #{linha['debtor_id']}"),
                    "creditor_name": nomes.get(
                        linha["creditor_id"], f"Membro #{linha['creditor_id']}"
                    ),
                }
                for linha in grupo["net_debts"]
            ]
            grupos.append(grupo)

        return {
            "currency": destino,
            # Sem "líquido": compensar as duas pontas entre casas é exatamente o
            # que o ADR 0020 proíbe. Os dois números vivem lado a lado.
            "to_pay": total_pagar,
            "to_receive": total_receber,
            "by_workspace": grupos,
            "excluded_workspaces": excluidos,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def get_personal_monthly(db: Session, user_id: int, month: str) -> Dict[str, Any]:
        """Retrato do mês (por `billing_month`), uma seção por casa.

        Cada grupo carrega o MESMO payload de `GET /{ws}/debts/monthly` — `month`,
        `base_currency`, `members`, `net_debts`, `expenses`, `settled_total`,
        `settlements`, `totals` — acrescido de `people`, com os nomes que a tela da
        casa buscaria em `/{ws}/members`. Assim o componente do frontend é o mesmo
        nos dois lugares, sem uma segunda forma de ler o ledger.

        **Sem parâmetro de moeda, de propósito.** Cada seção é uma casa e vive na
        moeda-base dela; não há total agregado a converter. A primeira versão
        aceitava `?currency=` e devolvia o código no corpo sem converter nada — um
        campo que dizia "estes números estão em USD" sobre valores em BRL, que é
        exatamente o tipo de rótulo errado que o ADR 0006 existe para impedir.
        """
        papeis = _papeis(db, user_id)

        brutos: List[Dict[str, Any]] = []
        ids_para_nomear: Set[int] = set()

        for ws in workspaces_do_usuario(db, user_id):
            ledger = DebtService.get_monthly_ledger(
                db, ws.id, month, viewer_user_id=user_id
            )
            # Mês sem despesa nem acerto NESTA casa não vira seção — a tela ficaria
            # com uma pilha de cards vazios de quem tem várias casas.
            if not ledger["expenses"] and not ledger["net_debts"] and not ledger["settlements"]:
                continue
            ids = _ids_do_ledger(ledger)
            ids_para_nomear |= ids
            papel = papeis.get(ws.id)
            brutos.append({
                "workspace_id": ws.id,
                "workspace_name": ws.name,
                "role": papel,
                "can_write": _pode_escrever(papel),
                "_ids": ids,
                **ledger,
            })

        nomes = _nomes(db, ids_para_nomear)
        grupos = []
        for grupo in brutos:
            ids = grupo.pop("_ids")
            grupo["people"] = _pessoas(nomes, ids)
            grupos.append(grupo)

        return {"month": month, "by_workspace": grupos}

    # ------------------------------------------------------------------
    @staticmethod
    def get_personal_by_month(db: Session, user_id: int) -> Dict[str, Any]:
        """De quais meses vem o saldo, uma seção por casa.

        Espelho global de `GET /{ws}/debts/by-month`. Cada grupo carrega o mesmo
        payload de lá — `balance`, `months`, `older`, `unassigned` — acrescido do
        id e do nome da casa.

        **Sem total agregado, e aqui não é só questão de moeda.** O ADR 0020 já
        proíbe compensar saldo entre casas; somar a origem delas produziria
        exatamente a compensação proibida, com a agravante de parecer uma conta
        fechada. Cada casa reconcilia consigo mesma.

        `viewer_user_id=user_id` sempre, inclusive para quem é admin: a camada
        `/me/*` é a visão da PESSOA (regra 2 do cabeçalho deste módulo).
        """
        grupos: List[Dict[str, Any]] = []
        for ws in workspaces_do_usuario(db, user_id):
            origem = DebtService.get_balance_by_month(
                db, ws.id, user_id, viewer_user_id=user_id
            )
            # Casa sem nenhum mês de origem e sem acerto solto não vira seção —
            # mesma regra de `get_personal_debts`, que também não lista casa
            # quitada.
            if not origem["months"] and not origem["unassigned"] and not origem["balance"]:
                continue
            grupos.append({
                "workspace_id": ws.id,
                "workspace_name": ws.name,
                **origem,
            })
        return {"by_workspace": grupos}

    # ------------------------------------------------------------------
    @staticmethod
    def list_personal_settlements(
        db: Session,
        user_id: int,
        limit: int = LIMITE_PADRAO,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Histórico de acertos da pessoa, em todas as casas.

        O predicado é `sou uma das pontas` — sem join de membership, porque a linha
        É do usuário (mesmo raciocínio de `CashFlowService._acertos`, que já lê
        `Settlement` cross-workspace para o caixa). O acerto entre TERCEIROS de uma
        casa em que sou admin não aparece aqui: quem mostra aquilo é a tela do
        workspace.
        """
        alvo = or_(
            Settlement.from_user_id == user_id,
            Settlement.to_user_id == user_id,
        )
        base = (
            select(Settlement)
            .where(alvo)
            .where(Settlement.deleted_at.is_(None))
        )
        # `total` ANTES da paginação: sem ele a tela mostra as 50 primeiras linhas
        # como se fossem todas, e truncar histórico financeiro em silêncio é o
        # mesmo defeito do `or ZERO` — um número plausível e errado.
        total = db.exec(
            select(func.count()).select_from(Settlement)
            .where(alvo)
            .where(Settlement.deleted_at.is_(None))
        ).one()
        linhas = db.exec(
            base.order_by(Settlement.settled_at.desc(), Settlement.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()

        # Moeda por casa, memoizada: `Settlement` não tem coluna de moeda — o valor
        # é implicitamente da moeda-base do workspace, e `base_currency_service`
        # REESCREVE o montante quando essa base muda.
        #
        # O nome vem de uma busca por ID, NÃO da lista de casas de que sou membro
        # hoje: sair de um workspace é permitido depois de quitar o saldo
        # (`_ensure_no_open_balance`), e a versão anterior rotulava todo o
        # histórico daquela casa como "Casa removida" enquanto ela seguia viva.
        # Casa com `deleted_at` também mantém o nome — é história, e história não
        # se reescreve (ADR 0023).
        moedas: Dict[int, str] = {}
        contrapartes = set()
        ws_ids = {s.workspace_id for s in linhas}
        nomes_ws: Dict[int, str] = {
            ws_id: nome
            for ws_id, nome in db.exec(
                select(Workspace.id, Workspace.name).where(Workspace.id.in_(ws_ids))
            ).all()
        } if ws_ids else {}
        for s in linhas:
            if s.workspace_id not in moedas:
                moedas[s.workspace_id] = workspace_base_currency(db, s.workspace_id)
            contrapartes.add(s.to_user_id if s.from_user_id == user_id else s.from_user_id)

        nomes = _nomes(db, contrapartes)
        itens = [
            {
                "id": s.id,
                "workspace_id": s.workspace_id,
                "workspace_name": nomes_ws.get(s.workspace_id, "Casa removida"),
                "currency": moedas.get(s.workspace_id, "BRL"),
                "from_user_id": s.from_user_id,
                "to_user_id": s.to_user_id,
                "counterparty_id": (
                    s.to_user_id if s.from_user_id == user_id else s.from_user_id
                ),
                "counterparty_name": nomes.get(
                    s.to_user_id if s.from_user_id == user_id else s.from_user_id, "—"
                ),
                # Direção do ponto de vista de quem pediu: a tela da casa mostra
                # "Pagou/Recebeu" por nome, mas na global o eixo é sempre eu.
                "direction": "sent" if s.from_user_id == user_id else "received",
                "amount": s.amount,
                "note": s.note,
                "billing_month": s.billing_month,
                "settled_at": s.settled_at,
                "created_by_user_id": s.created_by_user_id,
            }
            for s in linhas
        ]
        return {"items": itens, "total": total, "limit": limit, "offset": offset}


def _ids_do_ledger(ledger: Dict[str, Any]) -> Set[int]:
    """Todo `user_id` citado num ledger mensal, para nomear em lote."""
    ids: Set[int] = set()
    for m in ledger["members"]:
        ids.add(m["user_id"])
    for d in ledger["net_debts"]:
        ids.add(d["debtor_id"])
        ids.add(d["creditor_id"])
    for s in ledger["settlements"]:
        ids.add(s["from_user_id"])
        ids.add(s["to_user_id"])
    for e in ledger["expenses"]:
        for p in e["payers"]:
            ids.add(p["user_id"])
        for sp in e["splits"]:
            ids.add(sp["user_id"])
    return ids
