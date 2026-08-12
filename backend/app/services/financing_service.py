from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import List, Dict, Any
from app.domain.dates import add_months
from app.domain.money import Money
from app.models.financing import AmortizationMethod, AmortizationInstallment

class AmortizationError(ValueError):
    """Cronograma impossível de representar — vira 422, nunca 500."""


class FinancingService:
    @staticmethod
    def _assert_representavel(
        total_amount: Decimal,
        interest_rate: Decimal,
        installments_count: int,
        method: AmortizationMethod,
    ) -> None:
        """Recusa o que o cronograma não consegue expressar em centavos.

        Duas entradas chegavam inteiras ao cálculo e produziam lixo:

        **Parcela abaixo de um centavo.** Não há como representá-la, e um
        cronograma com parcelas de R$ 0,00 não descreve financiamento nenhum.
        (A parcela final NEGATIVA que a auditoria mediu — R$ 10,00 em 600x
        gerando `-1,98` — tinha outra causa, corrigida na própria geração do
        SAC: ver `_principais_sac`.)

        **Prestação que não cobre os juros (PRICE).** Com juros altos o
        arredondamento da PMT pode deixar a amortização do período negativa; o
        saldo então CRESCE, cresce composto, e em algumas dezenas de períodos
        estoura o contexto do `Decimal` — `InvalidOperation`, que sobe como 500.
        Medido: R$ 12.345,67 a 0,5 a.m. em 360x devolvia **HTTP 500** na criação
        do financiamento. `interest_rate` não tinha teto no schema.

        Recusar é a resposta certa nos dois casos: não existe cronograma válido,
        e inventar um seria pior que dizer não.
        """
        if installments_count <= 0:
            raise AmortizationError("O número de parcelas precisa ser maior que zero.")

        centavo = Decimal("0.01")
        if total_amount / installments_count < centavo:
            raise AmortizationError(
                f"{installments_count} parcelas deixam menos de um centavo em cada "
                f"uma. Reduza o número de parcelas ou aumente o valor."
            )

        if method == AmortizationMethod.PRICE and interest_rate > 0:
            # Primeira parcela: se a PMT não cobre os juros do período, o saldo
            # nunca cai — não é um financiamento, é uma dívida que só cresce.
            factor = (1 + interest_rate) ** installments_count
            pmt = (total_amount * (interest_rate * factor) / (factor - 1)).quantize(
                centavo, rounding=ROUND_HALF_UP
            )
            juros_primeiro = (total_amount * interest_rate).quantize(
                centavo, rounding=ROUND_HALF_UP
            )
            if pmt <= juros_primeiro:
                raise AmortizationError(
                    "Com esta taxa, a prestação não cobre nem os juros do mês e a "
                    "dívida nunca seria quitada. Revise a taxa ou o prazo."
                )

    @staticmethod
    def _principais_sac(total_amount: Decimal, installments_count: int) -> List[Decimal]:
        """A coluna de amortização do SAC, alocada em CENTAVOS (ADR 0001).

        Antes era uma cota arredondada UMA vez e repetida, com a última parcela
        recebendo "o que sobrou". Quando `total/n` arredondava para cima, as
        `n-1` primeiras consumiam mais que o total e a última nascia NEGATIVA —
        R$ 10,00 em 600x terminava com uma parcela de `-1,98`. A tela não
        denunciava porque a linha do saldo usa `max(0, saldo)`.

        `split_equal` é a mesma primitiva que divide uma despesa entre pessoas, e
        pelo mesmo motivo: em centavos inteiros, soma exata por construção, resto
        de 1 centavo distribuído aos primeiros. "Amortização constante" com
        granularidade de centavo é isto — parcelas que diferem em no máximo um
        centavo —, e não uma cota fracionária que só fecha no papel.
        """
        return [m.amount for m in Money(total_amount).split_equal(installments_count)]

    @staticmethod
    def calculate_amortization_schedule(
        total_amount: Decimal,
        interest_rate: Decimal,  # Monthly rate (e.g., 0.01 for 1%)
        installments_count: int,
        start_date: date,
        method: AmortizationMethod
    ) -> List[AmortizationInstallment]:
        FinancingService._assert_representavel(
            total_amount, interest_rate, installments_count, method
        )
        schedule = []
        remaining_balance = total_amount

        if method == AmortizationMethod.SAC:
            # SAC: amortização constante — em CENTAVOS (ADR 0001).
            principais = FinancingService._principais_sac(total_amount, installments_count)

            for i in range(1, installments_count + 1):
                interest_amount = (remaining_balance * interest_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                principal_amortization = principais[i - 1]
                total_installment = principal_amortization + interest_amount
                remaining_balance -= principal_amortization
                
                due_date = add_months(start_date, i)  # mês de calendário
                
                schedule.append(AmortizationInstallment(
                    installment_number=i,
                    due_date=due_date,
                    principal_amount=principal_amortization,
                    interest_amount=interest_amount,
                    total_amount=total_installment,
                    remaining_balance=max(Decimal("0.00"), remaining_balance)
                ))
                
        elif method == AmortizationMethod.PRICE:
            # PRICE: Constant Total Installment
            # PMT = P * [i(1+i)^n] / [(1+i)^n - 1]
            if interest_rate > 0:
                factor = (1 + interest_rate) ** installments_count
                pmt = (total_amount * (interest_rate * factor) / (factor - 1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                pmt = (total_amount / installments_count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                
            for i in range(1, installments_count + 1):
                interest_amount = (remaining_balance * interest_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                
                # Adjust last installment for rounding
                if i == installments_count:
                    principal_amortization = remaining_balance
                    total_installment = principal_amortization + interest_amount
                else:
                    # `min` com o saldo: no PRICE a amortização do período é
                    # `pmt - juros`, e o arredondamento da PMT para centavos faz
                    # essas cotas somarem um pouco MAIS que o principal em
                    # financiamentos pequenos. Sem o teto, as `n-1` primeiras
                    # consumiam mais que o total e a última — que recebe o saldo
                    # — nascia negativa (R$ 0,50 em 36x terminava em `-0,20`).
                    # É o mesmo defeito que o SAC tinha, e aqui não dá para usar
                    # `split_equal`: a cota do PRICE varia a cada período.
                    #
                    # Num financiamento de verdade `pmt - juros` é muito menor que
                    # o saldo e o `min` não faz nada; ele só age no fim da cauda,
                    # onde impede a parcela negativa. Depois que o saldo zera, as
                    # parcelas restantes ficam em zero — que é a descrição honesta
                    # de um prazo maior do que o principal comporta em centavos.
                    principal_amortization = min(pmt - interest_amount, remaining_balance)
                    total_installment = principal_amortization + interest_amount

                remaining_balance -= principal_amortization
                
                due_date = add_months(start_date, i)  # mês de calendário
                
                schedule.append(AmortizationInstallment(
                    installment_number=i,
                    due_date=due_date,
                    principal_amount=principal_amortization,
                    interest_amount=interest_amount,
                    total_amount=total_installment,
                    remaining_balance=max(Decimal("0.00"), remaining_balance)
                ))
                
        return schedule

    @staticmethod
    def simulate_early_settlement(
        remaining_installments: List[AmortizationInstallment],
        settlement_date: date,
        monthly_interest_rate: Decimal
    ) -> Dict[str, Any]:
        """
        Simulates the 'quitar' action (early settlement).
        Calculates the Present Value (PV) of future installments.
        """
        total_to_pay = Decimal("0.00")
        total_original_value = Decimal("0.00")
        total_savings = Decimal("0.00")
        
        for inst in remaining_installments:
            total_original_value += inst.total_amount
            
            # Simplified PV calculation for each installment
            # PV = FV / (1 + i)^n
            # n is the number of months between settlement and due_date
            months_early = max(0, (inst.due_date.year - settlement_date.year) * 12 + (inst.due_date.month - settlement_date.month))
            
            pv = (inst.total_amount / ((1 + monthly_interest_rate) ** months_early)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_to_pay += pv
            
        total_savings = total_original_value - total_to_pay
        
        return {
            "total_to_pay": total_to_pay,
            "original_value": total_original_value,
            "savings": total_savings,
            "installments_settled": len(remaining_installments)
        }
