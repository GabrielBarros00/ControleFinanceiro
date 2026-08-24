"""Contrato tipado da importação de CSV (ADR 0008).

`use-imports.ts` mantinha SETE interfaces escritas à mão para estas duas rotas, e
duas delas já divergiam entre si sobre o mesmo campo do mesmo fluxo
(`ParsedCsvRow.total_amount: string` × `CommitRow.total_amount: string | number`).
Nada acusava, porque a rota não declarava tipo nenhum.

**Nenhuma linha some em silêncio** é a regra do ADR 0008, e ela aparece no
formato: toda linha recusada vai para `skipped` com o número da linha e o motivo
em PT-BR, e o commit devolve a contagem de cada desfecho — importada, ignorada
por decisão, duplicata e inválida.
"""
from datetime import datetime
from decimal import Decimal
from typing import List

from pydantic import BaseModel


class ParsedCsvRow(BaseModel):
    """Uma linha que o parser entendeu, pronta para a decisão do usuário."""
    #: Número da linha no arquivo (o cabeçalho é a 1; dados começam na 2).
    line: int
    title: str
    total_amount: Decimal
    #: Ancorado ao meio-dia local (`civil_instant`, ADR 0025): a coluna de data
    #: de um extrato é um DIA de calendário, e meia-noite em UTC volta um dia em
    #: todo fuso negativo — a linha do dia 1º caía na competência anterior.
    transaction_date: datetime
    #: Já existe um lançamento com o mesmo fingerprint (ADR 0008).
    duplicate: bool = False


class SkippedCsvRow(BaseModel):
    """Linha que o parser recusou — com o porquê, em PT-BR."""
    line: int
    reason: str


class ParseCsvResult(BaseModel):
    rows: List[ParsedCsvRow] = []
    skipped: List[SkippedCsvRow] = []


class CommitImportResult(BaseModel):
    """O desfecho de cada linha do lote — a soma tem de bater com o enviado."""
    #: Lote auditável: `ImportRow` guarda linha a linha o que aconteceu.
    batch_id: int
    imported: int
    #: Recusadas pelo próprio usuário (`decision: "ignore"`).
    ignored: int
    #: Barradas pelo fingerprint — reimportar o mesmo arquivo não duplica.
    duplicate: int
    #: Inválidas (data/valor que o commit não conseguiu aproveitar).
    skipped: int


class BulkSkippedDetail(BaseModel):
    index: int
    title: str
    reason: str


class BulkImportResult(BaseModel):
    """Criação em lote sem lote auditável — o caminho antigo, ainda usado pela
    tela de importar quando não se quer registrar o batch."""
    status: str
    created: int
    skipped: int
    skipped_details: List[BulkSkippedDetail] = []
