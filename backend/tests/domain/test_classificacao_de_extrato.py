"""O palpite de classificação do extrato de conta (ADR 0037): conservador de propósito."""
import pytest

from app.domain.classificacao_de_extrato import sugerir

CONTAS = [(2, "Poupança Itaú"), (3, "Nubank")]
CARTOES = [(7, "Nubank Roxinho"), (8, "Inter Gold")]


@pytest.mark.parametrize(("titulo", "sentido", "esperado"), [
    ("PAGAMENTO FATURA NUBANK", "out", ("statement_payment", 7, None)),
    ("PGTO FATURA CARTÃO", "out", ("statement_payment", None, None)),  # dois cartões, nenhum citado: a pessoa escolhe
    ("TRANSF MESMA TITULARIDADE POUPANÇA", "out", ("transfer", None, 2)),
    ("RESGATE POUPANCA", "in", ("transfer", None, 2)),
    # Só o nome não basta: é Pix para alguém que usa o Nubank.
    ("PIX ENVIADO FULANO NUBANK", "out", ("expense", None, None)),
    ("PIX RECEBIDO JOÃO", "in", ("income", None, None)),
    ("MERCADO EXTRA", "out", ("expense", None, None)),
    # Fatura que ENTROU não é pagamento (estorno, cashback): segue o sinal.
    ("ESTORNO PAGAMENTO FATURA", "in", ("income", None, None)),
])
def test_palpite(titulo, sentido, esperado):
    s = sugerir(titulo, sentido, CONTAS, CARTOES)
    assert (s.classification, s.card_id, s.counterpart_account_id) == esperado


def test_com_um_cartao_so_ele_e_o_palpite():
    assert sugerir("PAGTO FATURA", "out", CONTAS, [(9, "C6")]).card_id == 9
