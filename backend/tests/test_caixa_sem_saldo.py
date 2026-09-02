"""Guarda mecânica: saldo e caixa não podem se contaminar (ADR 0034).

Três invariantes que nenhum teste de comportamento pega quando alguém acrescenta
uma fonte nova sem pensar, e cujo modo de falha é um número errado que ninguém
percebe:

1. **`CASH_SOURCES` continua com SEIS fontes.** Se transferência ou ajuste virarem
   fonte de caixa, `get_month` os soma em `cash_in`/`cash_out` sem netting: uma
   transferência de R$ 1.000 entre contas minhas infla os dois lados em 1.000 e o
   `net_cash` fica certo por acidente, com os dois números do topo mentindo.
2. **`cashflow_service` não importa `AccountEntry` nem `AccountTransfer`.** É a
   barreira estrutural da anterior — sem o import, a contaminação nem se escreve.
3. **Toda fonte de caixa sabe declarar a conta, ou está na lista dos que não sabem
   com o motivo escrito.** No espírito de `test_read_policy_coverage`: acrescentar
   uma sétima fonte sem decidir de qual conta ela sai faz o saldo silenciosamente
   ignorá-la.

Um gate de AST exigindo `account_id` em toda construção seria a forma ERRADA da
terceira: a conta é legitimamente opcional (`transaction_service` diz "sem conta
declarada o lançamento continua válido"), então o gate seria satisfeito com
`account_id=None` em todo lugar e não provaria nada. O que se afirma aqui é que a
CONSULTA da fonte projeta uma coluna de conta.
"""
import ast
import inspect
from pathlib import Path

from app.services import cashflow_service as cf

#: As fontes que, hoje, não têm de onde tirar a conta — com o porquê. Mexer nesta
#: lista é uma decisão, não um detalhe: cada entrada é um buraco conhecido no saldo.
SEM_CONTA = {
    # Nenhuma. `settlement_received` chegou a ser candidata — a conta do credor é
    # invisível para o devedor, que é quem registra o acerto —, mas ela ganhou
    # porta própria (`PUT /me/settlements/{id}/account`) em vez de virar exceção.
}


def test_o_caixa_tem_exatamente_seis_fontes():
    assert len(cf.CASH_SOURCES) == 6, (
        "Fonte nova em CASH_SOURCES (ADR 0022/0034). Se ela for transferência ou "
        "ajuste, NÃO pertence aqui: os dois movem saldo e não são entrada nem "
        "saída de caixa. Ver ACCOUNT_SOURCES em account_balance_service."
    )
    assert set(cf.CASH_SOURCES) == {
        cf.SOURCE_TRANSACTION,
        cf.SOURCE_STATEMENT_PAYMENT,
        cf.SOURCE_SETTLEMENT_SENT,
        cf.SOURCE_SETTLEMENT_RECEIVED,
        cf.SOURCE_FINANCING_INSTALLMENT,
        cf.SOURCE_INCOME,
    }


def test_o_caixa_nao_conhece_o_ledger_de_saldo():
    """Barreira estrutural: sem o import, a contaminação não se escreve."""
    fonte = Path(inspect.getfile(cf)).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")
            importados.update(a.name for a in no.names)
        elif isinstance(no, ast.Import):
            importados.update(a.name for a in no.names)

    proibidos = {"AccountEntry", "AccountTransfer", "app.models.account_ledger"}
    assert not (importados & proibidos), (
        f"`cashflow_service` importou {importados & proibidos}. Transferência e "
        "ajuste movem SALDO, não caixa — eles moram em `account_balance_service`."
    )


def test_toda_fonte_de_caixa_projeta_a_conta():
    """Cada uma das seis consultas seleciona uma coluna que resolve para conta.

    A verificação é sobre o CÓDIGO da consulta, não sobre uma construção: é ali
    que a conta entra ou deixa de entrar no `CashMovement`.
    """
    consultas = {
        cf.SOURCE_TRANSACTION: cf.CashFlowService._lancamentos,
        cf.SOURCE_STATEMENT_PAYMENT: cf.CashFlowService._pagamentos_de_fatura,
        cf.SOURCE_SETTLEMENT_SENT: cf.CashFlowService._acertos,
        cf.SOURCE_SETTLEMENT_RECEIVED: cf.CashFlowService._acertos,
        cf.SOURCE_FINANCING_INSTALLMENT: cf.CashFlowService._parcelas,
        cf.SOURCE_INCOME: cf.CashFlowService._rendas,
    }
    assert set(consultas) == set(cf.CASH_SOURCES), (
        "fonte de caixa sem consulta mapeada aqui — o gate deixou de cobrir tudo"
    )

    sem_conta = []
    for origem, funcao in consultas.items():
        if origem in SEM_CONTA:
            continue
        corpo = inspect.getsource(funcao)
        if "account_id=" not in corpo:
            sem_conta.append(origem)

    assert not sem_conta, (
        "Fonte de caixa que não declara a conta do movimento (ADR 0034): "
        f"{sem_conta}.\nO saldo por conta a ignora em silêncio. Projete a coluna "
        "de conta no `CashMovement` ou acrescente a fonte a `SEM_CONTA` com o "
        "motivo escrito."
    )
