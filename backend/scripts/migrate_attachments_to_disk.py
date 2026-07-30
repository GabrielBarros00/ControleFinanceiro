"""Move o conteúdo dos anexos do banco para o armazenamento em disco (ADR 0007).

A migração de schema (`e3f9a17c4b28`) adiciona `attachment.storage_key` e torna
`attachment.data` nullable, mas NÃO move os bytes: fazer isso dentro de uma
migração Alembic significaria escrever no sistema de arquivos a partir de um
DDL — se o volume não estivesse montado, o upgrade destruiria recibos sem volta.
Aqui é um passo explícito, verificável e repetível.

Enquanto uma linha ainda tiver `data`, o download continua servindo do banco
(fallback em `routes/attachments.read_attachment_bytes`), então rodar isto não
tem janela de indisponibilidade.

Uso (da raiz do backend, com o .env carregado):
    python scripts/migrate_attachments_to_disk.py --dry-run
    python scripts/migrate_attachments_to_disk.py
    python scripts/migrate_attachments_to_disk.py --lote 200

Ao terminar com "0 pendentes", a coluna `data` pode ser dropada por uma migração
de limpeza — só então, e nunca antes.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.engine import engine  # noqa: E402

# Um import de model registra TODOS (ver app/models/__init__.py): `attachment` tem
# FK para `transaction`, `workspace` e `user`, resolvidas só no flush.
from app.models.attachment import Attachment  # noqa: E402
from app.services.attachment_storage import (  # noqa: E402
    AttachmentStorage,
    AttachmentStorageError,
)

LOTE_PADRAO = 100


def _arg(nome: str, padrao: int) -> int:
    if nome not in sys.argv:
        return padrao
    try:
        return int(sys.argv[sys.argv.index(nome) + 1])
    except (IndexError, ValueError):
        return padrao


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    lote = _arg("--lote", LOTE_PADRAO)

    print(f"Armazenamento: {AttachmentStorage.root()}")
    print(f"Banco:         {settings.DATABASE_URL.split('@')[-1]}")
    if dry_run:
        print("MODO DRY-RUN — nada será gravado.\n")

    movidos = corrigidos = falhas = 0
    with Session(engine) as session:
        pendentes = session.exec(
            select(Attachment).where(Attachment.data.is_not(None))
        ).all()
        print(f"{len(pendentes)} anexo(s) com conteúdo no banco.\n")

        for i, anexo in enumerate(pendentes, start=1):
            dados = anexo.data
            if not dados:
                continue

            # Recalcula o hash em vez de confiar no gravado: a chave de
            # armazenamento é o próprio conteúdo, e um sha divergente (linha
            # antiga, antes do SEC-003) apontaria para o objeto errado.
            digest = hashlib.sha256(dados).hexdigest()
            if anexo.sha256 and anexo.sha256 != digest:
                print(f"  [{anexo.id}] sha256 divergente no banco — corrigido")
                corrigidos += 1

            if dry_run:
                movidos += 1
                continue

            try:
                chave = AttachmentStorage.save(anexo.workspace_id, digest, dados)
            except AttachmentStorageError as exc:
                print(f"  [{anexo.id}] FALHA ao gravar: {exc}")
                falhas += 1
                continue

            # Confere o que foi escrito ANTES de largar os bytes do banco: este
            # é o único ponto sem volta do processo.
            gravado = AttachmentStorage.read(chave)
            if gravado is None or hashlib.sha256(gravado).hexdigest() != digest:
                print(f"  [{anexo.id}] FALHA na verificação pós-escrita — mantido no banco")
                falhas += 1
                continue

            anexo.storage_key = chave
            anexo.sha256 = digest
            anexo.data = None
            session.add(anexo)
            movidos += 1

            if i % lote == 0:
                session.commit()
                print(f"  ... {i}/{len(pendentes)}")

        if not dry_run:
            session.commit()

        restantes = session.exec(
            select(Attachment).where(Attachment.data.is_not(None))
        ).all()

    print(
        f"\n{'Seriam movidos' if dry_run else 'Movidos'}: {movidos} | "
        f"sha corrigido: {corrigidos} | falhas: {falhas} | pendentes: {len(restantes)}"
    )
    if falhas:
        print("Há falhas: os anexos correspondentes seguem servindo do banco.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
