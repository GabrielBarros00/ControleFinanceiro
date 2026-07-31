from decimal import Decimal
from datetime import date
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select, func
from app.domain.access_policy import involvement_filter
from app.domain.dates import add_months, month_key
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.transaction import (
    SplitMode,
    Transaction,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
)
from app.models.category import Category
from app.models.settlement import Settlement
from app.services.transaction_service import _allocate_proportional, _cents


class ReportService:
    @staticmethod
    def get_summary(
        db: Session,
        workspace_id: int,
        target_month: date,
        user_id: Optional[int] = None,
        full_access: bool = True,
    ) -> Dict[str, Any]:
        """Resumo do mês DESTE WORKSPACE: o gasto da casa + o recorte do usuário.

        Só gasto. Renda e resultado saíram daqui na Onda 5 (ADR 0021), e essa é a
        correção do número mais enganoso que o app tinha. `my_net` era
        `my_income − my_expenses` com `my_income` GLOBAL (a renda segue a pessoa,
        por decisão do dono) e `my_expenses` recortado NESTE workspace. Quem
        participava de dois workspaces via o mesmo salário combinado com um
        subconjunto diferente das despesas em cada um — e as duas "sobras" eram
        maiores que a real, cada uma ignorando o que foi gasto na outra casa.

        Renda e resultado passam a existir num lugar só, `/me/overview`, onde o
        consumo somado de TODOS os workspaces é o denominador certo.

        O que o Painel precisa e agora recebe: quanto a casa gastou, quanto disso é
        meu (`my_expenses`, soma dos meus splits), quanto saiu do meu bolso
        (`paid_by_me`, soma do que paguei) e a diferença entre os dois, que é o
        acerto — `to_receive`/`to_pay`.

        `full_access=False` (ADR 0018) suprime os números da casa, devolvendo
        `None` — não `0`. Zero seria uma mentira aritmética: o membro somaria
        "a casa gastou 0" com "eu gastei 300" e concluiria coisa errada. `None`
        diz "você não tem acesso a isto", e a tela sabe não desenhar o comparativo.
        """
        base_currency = workspace_base_currency(db, workspace_id)
        # Só billing_month: a janela de datas (`start`/`end`) existia para recortar
        # a RENDA por `received_at`, e renda saiu daqui (ADR 0021). Despesa sempre
        # recortou por billing_month — a MESMA definição de mês que Lançamentos e
        # Dívidas usam. Ver domain.dates.month_key.
        mes = month_key(target_month)

        # Total de despesas — política única de status/moeda (ADR 0003/0006).
        # Tudo em Decimal: float() perdia centavos (REL-001).
        # Sem acesso completo nem chega a consultar: o número seria descartado no
        # return, e consultar de graça é o tipo de desperdício que passa despercebido.
        expenses = Decimal("0.00")
        if full_access:
            expenses = db.exec(
                select(func.sum(Transaction.total_amount))
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month == mes)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
            ).one() or Decimal("0.00")

        # "Minha parte" × "o que eu paguei": dois números diferentes, e a diferença
        # entre eles é o acerto. O app só sabia falar do primeiro.
        # Sem user_id, os campos do recorte ficam zerados (visão só da casa).
        my_expenses = Decimal("0.00")
        paid_by_me = Decimal("0.00")
        settled_by_me = Decimal("0.00")
        if user_id is not None:
            my_expenses = db.exec(
                select(func.sum(TransactionSplit.computed_amount))
                .join(Transaction)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month == mes)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionSplit.user_id == user_id)
            ).one() or Decimal("0.00")

            # Saída de caixa NESTE workspace: soma do que o usuário pagou, não do
            # que consumiu. É o número que faltava no Painel para a frase "consumi
            # 1.150 mas paguei 1.300, tenho 150 a receber" fechar na tela.
            paid_by_me = db.exec(
                select(func.sum(TransactionPayer.amount))
                .join(Transaction)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month == mes)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionPayer.user_id == user_id)
            ).one() or Decimal("0.00")

            # ACERTOS DO MÊS. Sem eles `my_balance` era `paid_by_me − my_expenses`
            # e nunca zerava: Alice adiantava 100 numa despesa de 50 que era dela,
            # Bob acertava os 50, e o Painel seguia anunciando "R$ 50 a receber"
            # para sempre — enquanto `/me/overview`, que usa o ledger do
            # DebtService, já mostrava zero. Duas telas do mesmo app discordando
            # sobre a mesma dívida.
            #
            # Mesma convenção do ledger mensal (`DebtService.get_monthly_ledger`):
            # quem PAGOU o acerto sobe (a dívida dele diminui), quem RECEBEU desce.
            # E o recorte é `billing_month`, o mesmo de "Dívidas do mês" — que é a
            # tela onde o acerto é registrado. Acerto global (billing_month NULL)
            # não entra aqui: ele pertence ao balanço geral, em `/debts` e
            # `/me/overview`, e este número é o do MÊS.
            enviados = db.exec(
                select(func.sum(Settlement.amount))
                .where(Settlement.workspace_id == workspace_id)
                .where(Settlement.billing_month == mes)
                .where(Settlement.deleted_at.is_(None))
                .where(Settlement.from_user_id == user_id)
            ).one() or Decimal("0.00")
            recebidos = db.exec(
                select(func.sum(Settlement.amount))
                .where(Settlement.workspace_id == workspace_id)
                .where(Settlement.billing_month == mes)
                .where(Settlement.deleted_at.is_(None))
                .where(Settlement.to_user_id == user_id)
            ).one() or Decimal("0.00")
            settled_by_me = enviados - recebidos

        # Distribuição por categoria: soma dos itens COM categoria. Itens sem
        # categoria E transações sem item nenhum entram em "Sem categoria" — que
        # é exatamente (total − categorizado), então nada some do gráfico (REL-001).
        categorized = []
        if full_access:
            categorized = db.exec(
                select(TransactionItem.category_id, func.sum(TransactionItem.amount))
                .join(Transaction)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month == mes)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionItem.category_id.is_not(None))
                .group_by(TransactionItem.category_id)
            ).all()

        category_names = {
            c.id: c.name
            for c in db.exec(select(Category).where(Category.workspace_id == workspace_id)).all()
        }
        # O id acompanha o nome: o orçamento casa gasto × meta por category_id
        # (BUD-001) — casar por nome quebrava calado ao renomear a categoria.
        category_data = [
            {
                "category_id": cid,
                "name": category_names.get(cid, "Categoria"),
                "value": amount or Decimal("0.00"),
            }
            for cid, amount in categorized
        ]
        categorized_total = sum((amount or Decimal("0.00") for _, amount in categorized), Decimal("0.00"))
        uncategorized = expenses - categorized_total
        if uncategorized > 0:
            category_data.append({"category_id": None, "name": "Sem categoria", "value": uncategorized})
        elif uncategorized < 0:
            # Itens somam MAIS que o total: acontece com ajuste negativo
            # (desconto/cashback), em que total = itens + ajustes com ajustes < 0.
            # Antes o valor negativo era só descartado e a pizza passava a somar
            # mais que o `total_expenses` exibido ao lado dela. Rateamos a
            # diferença entre as categorias, em centavos exatos, para o gráfico
            # fechar com o total — que é o número que o usuário confere.
            weights = {
                i: _cents(item["value"])
                for i, item in enumerate(category_data)
                if item["value"] > 0
            }
            if weights and sum(weights.values()) > 0:
                alloc = _allocate_proportional(_cents(uncategorized), weights)
                for i, delta in alloc.items():
                    category_data[i]["value"] += Decimal(delta) / Decimal("100")

        # Distribuição por categoria da MINHA parte — o par de `categories` para
        # a meta pessoal. Sem isto, a meta por categoria do usuário só poderia ser
        # comparada com o gasto da casa, que é exatamente o erro que o orçamento
        # com escopo veio corrigir.
        my_category_data: List[Dict[str, Any]] = []
        if user_id is not None:
            my_categorized = ReportService._my_categorized(
                db, workspace_id, mes, base_currency, user_id
            )
            my_category_data = [
                {
                    "category_id": cid,
                    "name": category_names.get(cid, "Categoria"),
                    "value": valor,
                }
                for cid, valor in sorted(my_categorized.items(), key=lambda kv: kv[0])
            ]
            my_categorized_total = sum(
                (v for v in my_categorized.values()), Decimal("0.00")
            )
            my_uncategorized = my_expenses - my_categorized_total
            if my_uncategorized > 0:
                my_category_data.append(
                    {"category_id": None, "name": "Sem categoria", "value": my_uncategorized}
                )

        # Lançamentos em moeda diferente da base ficam FORA dos totais (ADR 0006).
        # Expor a contagem deixa o usuário saber que "sumiram" de propósito (E5/F-04).
        # A contagem também é escopada: senão ela virava um oráculo — "existem 3
        # lançamentos que você não pode ver" é informação sobre dado alheio.
        excluded_stmt = (
            select(func.count(Transaction.id))
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == mes)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency != base_currency)
        )
        if not full_access and user_id is not None:
            excluded_stmt = excluded_stmt.where(involvement_filter(user_id))
        excluded_foreign_count = db.exec(excluded_stmt).one() or 0

        return {
            # Números da CASA: None sem acesso completo (ADR 0018)
            "total_expenses": expenses if full_access else None,
            "categories": category_data if full_access else None,
            # Recorte do usuário logado (a parte dele, não o valor cheio da casa).
            # Estes NUNCA são suprimidos: são os dados do próprio usuário.
            "my_expenses": my_expenses,
            "paid_by_me": paid_by_me,
            # Positivo = adiantei e tenho a receber; negativo = devo — DEPOIS dos
            # acertos já registrados neste mês. Recortado num workspace só, e por
            # isso NÃO compensado com outros (dever na casa e receber na viagem
            # envolve pessoas e acordos diferentes).
            "my_balance": paid_by_me - my_expenses + settled_by_me,
            # Mesma composição, recortada na parte do usuário (meta pessoal)
            "my_categories": my_category_data,
            "base_currency": base_currency,
            "excluded_foreign_count": excluded_foreign_count,
        }

    @staticmethod
    def _my_categorized(
        db: Session,
        workspace_id: int,
        mes: str,
        base_currency: str,
        user_id: int,
    ) -> Dict[int, Decimal]:
        """Quanto do gasto de `user_id` no mês caiu em cada categoria.

        Duas fontes, porque a "minha parte de um item" só é explícita num modo:

        - `split_mode='item'`: a share do usuário no item JÁ é o valor dele
          naquela linha (`TransactionItemShare.computed_amount`). Exato.
        - `split_mode='transaction'`: a divisão é da despesa inteira, não por
          linha. Rateamos a parte do usuário (`TransactionSplit.computed_amount`)
          proporcionalmente ao valor dos itens, em centavos exatos
          (`_allocate_proportional`, ADR 0001) — nenhum centavo se perde nem se
          inventa. Na prática também é exato: nesse modo existe no máximo o
          item-categoria único, cujo valor É o total.
        """
        por_categoria: Dict[int, Decimal] = {}

        def _somar(category_id, valor: Decimal) -> None:
            if category_id is None or valor == 0:
                return
            por_categoria[category_id] = por_categoria.get(category_id, Decimal("0.00")) + valor

        base = (
            select(Transaction.id, Transaction.split_mode)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == mes)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
        )
        modo_por_tx = dict(db.exec(base).all())
        if not modo_por_tx:
            return por_categoria

        tx_ids = list(modo_por_tx)
        item_mode_ids = [
            tid for tid, modo in modo_por_tx.items() if modo == SplitMode.item
        ]

        # (1) modo item: a share do usuário por linha, direto
        if item_mode_ids:
            linhas = db.exec(
                select(TransactionItem.category_id, TransactionItemShare.computed_amount)
                .join(TransactionItemShare, TransactionItemShare.item_id == TransactionItem.id)
                .where(TransactionItem.transaction_id.in_(item_mode_ids))
                .where(TransactionItemShare.user_id == user_id)
            ).all()
            for category_id, valor in linhas:
                _somar(category_id, valor or Decimal("0.00"))

        # (2) modo transaction: rateia a parte do usuário pelos itens da despesa
        outros_ids = [tid for tid in tx_ids if tid not in set(item_mode_ids)]
        if not outros_ids:
            return por_categoria

        minha_parte = dict(db.exec(
            select(TransactionSplit.transaction_id, TransactionSplit.computed_amount)
            .where(TransactionSplit.transaction_id.in_(outros_ids))
            .where(TransactionSplit.user_id == user_id)
        ).all())
        if not minha_parte:
            return por_categoria

        itens_por_tx: Dict[int, List] = {}
        for item in db.exec(
            select(TransactionItem)
            .where(TransactionItem.transaction_id.in_(list(minha_parte)))
            .order_by(TransactionItem.position, TransactionItem.id)
        ).all():
            itens_por_tx.setdefault(item.transaction_id, []).append(item)

        for tx_id, parte in minha_parte.items():
            itens = itens_por_tx.get(tx_id)
            if not itens:
                continue  # sem item = sem categoria; cai em "Sem categoria"
            pesos = {i: _cents(item.amount) for i, item in enumerate(itens)}
            if sum(pesos.values()) <= 0:
                pesos = {i: 1 for i in range(len(itens))}
            alocado = _allocate_proportional(_cents(parte), pesos)
            for i, item in enumerate(itens):
                _somar(item.category_id, Decimal(alocado[i]) / Decimal("100"))

        return por_categoria

    @staticmethod
    def get_last_6_months(
        db: Session,
        workspace_id: int,
        user_id: Optional[int] = None,
        ref_month: Optional[date] = None,
        full_access: bool = True,
    ) -> List[Dict[str, Any]]:
        """6 meses terminando em `ref_month` (padrão: mês corrente).

        Uma query por MÉTRICA agrupando os 6 meses de uma vez, em vez de um
        get_summary completo por mês (que fazia ~5 queries × 6 = 30 idas ao
        banco só para desenhar as barras).

        `full_access=False` (ADR 0018): as barras da casa saem `None` e sobra a
        série pessoal. Suprimir só o resumo e deixar o histórico passar seria pior
        que não suprimir nada — daria o total da casa mês a mês na mesma resposta.
        """
        base_currency = workspace_base_currency(db, workspace_id)
        first_of_month = (ref_month or date.today()).replace(day=1)
        months = [add_months(first_of_month, -i) for i in range(5, -1, -1)]
        month_keys = [month_key(d) for d in months]

        # Despesa agrupa por billing_month (mesma definição de mês do resto do
        # app); o SQL só filtra os 6 meses e a soma sai em Python — assim não
        # dependemos de strftime (SQLite) nem to_char (Postgres).
        #
        # Sem série de RENDA: ela é pessoal (ADR 0021) e o histórico do workspace
        # é de gasto. A barra de receita ao lado da de despesa era a versão
        # gráfica do mesmo erro do `my_net`.
        expenses_by_month: Dict[str, Decimal] = {}
        if full_access:
            expense_rows = db.exec(
                select(Transaction.billing_month, Transaction.total_amount)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month.in_(month_keys))
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
            ).all()
            for key, amount in expense_rows:
                expenses_by_month[key] = expenses_by_month.get(key, Decimal("0.00")) + amount

        my_by_month: Dict[str, Decimal] = {}
        if user_id is not None:
            my_rows = db.exec(
                select(Transaction.billing_month, TransactionSplit.computed_amount)
                .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.billing_month.in_(month_keys))
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
                .where(TransactionSplit.user_id == user_id)
            ).all()
            for key, amount in my_rows:
                my_by_month[key] = my_by_month.get(key, Decimal("0.00")) + amount

        # `month` (YYYY-MM) é o rótulo AUTORITATIVO: `name` vinha de
        # `strftime("%b")`, que usa o locale do processo — no container (locale C)
        # o eixo dos gráficos de Relatórios falava inglês ("Jan/Feb/May") num app
        # inteiro em PT-BR. O nome fica por compatibilidade; quem desenha formata
        # a partir de `month` com Intl.
        return [
            {
                "month": key,
                "name": d.strftime("%b"),
                # Barras da casa: None sem acesso completo (ADR 0018)
                "expenses": expenses_by_month.get(key, Decimal("0.00")) if full_access else None,
                "my_expenses": my_by_month.get(key, Decimal("0.00")),
            }
            for d, key in zip(months, month_keys)
        ]
