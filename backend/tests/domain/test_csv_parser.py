import io
from decimal import Decimal
from datetime import date
from app.services.csv_parser import CSVParserService, CSVColumnMapping

def test_parse_simple_csv():
    csv_content = """Data,Descrição,Valor
2024-01-15,Mercado,-150.50
2024-01-16,Restaurante,-80.00
2024-01-17,Salário,5000.00
"""
    file_like = io.StringIO(csv_content)
    mapping = CSVColumnMapping(
        date_column="Data",
        description_column="Descrição",
        amount_column="Valor",
        date_format="%Y-%m-%d"
    )
    
    result = CSVParserService.parse(file_like, mapping)
    transactions = result["rows"]

    assert result["skipped"] == []
    assert len(transactions) == 3
    assert transactions[0]["title"] == "Mercado"
    # invert_amount=True: valores viram MÓDULO (tratados como despesa — ADR 0008)
    assert transactions[0]["total_amount"] == Decimal("150.50")
    assert transactions[0]["transaction_date"].date() == date(2024, 1, 15)

    assert transactions[2]["title"] == "Salário"
    assert transactions[2]["total_amount"] == Decimal("5000.00")

def test_parse_csv_different_delimiters():
    # Nubank style: Data;Valor;Identificador;Descrição
    csv_content = """Data;Valor;Identificador;Descrição
15/01/2024;-150,50;123;Mercado
"""
    file_like = io.StringIO(csv_content)
    mapping = CSVColumnMapping(
        date_column="Data",
        description_column="Descrição",
        amount_column="Valor",
        date_format="%d/%m/%Y",
        delimiter=";",
        decimal_separator=","
    )
    
    result = CSVParserService.parse(file_like, mapping)
    transactions = result["rows"]
    assert len(transactions) == 1
    assert transactions[0]["title"] == "Mercado"
    assert transactions[0]["total_amount"] == Decimal("150.50")
    assert transactions[0]["transaction_date"].date() == date(2024, 1, 15)


def test_parse_reporta_linhas_invalidas_com_motivo():
    """ADR 0008: nenhuma linha é descartada em silêncio."""
    csv_content = """Data,Descrição,Valor
2024-01-15,Mercado,-150.50
data-invalida,Padaria,-10.00
2024-01-17,Farmácia,abc
2024-01-18,,
"""
    file_like = io.StringIO(csv_content)
    mapping = CSVColumnMapping(
        date_column="Data",
        description_column="Descrição",
        amount_column="Valor",
        date_format="%Y-%m-%d",
    )

    result = CSVParserService.parse(file_like, mapping)

    assert len(result["rows"]) == 1
    assert result["rows"][0]["title"] == "Mercado"

    skipped = {s["line"]: s["reason"] for s in result["skipped"]}
    assert len(skipped) == 3
    assert "formato" in skipped[3]      # data inválida
    assert "número" in skipped[4]       # valor inválido
    assert "ausente" in skipped[5]      # campos vazios
