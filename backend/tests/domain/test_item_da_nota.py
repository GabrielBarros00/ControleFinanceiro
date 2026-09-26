"""A regra da linha da nota (ADR 0040): os casos reais e a varredura que a sustenta."""
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

import pytest

from app.domain.item_da_nota import (
    UNIDADES,
    problema_da_linha,
    total_da_linha,
    unitario_depois_de_rateio,
)

D = Decimal


@pytest.mark.parametrize("quantidade, unitario, impresso", [
    # Balança que arredonda e balança que trunca: as duas leituras são honestas.
    ("1.235", "39.90", "49.28"),
    ("1.235", "39.90", "49.27"),
    # O caso que a tela recusava: 2,050 × 19,90 = 40,795.
    ("2.050", "19.90", "40.80"),
    ("2.050", "19.90", "40.79"),
    # Combustível: o preço do litro tem 3 casas.
    ("40.123", "5.899", "236.69"),
    ("40.123", "5.899", "236.68"),
    # Produto exato: até 1 centavo de diferença é o arredondamento aceito.
    ("2", "25.00", "50.00"),
    ("2", "25.00", "50.01"),
])
def test_leituras_honestas_da_nota_passam(quantidade, unitario, impresso):
    assert problema_da_linha("Item", D(quantidade), D(unitario), D(impresso), "kg") is None


@pytest.mark.parametrize("quantidade, unitario, impresso", [
    ("1.235", "39.90", "49.40"),   # 12 centavos: leitura errada
    ("12.35", "39.90", "49.28"),   # a vírgula no lugar errado
    ("2", "25.00", "50.02"),       # 2 centavos num produto exato
])
def test_leitura_errada_e_recusada_dizendo_o_porque(quantidade, unitario, impresso):
    problema = problema_da_linha("Carne", D(quantidade), D(unitario), D(impresso), "kg")
    assert problema is not None
    assert "Carne" in problema and "até 1 centavo" in problema


def test_unidade_fora_do_vocabulario_e_recusada():
    assert problema_da_linha("Arroz", D("1"), D("30"), D("30"), "saco") is not None
    for unidade in UNIDADES:
        assert problema_da_linha("Arroz", D("1"), D("30"), D("30"), unidade) is None


def test_preco_unitario_aceita_ate_quatro_casas():
    assert problema_da_linha("Gasolina", D("10"), D("5.8990"), D("58.99"), "l") is None
    assert "4 casas" in problema_da_linha("Gasolina", D("10"), D("5.89901"), D("58.99"), "l")


def test_sem_unitario_nao_ha_o_que_conferir():
    """Linha antiga, item-sombra da categoria: só o total, como sempre foi."""
    assert problema_da_linha("Mercado", D("1"), None, D("150.00")) is None


def test_qualquer_balanca_passa_na_varredura():
    """0,001 a 5,000 kg × 14 preços, arredondando E truncando: nenhuma recusa.

    É a varredura que achou 2,050 × 19,90 do lado da tela; aqui ela garante que
    a regra do servidor aceita toda leitura legítima.
    """
    precos = [D(p) for p in ("0.99", "1.99", "3.99", "5.99", "7.99", "12.99", "19.90",
                             "24.90", "29.99", "39.90", "45.90", "59.99", "89.90", "99.99")]
    recusas = []
    for milesimos in range(1, 5001):
        quantidade = D(milesimos) / 1000
        for preco in precos:
            exato = quantidade * preco
            for impresso in (exato.quantize(D("0.01"), ROUND_HALF_UP), exato.quantize(D("0.01"), ROUND_DOWN)):
                if problema_da_linha("x", quantidade, preco, impresso, "kg"):
                    recusas.append((quantidade, preco, impresso))
    assert recusas == []


def test_total_derivado_arredonda_ao_centavo():
    assert total_da_linha(D("2.050"), D("19.90")) == D("40.80")
    assert total_da_linha(D("40.123"), D("5.899")) == D("236.69")


def test_rateio_preserva_a_medida_e_recalcula_o_unitario():
    """Conversão de moeda: R$ 49,28 viram US$ 9,87 — a linha continua sendo 1,235 kg."""
    unitario = unitario_depois_de_rateio(D("9.87"), D("1.235"))
    assert unitario == D("7.9919")
    assert problema_da_linha("Carne", D("1.235"), unitario, D("9.87"), "kg") is None


def test_rateio_sem_unitario_possivel_devolve_nada():
    """Com quantidade enorme nem 4 casas fecham o total: melhor sem unitário que errado."""
    assert unitario_depois_de_rateio(D("100.00"), D("0")) is None
    # 100.000 un × 0,1235 = 12.350,00 ≠ 12.345,67: a 4ª casa não alcança.
    assert unitario_depois_de_rateio(D("12345.67"), D("100000")) is None
    # Unitário zero para um total positivo não é preço.
    assert unitario_depois_de_rateio(D("0.01"), D("999999.999")) is None
