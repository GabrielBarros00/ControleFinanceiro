from decimal import Decimal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from typing import List, Dict, Any, Optional
import io

from app.core.config import settings
from app.db.session import get_session
from app.domain.query_policy import workspace_base_currency
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
    SplitMethod,
)
from app.models.import_batch import (
    ImportBatch,
    ImportRow,
    ImportRowStatus,
    compute_fingerprint,
)
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.csv_parser import CSVParserService, CSVColumnMapping
from app.services.event_service import publish_event
from app.api.deps import require_role


def _mark_duplicates(session: Session, workspace_id: int, rows: List[Dict[str, Any]]) -> None:
    """Heurística de duplicata: mesma data (dia), valor e título (case-insensitive)
    de uma transação já existente no workspace."""
    if not rows:
        return
    # Só a JANELA de datas do arquivo. Antes carregava TODAS as transações vivas
    # do workspace em memória a cada parse: com anos de histórico e um CSV de
    # 5 MB, o pico crescia sem teto e a resposta ia junto.
    datas = [row["transaction_date"] for row in rows]
    inicio, fim = min(datas), max(datas)
    existing = session.exec(
        select(Transaction.transaction_date, Transaction.total_amount, Transaction.title)
        .where(Transaction.workspace_id == workspace_id)
        .where(Transaction.deleted_at.is_(None))
        .where(Transaction.transaction_date >= inicio)
        .where(Transaction.transaction_date <= fim)
    ).all()
    existing_keys = {
        (tx_date.date(), int(amount * 100), title.strip().lower())
        for tx_date, amount, title in existing
    }
    for row in rows:
        key = (
            row["transaction_date"].date(),
            int(row["total_amount"] * 100),
            row["title"].strip().lower(),
        )
        row["duplicate"] = key in existing_keys

router = APIRouter(prefix="/workspaces/{workspace_id}/imports", tags=["imports"])


@router.post("/parse", response_model=Dict[str, Any])
def parse_csv(
    workspace_id: int,
    file: UploadFile = File(...),
    date_column: str = Form(...),
    description_column: str = Form(...),
    amount_column: str = Form(...),
    date_format: str = Form("%Y-%m-%d"),
    delimiter: str = Form(","),
    decimal_separator: str = Form("."),
    invert_amount: bool = Form(True),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    mapping = CSVColumnMapping(
        date_column=date_column,
        description_column=description_column,
        amount_column=amount_column,
        date_format=date_format,
        delimiter=delimiter,
        decimal_separator=decimal_separator,
        invert_amount=invert_amount
    )

    # Limite de upload (lê no máximo limite+1 para detectar excesso sem carregar tudo)
    raw = file.file.read(settings.UPLOAD_MAX_BYTES + 1)
    if len(raw) > settings.UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite de {settings.UPLOAD_MAX_BYTES // (1024 * 1024)}MB"
        )

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Arquivo inválido: envie um CSV codificado em UTF-8"
        )
    file_obj = io.StringIO(content)

    result = CSVParserService.parse(file_obj, mapping)
    _mark_duplicates(session, workspace_id, result["rows"])
    return result


class CommitRow(BaseModel):
    line: Optional[int] = None
    title: str = "Imported Transaction"
    total_amount: Decimal
    transaction_date: datetime
    decision: str = "import"  # "import" | "ignore"


class CommitRequest(BaseModel):
    filename: Optional[str] = None
    # Teto de linhas: o corpo é JSON livre, então sem limite um cliente pede a
    # criação de milhões de transações numa única transação de banco
    rows: List[CommitRow] = Field(max_length=settings.IMPORT_MAX_ROWS)


@router.post("/commit", response_model=Dict[str, Any])
def commit_import(
    workspace_id: int,
    body: CommitRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Persiste um lote com DECISÃO por linha (importar/ignorar) e idempotência
    por fingerprint (ADR 0008): reimportar o mesmo arquivo não duplica."""
    # Moeda-base do workspace, não "BRL" fixo: com o literal, TODA linha
    # importada num workspace em outra moeda caía fora das agregações (que
    # filtram `currency == base`) e sumia sem aviso nenhum.
    base_currency = workspace_base_currency(session, workspace_id)
    batch = ImportBatch(
        workspace_id=workspace_id,
        filename=body.filename,
        created_by_user_id=membership.user_id,
        total_rows=len(body.rows),
    )
    session.add(batch)
    session.flush()

    # Fingerprints já importados neste workspace = fonte da idempotência
    seen = set(session.exec(
        select(ImportRow.fingerprint).where(
            ImportRow.workspace_id == workspace_id,
            ImportRow.status == ImportRowStatus.imported,
        )
    ).all())

    imported = ignored = duplicate = skipped = 0
    for row in body.rows:
        title = (row.title or "Imported Transaction").strip()[:200]
        fp = compute_fingerprint(workspace_id, row.transaction_date, row.total_amount, title)

        if row.decision == "ignore":
            status, reason, tx_id = ImportRowStatus.ignored, None, None
            ignored += 1
        elif row.total_amount <= 0:
            status, reason, tx_id = ImportRowStatus.skipped, "valor deve ser positivo", None
            skipped += 1
        elif fp in seen:
            status, reason, tx_id = ImportRowStatus.duplicate, "já importado anteriormente", None
            duplicate += 1
        else:
            tx = Transaction(
                title=title,
                total_amount=row.total_amount,
                transaction_date=row.transaction_date,
                billing_month=row.transaction_date.strftime("%Y-%m"),
                workspace_id=workspace_id,
                created_by_user_id=membership.user_id,
                currency=base_currency,
                status=TransactionStatus.confirmed,
            )
            session.add(tx)
            session.flush()
            session.add(TransactionPayer(
                transaction_id=tx.id, user_id=membership.user_id, amount=row.total_amount,
            ))
            session.add(TransactionSplit(
                transaction_id=tx.id, user_id=membership.user_id,
                split_method=SplitMethod.equal, input_value=Decimal("100"),
                computed_amount=row.total_amount,
            ))
            status, reason, tx_id = ImportRowStatus.imported, None, tx.id
            seen.add(fp)
            imported += 1

        session.add(ImportRow(
            batch_id=batch.id, workspace_id=workspace_id, line=row.line,
            title=title, amount=row.total_amount, transaction_date=row.transaction_date,
            fingerprint=fp, status=status, transaction_id=tx_id, reason=reason,
        ))

    batch.imported_count = imported
    batch.ignored_count = ignored
    batch.duplicate_count = duplicate
    batch.skipped_count = skipped
    session.add(batch)

    if imported:
        publish_event(session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id)
    session.commit()
    return {
        "batch_id": batch.id,
        "imported": imported,
        "ignored": ignored,
        "duplicate": duplicate,
        "skipped": skipped,
    }
