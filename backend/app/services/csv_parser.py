import csv
from typing import TextIO, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal

from app.domain.dates import civil_instant

class CSVColumnMapping(BaseModel):
    date_column: str
    description_column: str
    amount_column: str
    date_format: str = "%Y-%m-%d"
    delimiter: str = ","
    decimal_separator: str = "."
    # Tratar valores como DESPESA (ADR 0008): importa o módulo do valor —
    # extratos bancários trazem despesas negativas; positivos ficam como estão.
    # Se false, mantém o sinal original (linhas <= 0 são recusadas no /bulk).
    invert_amount: bool = True
    # Extrato de CONTA (ADR 0037): o sinal É a informação — positivo entrou,
    # negativo saiu. A linha sai com `direction` e o valor em módulo; o
    # `invert_amount` não se aplica.
    keep_sign: bool = False
    # Coluna com o id que o banco dá à linha (opcional): deduplica melhor que a
    # impressão digital de data + valor + título.
    id_column: Optional[str] = None

class CSVParserService:
    @staticmethod
    def parse(file_obj: TextIO, mapping: CSVColumnMapping) -> Dict[str, Any]:
        """Lê um CSV e retorna {"rows": [...], "skipped": [...]}.

        Nenhuma linha é descartada em silêncio (ADR 0008): cada linha inválida
        entra em skipped com o número da linha e o motivo em PT-BR.
        """
        rows = []
        skipped = []
        reader = csv.DictReader(file_obj, delimiter=mapping.delimiter)

        # Linha 1 é o cabeçalho; dados começam na 2
        for line_no, row in enumerate(reader, start=2):
            raw_date = row.get(mapping.date_column, "")
            raw_desc = row.get(mapping.description_column, "")
            raw_amount = row.get(mapping.amount_column, "")

            if not raw_date or not raw_amount:
                skipped.append({"line": line_no, "reason": "data ou valor ausente"})
                continue

            # Parse Date
            #
            # `civil_instant`: a coluna de data de um extrato é um DIA DE
            # CALENDÁRIO, e `strptime` de um formato só-data devolve meia-noite.
            # Carimbar isso como UTC produzia uma data civil disfarçada de
            # instante — "01/08" ficava gravado como `2026-08-01T00:00Z`, que
            # todo leitor de fuso negativo lê como 31 de julho. A linha do dia 1º
            # do mês entrava na competência anterior. Ancorar aqui, na fronteira
            # onde ainda se sabe que aquilo é uma data, deixa o resto do caminho
            # tratando um instante de verdade.
            try:
                dia = datetime.strptime(raw_date.strip(), mapping.date_format).date()
                dt = civil_instant(dia)
            except ValueError:
                skipped.append({
                    "line": line_no,
                    "reason": f"data '{raw_date.strip()}' não corresponde ao formato {mapping.date_format}",
                })
                continue

            # Parse Amount
            # Remove pontos de milhar, troca vírgula decimal se necessário
            amount_str = raw_amount.strip()
            if mapping.decimal_separator == ",":
                amount_str = amount_str.replace(".", "") # Remove pontos de milhar
                amount_str = amount_str.replace(",", ".")
            else:
                amount_str = amount_str.replace(",", "") # Remove vírgulas de milhar

            try:
                amount = Decimal(amount_str)
            except Exception:
                skipped.append({
                    "line": line_no,
                    "reason": f"valor '{raw_amount.strip()}' não é um número válido",
                })
                continue

            if mapping.keep_sign:
                if amount == 0:
                    skipped.append({"line": line_no, "reason": "valor zero não é movimento"})
                    continue
                linha = {
                    "line": line_no,
                    "title": raw_desc.strip(),
                    "total_amount": abs(amount),
                    "transaction_date": dt,
                    "direction": "in" if amount > 0 else "out",
                }
                if mapping.id_column:
                    linha["external_id"] = (row.get(mapping.id_column) or "").strip()[:120] or None
                rows.append(linha)
                continue

            if mapping.invert_amount:
                amount = abs(amount)

            rows.append({
                "line": line_no,
                "title": raw_desc.strip(),
                "total_amount": amount,
                "transaction_date": dt
            })

        return {"rows": rows, "skipped": skipped}
