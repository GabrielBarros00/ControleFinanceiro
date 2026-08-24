"""Contrato tipado de resumo, relatórios, previsão e câmbio.

Mesma razão de `app/schemas/overview.py`, que o ADR 0022 já registra: sem
`response_model` de verdade o OpenAPI diz só "objeto", o `api.gen.ts` gera
`{[key: string]: unknown}` e o frontend escreve a interface à mão. Quando o
backend muda um campo, nada acusa — `use-analytics.ts` chegava a devolver
`response.data` cru, sem tipo nenhum.

**`None` não é `0`.** Os campos da CASA são suprimidos com `null` para quem não
tem acesso financeiro completo (ADR 0018), e `docs/API.md` obriga o cliente a
tratar `null` como "sem acesso" em vez de coagir para zero. Por isso eles são
`Optional[...]` aqui, e não `Decimal` com default — o tipo gerado no frontend
passa a forçar essa distinção no compilador.

**Decimal, não float.** Sai como string decimal no JSON (é o que `docs/API.md`
manda e o que o resto do app já faz); float reintroduziria a perda de centavos
que o ADR 0001 fechou.
"""
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class CategorySlice(BaseModel):
    """Uma fatia da pizza de categorias.

    `category_id` acompanha o nome porque o orçamento casa gasto × meta por id
    (BUD-001): casar por nome quebrava calado ao renomear a categoria. É `None`
    na fatia sintética "Sem categoria".
    """
    category_id: Optional[int] = None
    name: str
    value: Decimal


class SummaryRead(BaseModel):
    """O mês de UM workspace, com o recorte de quem perguntou."""
    #: Total da casa — `None` sem acesso completo (ADR 0018), nunca 0.
    total_expenses: Optional[Decimal] = None
    #: Composição da casa — suprimida junto com o total, pela mesma regra.
    categories: Optional[List[CategorySlice]] = None

    #: Daqui para baixo é dado do PRÓPRIO usuário e nunca é suprimido.
    my_expenses: Decimal
    paid_by_me: Decimal
    #: Positivo = adiantei e tenho a receber; negativo = devo. Já descontados os
    #: acertos do mês, e recortado neste workspace (não compensa com outros).
    my_balance: Decimal
    my_categories: List[CategorySlice] = []

    base_currency: str
    #: Lançamentos em outra moeda ficam FORA dos totais (ADR 0006); a contagem
    #: existe para o usuário saber que sumiram de propósito.
    excluded_foreign_count: int = 0


class MonthlyHistoryPoint(BaseModel):
    """Uma barra do histórico de 6 meses."""
    #: `YYYY-MM` — o rótulo AUTORITATIVO. Quem desenha formata a partir daqui.
    month: str
    #: Abreviação de `strftime("%b")`, que segue o locale do processo (no
    #: container, inglês). Mantido por compatibilidade; não use para exibir.
    name: str
    #: Barra da casa — `None` sem acesso completo (ADR 0018).
    expenses: Optional[Decimal] = None
    my_expenses: Decimal


class ReportsRead(BaseModel):
    monthly_history: List[MonthlyHistoryPoint]
    current_summary: SummaryRead


class ForecastRead(BaseModel):
    """Previsão de fechamento do mês.

    Todo campo da casa é `Optional` porque a resposta sem acesso completo devolve
    o MESMO conjunto de chaves com `null` — e não um objeto menor. Resposta que
    muda de forma conforme quem pergunta é o que fazia o cliente adivinhar.
    """
    month: str
    base_currency: str
    #: Meta PESSOAL de quem pediu — é o que o Painel compara com "sua despesa".
    my_budget: Decimal

    excluded_foreign_count: Optional[int] = None
    actual_spent: Optional[Decimal] = None
    projected_eom: Optional[Decimal] = None
    daily_average: Optional[Decimal] = None
    remaining_days: Optional[int] = None
    fixed_costs_pending: Optional[Decimal] = None
    total_budget: Optional[Decimal] = None
    is_over_budget: Optional[bool] = None


class ExchangeRateRead(BaseModel):
    """Taxa de referência + de onde ela veio.

    `rate` é string decimal de propósito (o serviço devolve `str(rate)`): é uma
    cotação com muitas casas, e um float aqui volta a arredondar na exibição da
    dica que o formulário mostra antes de gravar o lançamento.
    """
    from_currency: str
    to_currency: str
    rate: str
    #: `ptax` (oficial, majores → BRL) ou a fonte de mercado.
    source: str
