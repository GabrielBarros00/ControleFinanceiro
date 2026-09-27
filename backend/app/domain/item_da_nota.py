"""A linha da nota: quantidade, unidade, preço unitário e o total impresso (ADR 0040).

Uma regra só para os três caminhos que gravam item — o schema da API (tela), as
tools do MCP e as conversões internas —, e o frontend a replica em
`src/lib/item-da-nota.ts` com um teste que exige o mesmo resultado.

**O total impresso é a verdade.** Balanças e caixas arredondam `quantidade ×
unitário` de formas diferentes (umas arredondam, outras truncam), e a nota que a
pessoa tem na mão é o fato. Por isso a conferência aceita diferença de até um
centavo entre o produto EXATO e o total da linha: 1,235 kg × R$ 39,90 = 49,2765,
e tanto R$ 49,27 quanto R$ 49,28 são leituras honestas. Diferença maior é leitura
errada (1,235 ou 12,35 kg?) e é recusada com uma mensagem que diz isso.

**Preço unitário com até 4 casas.** Combustível é vendido a R$ 5,899 o litro; com 2
casas o banco gravava 5,90 em silêncio. O valor LANÇADO (o total da linha) continua
em centavos (ADR 0001) — o unitário é um preço de referência, não um lançamento.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

#: Unidades aceitas. Decisão do dono (2026-09-26): só estas, por enquanto.
UNIDADES = ("un", "kg", "g", "l", "ml", "m")
Unidade = Literal["un", "kg", "g", "l", "ml", "m"]

#: Diferença máxima entre `quantidade × unitário` (exato) e o total da linha.
TOLERANCIA = Decimal("0.01")

CASAS_UNITARIO = 4
CASAS_QUANTIDADE = 3

_CENTAVO = Decimal("0.01")
_QUANTUM_UNITARIO = Decimal(1).scaleb(-CASAS_UNITARIO)


def total_da_linha(quantidade: Decimal, unitario: Decimal) -> Decimal:
    """O total derivado quando a nota não traz o da linha: arredondado ao centavo."""
    return (Decimal(quantidade) * Decimal(unitario)).quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def casas_decimais(valor: Decimal) -> int:
    expoente = Decimal(valor).normalize().as_tuple().exponent
    return max(0, -expoente) if isinstance(expoente, int) else 0


def _br(valor: Decimal, casas: int) -> str:
    texto = f"{Decimal(valor):.{casas}f}".replace(".", ",")
    if casas > 2 and "," in texto:
        texto = texto.rstrip("0")
        if texto.endswith(","):
            texto = texto[:-1]
    return texto


def descreve(quantidade: Decimal, unidade: Optional[str], unitario: Decimal) -> str:
    """ "1,235 kg × R$ 39,90" — para mensagens."""
    medida = f"{_br(quantidade, CASAS_QUANTIDADE)} {unidade}" if unidade else _br(quantidade, CASAS_QUANTIDADE)
    return f"{medida} × R$ {_br(unitario, max(2, casas_decimais(unitario)))}"


def problema_da_linha(
    titulo: str,
    quantidade: Decimal,
    unitario: Optional[Decimal],
    total: Decimal,
    unidade: Optional[str] = None,
) -> Optional[str]:
    """`None` se a linha fecha; senão, a mensagem em pt-BR que explica o porquê."""
    if unidade is not None and unidade not in UNIDADES:
        return f"Item \"{titulo}\": unidade \"{unidade}\" não aceita. Use uma de: {', '.join(UNIDADES)}."
    if unitario is None:
        return None
    if casas_decimais(unitario) > CASAS_UNITARIO:
        return f"Item \"{titulo}\": o preço unitário aceita no máximo {CASAS_UNITARIO} casas decimais."
    exato = Decimal(quantidade) * Decimal(unitario)
    if abs(exato - Decimal(total)) <= TOLERANCIA:
        return None
    return (
        f"Item \"{titulo}\": {descreve(quantidade, unidade, unitario)} = R$ {_br(total_da_linha(quantidade, unitario), 2)}, "
        f"mas o total da linha é R$ {_br(total, 2)}. Confira a nota — a diferença aceita é de até 1 centavo "
        "(o arredondamento da balança ou do caixa); mais que isso costuma ser a quantidade ou o preço lidos errado."
    )


def unitario_depois_de_rateio(total: Decimal, quantidade: Decimal) -> Optional[Decimal]:
    """O preço unitário que acompanha um total REESCRITO (conversão de moeda, rateio
    da edição parcial), mantendo quantidade e unidade.

    Antes a linha virava `1 × total` e a medida se perdia ("1,235 kg" sumia). Agora a
    quantidade fica e o unitário é recalculado com 4 casas — ou vira `None` quando
    nem com 4 casas ele fecharia o total dentro da tolerância (quantidades enormes).
    """
    quantidade = Decimal(quantidade)
    if quantidade <= 0:
        return None
    unitario = (Decimal(total) / quantidade).quantize(_QUANTUM_UNITARIO, rounding=ROUND_HALF_UP)
    if unitario == 0 and Decimal(total) > 0:
        return None
    if abs(quantidade * unitario - Decimal(total)) <= TOLERANCIA:
        return unitario
    return None
