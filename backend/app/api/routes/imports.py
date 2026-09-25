from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlmodel import Session
import io

from app.db.session import get_session
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.schemas.imports import (
    CommitImportResult,
    CommitRequest,
    CommitRow,
    ImportBatchDetail,
    ImportBatchRead,
    ParseCsvResult,
    UndoImportRequest,
    UndoImportResult,
)
from app.services import app_settings
from app.services.csv_parser import CSVParserService, CSVColumnMapping
from app.api.deps import get_workspace_membership, require_role
from app.services.attachment_storage import free_keys
from app.services.commands import imports as imp_cmd
from app.services.commands.imports import _mark_duplicates

router = APIRouter(prefix="/workspaces/{workspace_id}/imports", tags=["imports"])

# `CommitRequest`/`CommitRow` moram em `schemas/imports.py`; o nome continua
# importável daqui para quem já o importava.
__all__ = ["CommitRequest", "CommitRow", "router"]


@router.post("/parse", response_model=ParseCsvResult)
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

    # Limite de upload (lê no máximo limite+1 para detectar excesso sem carregar
    # tudo). Configurável em runtime pela tela de Admin (ADR 0026).
    teto_upload = app_settings.get(session, "upload_max_bytes")
    raw = file.file.read(teto_upload + 1)
    if len(raw) > teto_upload:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite de {teto_upload // (1024 * 1024)}MB"
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


@router.post("/commit", response_model=CommitImportResult)
def commit_import(
    workspace_id: int,
    body: CommitRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Persiste um lote com DECISÃO por linha (importar/ignorar) e idempotência
    por fingerprint (ADR 0008): reimportar o mesmo arquivo não duplica."""
    resultado = imp_cmd.commit_import(session, workspace_id, body, membership)
    session.commit()
    return resultado


@router.get("", response_model=List[ImportBatchRead])
@router.get("/", response_model=List[ImportBatchRead], include_in_schema=False)
def list_imports(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """As importações da pessoa neste espaço (ADR 0036)."""
    return imp_cmd.list_batches(session, workspace_id, membership)


@router.get("/{batch_id}", response_model=ImportBatchDetail)
def get_import(
    workspace_id: int,
    batch_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return imp_cmd.get_batch(session, workspace_id, batch_id, membership)


@router.post("/{batch_id}/undo", response_model=UndoImportResult)
def undo_import(
    workspace_id: int,
    batch_id: int,
    body: UndoImportRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Exclui os lançamentos que a importação criou (tudo ou nada, ADR 0036)."""
    resultado, liberar = imp_cmd.undo_batch(
        session, workspace_id, batch_id, membership, confirm_attachments=body.confirm_attachments,
    )
    session.commit()
    free_keys(liberar)
    return resultado
