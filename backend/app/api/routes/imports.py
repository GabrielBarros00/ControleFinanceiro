from decimal import Decimal
from datetime import datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from typing import List, Dict, Any, Optional
import io

from app.core.config import settings
from app.db.session import get_session
from app.domain.dates import civil_instant, local_day, month_key_local
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
from app.services import app_settings
from app.services.csv_parser import CSVParserService, CSVColumnMapping
from app.services.event_service import publish_event
from app.api.deps import require_role


def _ancora_data_civil(quando: datetime) -> datetime:
    """Meia-noite cravada num payload de import É uma data civil — ancora.

    O caminho normal já chega ancorado, porque `/parse` o faz na leitura do CSV.
    Mas `/commit` aceita as linhas do CLIENTE, e um script que monte o corpo à
    mão manda `2026-08-01T00:00:00` — a data que o extrato do banco mostra, sem
    hora nenhuma. Sem esta rede, essa linha nasceria com competência de julho,
    que é exatamente o defeito que o `csv_parser` deixou de produzir.

    Um instante genuíno passa intacto: só 00:00:00 exato é tratado como data.
    """
    if quando.time() == time.min:
        return civil_instant(local_day(quando.date()))
    return quando


def _mark_duplicates(session: Session, workspace_id: int, rows: List[Dict[str, Any]]) -> None:
    """Heurística de duplicata: mesma data (dia), valor e título (case-insensitive)
    de uma transação já existente no workspace."""
    if not rows:
        return
    # Só a JANELA de datas do arquivo. Antes carregava TODAS as transações vivas
    # do workspace em memória a cada parse: com anos de histórico e um CSV de
    # 5 MB, o pico crescia sem teto e a resposta ia junto.
    #
    # A janela é por DIA CIVIL, com um dia de folga de cada lado. A comparação é
    # entre um dia de calendário (a linha do CSV) e um INSTANTE (a coluna), e os
    # dois só coincidem no meio: uma compra das 22h do dia 31 está gravada em
    # 01/08 01:00Z, e uma compra ancorada ao meio-dia local está em 15:00Z. Sem a
    # folga, a janela recortada nos extremos crus do arquivo deixava de fora
    # justamente os lançamentos do primeiro e do último dia — e o import os
    # reimportava como se fossem novos.
    datas = [local_day(row["transaction_date"]) for row in rows]
    inicio = datetime.combine(min(datas) - timedelta(days=1), time.min)
    fim = datetime.combine(max(datas) + timedelta(days=1), time.max)
    existing = session.exec(
        select(Transaction.transaction_date, Transaction.total_amount, Transaction.title)
        .where(Transaction.workspace_id == workspace_id)
        .where(Transaction.deleted_at.is_(None))
        .where(Transaction.transaction_date >= inicio)
        .where(Transaction.transaction_date <= fim)
    ).all()
    existing_keys = {
        (local_day(tx_date), int(amount * 100), title.strip().lower())
        for tx_date, amount, title in existing
    }
    for row in rows:
        key = (
            local_day(row["transaction_date"]),
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


@router.post("/commit", response_model=Dict[str, Any])
def commit_import(
    workspace_id: int,
    body: CommitRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Persiste um lote com DECISÃO por linha (importar/ignorar) e idempotência
    por fingerprint (ADR 0008): reimportar o mesmo arquivo não duplica."""
    # Teto operacional (ver o comentário em CommitRequest.rows). O declarativo já
    # barrou o abuso; este é o número que o admin escolheu.
    teto_linhas = app_settings.get(session, "import_max_rows")
    if len(body.rows) > teto_linhas:
        raise HTTPException(
            status_code=422,
            detail=f"Importação limitada a {teto_linhas} linhas por lote",
        )
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
        quando = _ancora_data_civil(row.transaction_date)
        fp = compute_fingerprint(workspace_id, quando, row.total_amount, title)

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
                transaction_date=quando,
                # `month_key_local` agora que a data do CSV chega ancorada ao
                # meio-dia local (`csv_parser`), e não mais como meia-noite UTC.
                # Enquanto era meia-noite, `strftime` era o único jeito de não
                # jogar "01/03" para fevereiro; com um instante de verdade, ler o
                # mês em UTC é que erraria — e a competência tem de ser a mesma
                # que o extrato e o caixa enxergam.
                billing_month=month_key_local(quando),
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
            title=title, amount=row.total_amount, transaction_date=quando,
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
