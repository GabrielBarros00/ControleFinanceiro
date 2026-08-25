"""Quando um lançamento nasce LIQUIDADO — ponto único de decisão (ADR 0029).

`Transaction.settled_at` é a data em que o dinheiro saiu de fato. Até o ADR 0029
essa data não existia: `CashFlowService` lia `transaction_date` e afirmava que
toda despesa fora do cartão saía do bolso no instante em que era registrada.
`payment_method` não entrava em consulta nenhuma — Pix, dinheiro, boleto e
transferência eram rótulos sem efeito, e o status `paid`, que deveria significar
"foi pago", não era escrito por nenhuma rota nem por nenhuma tela.

A regra mora aqui, e não espalhada nos seis caminhos que constroem `Transaction`,
porque o modo de falha é silencioso nos dois sentidos: um caminho que esquece de
liquidar some com a despesa do caixa; um que liquida sempre reintroduz o defeito
que este módulo veio fechar. `tests/test_liquidacao_ponto_unico.py` é o portão que
mantém a lista fechada.
"""
from datetime import datetime
from typing import Optional

from app.domain.dates import local_day, today_local


def _do_espaco(session, workspace_id: int) -> bool:
    """O espaço controla o pagamento das contas?

    Espaço inexistente responde `True` (o padrão do modelo): melhor exigir a
    confirmação de um pagamento do que afirmar uma saída de caixa que talvez não
    tenha acontecido.
    """
    from app.models.workspace import Workspace

    ws = session.get(Workspace, workspace_id)
    return True if ws is None else bool(ws.settlement_tracking)


def resolve_settled_at(
    session,
    workspace_id: int,
    *,
    transaction_date: datetime,
    credit_card_id: Optional[int] = None,
    explicit: Optional[bool] = None,
) -> Optional[datetime]:
    """A data de liquidação com que o lançamento nasce, ou `None` (a pagar).

    As regras, nesta ordem — a ordem importa:

    1. **Espaço sem controle de pagamento** → sempre liquidado na data do
       lançamento. É o comportamento anterior ao ADR 0029, preservado inteiro
       para quem não quiser a etapa a mais.
    2. **Compra no cartão** → `None`, e ela nunca aparece em Contas a pagar
       (o índice `ix_transaction_a_liquidar` exclui `credit_card_id`). O caixa
       dela é o pagamento da FATURA, e marcar a compra como paga somaria a mesma
       saída duas vezes.
    3. **`explicit` informado** vence o palpite da data. É o "Já foi paga" do
       formulário, o `True` do import (fato consumado) e o `auto_settle` da
       recorrência.
    4. **Padrão**: liquidado se a data já chegou, a pagar se está no futuro.

    O palpite da regra 4 vale para o que uma PESSOA digitou: quem registra uma
    despesa de ontem está anotando o que aconteceu; quem cadastra o boleto que
    vence dia 30 está anotando o que ainda vai acontecer. Ele **não** vale para o
    que a máquina gerou — a ocorrência que a recorrência materializou no dia 10
    tem a data no passado e mesmo assim ninguém afirmou ter pago nada. Por isso a
    recorrência sempre informa `explicit` (com o `auto_settle` do template) em vez
    de deixar o padrão decidir.

    A data de liquidação é `transaction_date`, não "agora": lançar hoje a compra
    de ontem tem de mover o caixa de ONTEM, senão o extrato do mês fechado muda
    conforme a hora em que alguém lembrou de digitar.
    """
    if not _do_espaco(session, workspace_id):
        return transaction_date
    if credit_card_id is not None:
        return None
    if explicit is not None:
        return transaction_date if explicit else None
    return transaction_date if local_day(transaction_date) <= today_local() else None
