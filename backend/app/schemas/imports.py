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
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.import_batch import ImportRowStatus


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


# Entrada do `/commit`. Morava em `api/routes/imports.py` até o ADR 0035 (o
# comando é compartilhado com o MCP e um serviço não importa de rota).
class CommitRow(BaseModel):
    line: Optional[int] = None
    title: str = "Imported Transaction"
    total_amount: Decimal
    transaction_date: datetime
    decision: str = "import"  # "import" | "ignore"


class CommitRequest(BaseModel):
    filename: Optional[str] = None
    # DOIS tetos, e a diferença entre eles importa.
    #
    # Este, declarativo, é a defesa contra abuso: o corpo é JSON livre, e o
    # Pydantic checa o COMPRIMENTO da lista antes de construir os itens — um
    # corpo com dez milhões de linhas é recusado sem que dez milhões de
    # `CommitRow` cheguem a existir na memória. Ele vem do ambiente e é o teto
    # absoluto, porque afrouxá-lo pela tela seria entregar ao próprio operador um
    # jeito de derrubar o processo.
    #
    # O outro, operacional e configurável em runtime (`import_max_rows`, ADR
    # 0026), é checado no handler e serve para o admin apertar o limite abaixo
    # deste — nunca acima; `app_settings` recusa valor maior.
    rows: List[CommitRow] = Field(max_length=settings.IMPORT_MAX_ROWS)


# --- Histórico e desfazer (ADR 0036) -----------------------------------------------------

class ImportBatchRead(BaseModel):
    """Uma importação da pessoa, com quanto dela ainda está no app."""
    id: int
    filename: Optional[str] = None
    created_at: datetime
    total_rows: int
    imported: int
    ignored: int
    duplicate: int
    skipped: int
    #: Lançamentos criados por ela que ainda existem. 0 com `imported` > 0 =
    #: desfeita (ou todos excluídos um a um).
    live_transactions: int
    #: Recibos anexados a esses lançamentos — apagados para sempre se desfizer.
    attachments: int


class ImportRowRead(BaseModel):
    line: Optional[int] = None
    title: str
    amount: Decimal
    transaction_date: datetime
    status: ImportRowStatus
    reason: Optional[str] = None
    transaction_id: Optional[int] = None
    #: O lançamento que a linha criou ainda existe.
    transaction_alive: bool


class ImportBatchDetail(ImportBatchRead):
    rows: List[ImportRowRead] = []


class UndoImportRequest(BaseModel):
    #: Com anexo, o desfazer apaga os recibos para sempre: só com esta confirmação.
    confirm_attachments: bool = False


class UndoImportResult(BaseModel):
    batch_id: int
    deleted: int
    attachments_removed: int


# --- Extrato de CONTA: entradas, transferências e pagamento de fatura (ADR 0037) -------

Direction = Literal["in", "out"]
Classification = Literal["expense", "income", "transfer", "statement_payment"]


class AccountParsedRow(BaseModel):
    """Uma linha do extrato, com o sinal preservado em `direction` e o palpite."""
    line: int
    title: str
    #: Sempre positivo; o sentido está em `direction`.
    total_amount: Decimal
    transaction_date: datetime
    direction: Direction
    external_id: Optional[str] = None
    #: Já importada antes e o que ela criou ainda existe (ADR 0036/0037).
    duplicate: bool = False
    #: Palpite (`app/domain/classificacao_de_extrato.py`); a pessoa confirma.
    suggested_classification: Classification
    suggested_card_id: Optional[int] = None
    suggested_account_id: Optional[int] = None


class AccountParseResult(BaseModel):
    account_id: int
    currency: str
    rows: List[AccountParsedRow] = []
    skipped: List[SkippedCsvRow] = []


class AccountCommitRow(BaseModel):
    """A decisão da pessoa sobre uma linha do extrato."""
    line: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    total_amount: Decimal = Field(gt=0)
    transaction_date: datetime
    direction: Direction
    external_id: Optional[str] = Field(default=None, max_length=120)
    decision: Literal["import", "ignore"] = "import"
    #: Omitida: saiu é despesa, entrou é renda.
    classification: Optional[Classification] = None
    #: Despesa: em qual espaço ela entra, e a categoria (do espaço).
    space_id: Optional[int] = None
    category_id: Optional[int] = None
    #: Renda: a categoria livre da renda ("Salário", "Freela").
    income_category: Optional[str] = Field(default=None, max_length=120)
    #: Transferência: a OUTRA conta (sua). Saiu = para ela; entrou = dela.
    counterpart_account_id: Optional[int] = None
    #: Pagamento de fatura: o cartão (seu). A fatura é a que o pagamento quita.
    card_id: Optional[int] = None


class AccountCommitRequest(BaseModel):
    account_id: int
    filename: Optional[str] = None
    rows: List[AccountCommitRow] = Field(max_length=settings.IMPORT_MAX_ROWS)


class AccountCommitResult(BaseModel):
    batch_id: int
    imported: int
    ignored: int
    duplicate: int
    skipped: int
    #: Quantas de cada tipo entraram.
    by_classification: Dict[str, int] = {}
    #: As que não entraram por um motivo (ADR 0008: nenhuma some calada).
    problems: List[SkippedCsvRow] = []


class AccountImportBatchRead(BaseModel):
    """Uma importação de extrato da pessoa, com quanto dela ainda existe."""
    id: int
    account_id: int
    account_name: str
    filename: Optional[str] = None
    created_at: datetime
    total_rows: int
    imported: int
    ignored: int
    duplicate: int
    skipped: int
    live: int
    attachments: int


class AccountImportRowRead(BaseModel):
    line: Optional[int] = None
    title: str
    amount: Decimal
    transaction_date: datetime
    direction: Optional[Direction] = None
    classification: Optional[Classification] = None
    status: ImportRowStatus
    reason: Optional[str] = None
    external_id: Optional[str] = None
    alive: bool


class AccountImportBatchDetail(AccountImportBatchRead):
    rows: List[AccountImportRowRead] = []


class AccountUndoResult(BaseModel):
    batch_id: int
    #: Quanto de cada tipo saiu (despesa excluída, renda excluída, transferência
    #: excluída, pagamento estornado).
    undone: Dict[str, int] = {}
    attachments_removed: int
