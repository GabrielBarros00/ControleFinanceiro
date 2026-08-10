"""Converte a perna de FATURA das compras antigas (ADR 0024), com taxa histórica.

A migração `d8f1a37c025b` preencheu `statement_amount`/`statement_currency` por
IDENTIDADE — copiou o valor contábil como está. Isso acerta todo lançamento cujo
cartão está na mesma moeda do workspace, que é a esmagadora maioria, e deixa de
fora exatamente as linhas do defeito: compras num cartão de moeda diferente, que
continuam sem entrar no total da fatura (a API as anuncia em
`excluded_from_total_count`).

A migração não as converte de propósito. Reconverter histórico dentro de um
`alembic upgrade` significaria ir buscar cotação — num passo que não pode falhar
pela metade e roda sem supervisão — e gravar um número que banco nenhum cobrou.
Este script é a versão supervisionada disso: opt-in, com dry-run, e falha alto
quando falta cotação em vez de inventar uma.

**Duas passadas, e a segunda não é opcional.** Converter só a transação conserta
a fatura ABERTA, cujo total é somado na leitura. A fechada/paga usa o
`total_amount` CONGELADO no fechamento (`CreditCardService.effective_total`):
sem regravá-lo, o backfill apagaria o aviso de linha incompatível e deixaria o
total errado — pior que antes, porque agora invisível. A segunda passada
recalcula o congelado das faturas não abertas que tiveram linha convertida.

O script NUNCA cria nem apaga pagamento — cobrar a diferença é decisão humana, e
sai numa seção própria da saída, em destaque. O que ele faz é **devolver a fatura
sub-paga para `closed`**, que é o estado normal de pagamento parcial. Deixá-la
`paid` com saldo devedor era um estado que o resto do sistema não sabe ler: o
limite do cartão ignora fatura `paid` (`card_overview`), a tela só mostra "Saldo
restante" fora desse status, e `pay_statement` EXIGE `closed` — a única saída
oferecida era reabrir, que estorna todos os pagamentos. Ou a dívida sumia da
tela, ou o dinheiro já pago sumia do histórico. Em `closed` com os pagamentos
intactos, "Pagar saldo restante" volta a funcionar e o limite volta a contar.

Uso (da raiz do backend, com o .env carregado):
    python scripts/backfill_statement_amounts.py            # dry-run
    python scripts/backfill_statement_amounts.py --apply    # grava

Sem cotação para a data de alguma compra, ele NÃO grava nada e lista o que
falta — rode `scripts/backfill_rates.py` para o período e tente de novo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.engine import engine  # noqa: E402
from app.domain.dates import local_day  # noqa: E402
from app.models.credit_card import CardStatement, CreditCard, StatementStatus  # noqa: E402
from app.models.transaction import Transaction  # noqa: E402
from app.services.base_conversion import compute_statement_conversion  # noqa: E402
from app.services.credit_card_service import CreditCardService  # noqa: E402


def main(apply: bool) -> int:
    with Session(engine) as session:
        return backfill(session, apply)


def backfill(session: Session, apply: bool) -> int:
    """O trabalho todo, contra uma sessão que o chamador abriu.

    Separado de `main` para ser TESTÁVEL: a segunda passada regrava o total
    congelado de faturas fechadas, que é histórico financeiro, e isso não pode
    existir sem teste só porque mora num script. `main` continua sendo o
    entrypoint que abre a sessão do engine real.

    Três passadas: converter as linhas, recongelar o total das faturas não
    abertas e reconciliar as que ficaram sub-pagas (`_finalizar`).
    """
    convertidos = 0
    faltando: list[str] = []
    # Faturas NÃO abertas que tiveram linha convertida: o total congelado delas
    # deixou de bater com a soma das compras.
    a_recongelar: set[int] = set()

    # Só o que a identidade não resolveu: a perna de fatura numa moeda que
    # não é a do cartão. O resto já está correto e não deve ser tocado.
    linhas = session.exec(
        select(Transaction, CreditCard)
        .join(CreditCard, CreditCard.id == Transaction.credit_card_id)
        .where(Transaction.statement_id.is_not(None))
        .where(Transaction.deleted_at.is_(None))
        .where(Transaction.statement_currency != CreditCard.currency)
    ).all()

    if not linhas:
        print("Nada a converter: toda compra já está na moeda do seu cartão.")
        # Sai por `_finalizar`, não com um `return 0` seco: a reconciliação é o
        # caminho de REPARO e precisa rodar justamente em quem já rodou o script
        # antes. Depois de uma conversão bem-sucedida aquelas linhas deixam de
        # casar com o filtro acima — se o reparo dependesse de "ter o que
        # converter", a fatura sub-paga que a rodada anterior deixou para trás
        # nunca mais seria reencontrada.
        return _finalizar(session, apply, convertidos=0, recongeladas=0)

    print(f"{len(linhas)} lançamento(s) com perna de fatura em moeda divergente.\n")

    for tx, card in linhas:
        try:
            # REUSA a regra de entrada em vez de reimplementá-la. A versão
            # anterior aplicava taxa × (1 + IOF) sempre, e errava justamente
            # o caso mais comum aqui: compra JÁ na moeda do cartão (USD num
            # cartão USD), cuja perna contábil está em BRL só porque o
            # workspace é BRL. Não houve conversão nenhuma, logo não há IOF —
            # US$ 20 viravam US$ 20,70 do nada. `compute_statement_conversion`
            # trata `origem == destino` na origem; duas cópias da regra
            # divergiram, como sempre divergem.
            #
            # `allow_fetch=False`: um backfill não deve depender da rede a
            # cada linha. O que faltar sai na lista para o operador buscar
            # com `backfill_rates.py` e rodar de novo.
            meta = compute_statement_conversion(
                session,
                card,
                currency=tx.original_currency or tx.currency,
                total_amount=(
                    tx.original_amount
                    if tx.original_amount is not None
                    else tx.total_amount
                ),
                transaction_date=tx.transaction_date,
                allow_fetch=False,
            )
        except HTTPException as exc:
            dia = local_day(tx.transaction_date)
            faltando.append(f"  tx #{tx.id}  {dia.isoformat()}  ({exc.detail})")
            continue

        print(
            f"  tx #{tx.id}  {tx.statement_amount} {tx.statement_currency}"
            f"  ->  {meta['statement_amount']} {meta['statement_currency']}"
        )
        # Grava SEMPRE, inclusive no dry-run — o commit é que fica de fora
        # (ver o fim da função). Sem isto o dry-run mentiria na segunda
        # passada: `compute_statement_total` soma em SQL, e com as linhas
        # ainda na moeda velha o filtro por `statement_currency` as
        # descartaria, prevendo um total que a rodada real não produziria.
        tx.statement_amount = meta["statement_amount"]
        tx.statement_currency = meta["statement_currency"]
        tx.statement_exchange_rate = meta["statement_exchange_rate"]
        session.add(tx)
        convertidos += 1

        statement = session.get(CardStatement, tx.statement_id)
        if statement is not None and statement.status != StatementStatus.open:
            a_recongelar.add(statement.id)

    if faltando:
        session.rollback()
        print("\nSem cotação para:")
        print("\n".join(faltando))
        print(
            "\nNada foi gravado. Rode `python scripts/backfill_rates.py N` "
            "cobrindo essas datas e tente de novo."
        )
        return 1

    # ---- Segunda passada: o total congelado das faturas fechadas ----------
    # `flush()` antes de somar: `compute_statement_total` roda em SQL, e sem
    # descer as alterações pendentes ele somaria os valores ANTIGOS — o
    # script gravaria o congelado errado com toda a confiança.
    if a_recongelar:
        session.flush()
        print(f"\n{len(a_recongelar)} fatura(s) fechada/paga com total congelado a corrigir:")
        for statement_id in sorted(a_recongelar):
            statement = session.get(CardStatement, statement_id)
            antes = statement.total_amount
            novo = CreditCardService.compute_statement_total(session, statement_id)
            print(
                f"  fatura #{statement_id} ({statement.month})  "
                f"{antes} -> {novo} {_moeda(session, statement)}"
            )
            statement.total_amount = novo
            session.add(statement)

    return _finalizar(session, apply, convertidos=convertidos, recongeladas=len(a_recongelar))


def _finalizar(session: Session, apply: bool, *, convertidos: int, recongeladas: int) -> int:
    """Terceira passada + commit/rollback. Ponto único de saída das duas
    entradas de `backfill` (com e sem linha a converter)."""
    _reconciliar_subpagas(session)

    if apply:
        session.commit()
        if convertidos:
            print(f"\n{convertidos} lançamento(s) convertido(s).")
        if recongeladas:
            print(f"{recongeladas} total(is) de fatura recongelado(s).")
    else:
        # O dry-run calculou tudo NO BANCO para poder prever de verdade; o
        # rollback é o que o mantém dry.
        session.rollback()
        print(f"\nDry-run: {convertidos} seriam convertidos. Use --apply para gravar.")

    return 0


def _reconciliar_subpagas(session: Session) -> list[int]:
    """Devolve para `closed` toda fatura `paid` que ainda tem saldo devedor.

    Regravar o total congelado pode revelar que a fatura foi paga a menos. O
    script não cria nem apaga pagamento — cobrar a diferença é decisão humana —,
    mas não pode deixar o estado CONTRADITÓRIO no banco: `paid` com saldo é uma
    dívida que some da tela (a UI só mostra "Saldo restante" fora de `paid`),
    some do limite do cartão (`card_overview` pula `paid`) e não pode ser quitada
    (`pay_statement` exige `closed`) — só reaberta, o que estorna todo o
    histórico de pagamentos.

    `closed` com os pagamentos intactos é o estado NORMAL de pagamento parcial,
    que o sistema inteiro já sabe tratar.

    Varre todas as faturas `paid`, não só as que este script tocou: é assim que
    ele repara um banco onde uma rodada anterior já deixou o estado para trás.
    """
    reconciliadas: list[int] = []
    linhas: list[str] = []
    for statement in session.exec(
        select(CardStatement).where(CardStatement.status == StatementStatus.paid)
    ).all():
        total = CreditCardService.effective_total(session, statement)
        pago = CreditCardService.paid_amount(session, statement)
        if total <= pago:
            continue
        statement.status = StatementStatus.closed
        statement.paid_at = None
        session.add(statement)
        reconciliadas.append(statement.id)
        linhas.append(
            f"  fatura #{statement.id} ({statement.month}): "
            f"total {total}, pago {pago}, falta {total - pago} {_moeda(session, statement)}"
        )

    if reconciliadas:
        print("\n" + "!" * 70)
        print("ATENÇÃO — estas faturas estavam SUB-PAGAS e voltaram para 'fechada':")
        print("\n".join(linhas))
        print(
            "Nenhum pagamento foi criado ou apagado — o que já foi pago continua\n"
            "registrado, e a fatura volta a aceitar 'Pagar saldo restante'.\n"
            "Cobrar ou não a diferença é decisão sua: confira o extrato do cartão."
        )
        print("!" * 70)
    return reconciliadas


def _moeda(session: Session, statement: CardStatement) -> str:
    card = session.get(CreditCard, statement.card_id)
    return card.currency if card else ""


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
