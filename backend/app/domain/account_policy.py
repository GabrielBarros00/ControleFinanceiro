"""A conta é a unidade de conta do saldo — e por isso a moeda tem de bater (ADR 0034).

`PaymentAccount.currency` deixou de ser rótulo no dia em que o saldo passou a ser
derivado dos movimentos atribuídos a ela. A soma é literal: `TransactionPayer.amount`,
`StatementPayment.amount` e `Income.amount` entram no saldo **na moeda em que foram
gravados**, e o total da conta é apresentado na moeda DELA. Se as duas divergirem, o
saldo soma laranja com maçã e o erro é mudo — o número aparece, só está errado.

Não é caso de borda. `base_currency_service` estabelece que todo valor é persistido na
moeda-base do workspace: num espaço de base USD, **todo** `TransactionPayer.amount` está
em USD. Antes deste módulo os três gates de `_validate_payer_accounts` (existe, é do
pagador, está ativa) deixavam passar "esses USD 500 saíram da minha conta em reais".

**`AccountTransfer` é o único lugar do sistema onde duas moedas se encontram**, e lá elas
se encontram declaradas: valor de origem, valor de destino e a taxa usada. Em qualquer
outro caminho, moeda diferente é recusa — nunca conversão silenciosa (ADR 0006/0015).

A alternativa descartada era gravar `(account_amount, account_currency)` convertidos por
movimento. Isso é um ledger contábil de verdade: cada linha passaria a ter duas
expressões do mesmo valor, que divergem quando a taxa é corrigida, e o saldo dependeria
de qual das duas se lê. Custa dez vezes mais do que um app doméstico precisa.
"""
from typing import Optional


class AccountCurrencyMismatch(ValueError):
    """Conta e movimento em moedas diferentes (o chamador traduz para 4xx)."""


def moedas_batem(account_currency: Optional[str], movement_currency: Optional[str]) -> bool:
    """As duas moedas são a mesma?

    Comparação de string em caixa alta, o mesmo critério que toda agregação usa
    (`currency == base_currency`). `None` de qualquer lado responde `True`: é
    "não informada", e recusar por ausência barraria o caminho legítimo em que a
    conta não foi declarada.
    """
    if not account_currency or not movement_currency:
        return True
    return account_currency.strip().upper() == movement_currency.strip().upper()


def assert_conta_na_moeda(account, movement_currency: Optional[str]) -> None:
    """Levanta `AccountCurrencyMismatch` quando a conta não pode receber o movimento.

    Recebe a `PaymentAccount` já carregada (quem chama acabou de validar dono e
    estado), e não o id: uma segunda consulta aqui seria repetição pura.
    """
    if account is None:
        return
    if moedas_batem(account.currency, movement_currency):
        return
    raise AccountCurrencyMismatch(
        f"A conta '{account.name}' é em {account.currency} e este movimento está em "
        f"{movement_currency}. Escolha uma conta em {movement_currency} ou registre "
        "uma transferência entre contas, que é onde duas moedas podem se encontrar."
    )
