"""Importação de EXTRATO DE CONTA (ADR 0037): pessoal, como a conta.

A importação de despesas de um espaço continua em `/workspaces/{id}/imports`
(ADR 0008). Esta lê o extrato de UMA conta da pessoa com o sinal preservado e
grava cada linha como o que ela é: despesa (num espaço), renda, transferência ou
pagamento de fatura. A regra mora em `services/commands/account_imports.py`.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.imports import (
    AccountCommitRequest,
    AccountCommitResult,
    AccountImportBatchDetail,
    AccountImportBatchRead,
    AccountParseResult,
    AccountUndoResult,
    UndoImportRequest,
)
from app.services import app_settings
from app.services.attachment_storage import free_keys
from app.services.commands import account_imports as cmd
from app.services.csv_parser import CSVColumnMapping

router = APIRouter(prefix="/me/imports", tags=["imports"])


@router.post("/parse", response_model=AccountParseResult)
def parse_account_statement(
    account_id: int = Form(...),
    file: UploadFile = File(...),
    date_column: str = Form(...),
    description_column: str = Form(...),
    amount_column: str = Form(...),
    date_format: str = Form("%Y-%m-%d"),
    delimiter: str = Form(","),
    decimal_separator: str = Form("."),
    id_column: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Lê o extrato com o sinal (entrou/saiu) e sugere a classificação de cada linha."""
    teto = app_settings.get(session, "upload_max_bytes")
    bruto = file.file.read(teto + 1)
    if len(bruto) > teto:
        raise HTTPException(status_code=413, detail=f"Arquivo excede o limite de {teto // (1024 * 1024)}MB")
    try:
        conteudo = bruto.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Arquivo inválido: envie um CSV codificado em UTF-8")
    mapping = CSVColumnMapping(
        date_column=date_column, description_column=description_column, amount_column=amount_column,
        date_format=date_format, delimiter=delimiter, decimal_separator=decimal_separator,
        keep_sign=True, id_column=id_column or None,
    )
    return cmd.parse_account_statement(session, user.id, account_id, conteudo, mapping)


@router.post("/commit", response_model=AccountCommitResult)
def commit_account_statement(
    body: AccountCommitRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Grava o extrato com a decisão de cada linha (ADR 0037)."""
    resultado = cmd.commit_account_statement(session, user.id, body)
    session.commit()
    return resultado


@router.get("", response_model=List[AccountImportBatchRead])
@router.get("/", response_model=List[AccountImportBatchRead], include_in_schema=False)
def list_account_imports(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return cmd.list_account_imports(session, user.id)


@router.get("/{batch_id}", response_model=AccountImportBatchDetail)
def get_account_import(
    batch_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return cmd.get_account_import(session, user.id, batch_id)


@router.post("/{batch_id}/undo", response_model=AccountUndoResult)
def undo_account_import(
    batch_id: int,
    body: UndoImportRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Desfaz o extrato: exclui ou estorna o que ele criou (tudo ou nada)."""
    resultado, liberar = cmd.undo_account_import(
        session, user.id, batch_id, confirm_attachments=body.confirm_attachments,
    )
    session.commit()
    free_keys(liberar)
    return resultado
