"""Métricas da tela de Admin (ADR 0026).

**A regra deste módulo, e a razão de ele existir separado das rotas: só sai
daqui contagem, tamanho e data.** Nenhuma função devolve valor de lançamento,
saldo, limite de cartão, salário ou nome de categoria de outra pessoa.

Isso não é excesso de zelo — é o que mantém de pé os ADRs 0018 e 0021, que
custaram um programa de seis ondas. Um administrador precisa saber *quanto
espaço* alguém ocupa e *quantos* lançamentos existem para operar o servidor;
precisar saber *o que* a pessoa gastou nunca foi requisito de operação. A
diferença entre `COUNT(*)` e `SUM(amount)` é exatamente a diferença entre
administrar o site e ler a vida financeira de quem o usa.

Quem revisar este arquivo no futuro: se aparecer aqui um `func.sum` sobre uma
coluna de dinheiro, é regressão — não otimização.
"""
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlmodel import Session, func, select

from app.models.attachment import Attachment
from app.models.audit import ActionType, AuditLog
from app.models.exchange_rate import ExchangeRate
from app.models.refresh_session import RefreshSession
from app.models.registration_invite import RegistrationInvite
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import InviteStatus, Workspace, WorkspaceMembership


def _aware(momento: Optional[datetime]) -> Optional[datetime]:
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def visao_geral(db: Session) -> Dict[str, Any]:
    """Os números do topo da tela de Admin."""
    agora = datetime.now(UTC)
    ha_30_dias = agora - timedelta(days=30)

    usuarios_total = db.exec(
        select(func.count(User.id)).where(User.deleted_at.is_(None))
    ).one()
    usuarios_ativos = db.exec(
        select(func.count(User.id)).where(
            User.deleted_at.is_(None), User.is_active.is_(True)
        )
    ).one()
    usuarios_novos_30d = db.exec(
        select(func.count(User.id)).where(
            User.deleted_at.is_(None), User.created_at >= ha_30_dias
        )
    ).one()

    workspaces = db.exec(
        select(func.count(Workspace.id)).where(Workspace.deleted_at.is_(None))
    ).one()
    # Lançamentos: a CONTAGEM. Ver o cabeçalho deste módulo.
    lancamentos = db.exec(
        select(func.count(Transaction.id)).where(Transaction.deleted_at.is_(None))
    ).one()

    anexos_bytes = db.exec(
        select(func.coalesce(func.sum(Attachment.size_bytes), 0))
    ).one()
    anexos_qtd = db.exec(select(func.count(Attachment.id))).one()

    convites_pendentes = db.exec(
        select(func.count(RegistrationInvite.id)).where(
            RegistrationInvite.status == InviteStatus.pending,
            RegistrationInvite.expires_at >= agora,
        )
    ).one()

    sessoes_vivas = db.exec(
        select(func.count(RefreshSession.id)).where(
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at >= agora,
        )
    ).one()

    return {
        "usuarios_total": usuarios_total,
        "usuarios_ativos": usuarios_ativos,
        "usuarios_novos_30d": usuarios_novos_30d,
        "workspaces": workspaces,
        "lancamentos": lancamentos,
        "anexos_bytes": anexos_bytes,
        "anexos_qtd": anexos_qtd,
        "convites_pendentes": convites_pendentes,
        "sessoes_vivas": sessoes_vivas,
        "banco_bytes": tamanho_do_banco(db),
    }


def tamanho_do_banco(db: Session) -> Optional[int]:
    """Tamanho do banco em bytes, ou `None` quando o motor não sabe responder.

    `None` em vez de zero de propósito: zero é um tamanho, e a tela mostraria
    "0 B" como se o banco estivesse vazio. `None` vira "—", que é a verdade.
    """
    try:
        if db.get_bind().dialect.name == "postgresql":
            return db.exec(text("SELECT pg_database_size(current_database())")).one()[0]
        # SQLite: páginas × tamanho da página.
        paginas = db.exec(text("PRAGMA page_count")).one()[0]
        tamanho = db.exec(text("PRAGMA page_size")).one()[0]
        return int(paginas) * int(tamanho)
    except Exception:
        return None


def _ultimo_login_por_usuario(db: Session, ids: List[int]) -> Dict[int, datetime]:
    """Último login de cada usuário, em UMA consulta.

    Feito em lote porque a alternativa — uma consulta por linha da tabela — é o
    N+1 clássico: com 50 usuários na tela seriam 51 idas ao banco, e a página de
    administração ficaria mais cara que qualquer tela do produto.
    """
    if not ids:
        return {}
    linhas = db.exec(
        select(AuditLog.user_id, func.max(AuditLog.created_at))
        .where(AuditLog.action == ActionType.login, AuditLog.user_id.in_(ids))
        .group_by(AuditLog.user_id)
    ).all()
    return {uid: quando for uid, quando in linhas if uid is not None}


def _contagem_por_usuario(db: Session, ids: List[int]) -> Dict[str, Dict[int, int]]:
    """Workspaces, lançamentos e bytes de anexo por usuário, em três consultas."""
    if not ids:
        return {"workspaces": {}, "lancamentos": {}, "anexos_bytes": {}}

    workspaces = dict(db.exec(
        select(WorkspaceMembership.user_id, func.count(WorkspaceMembership.id))
        .where(WorkspaceMembership.user_id.in_(ids))
        .group_by(WorkspaceMembership.user_id)
    ).all())

    # Lançamentos que a pessoa CRIOU. Não é "lançamentos que a envolvem" — essa
    # pergunta exigiria atravessar splits e pagadores, que é caminho de dado
    # financeiro. Para operar o servidor, autoria basta.
    lancamentos = dict(db.exec(
        select(Transaction.created_by_user_id, func.count(Transaction.id))
        .where(
            Transaction.created_by_user_id.in_(ids),
            Transaction.deleted_at.is_(None),
        )
        .group_by(Transaction.created_by_user_id)
    ).all())

    anexos = dict(db.exec(
        select(Attachment.uploaded_by_user_id, func.coalesce(func.sum(Attachment.size_bytes), 0))
        .where(Attachment.uploaded_by_user_id.in_(ids))
        .group_by(Attachment.uploaded_by_user_id)
    ).all())

    return {"workspaces": workspaces, "lancamentos": lancamentos, "anexos_bytes": anexos}


def lista_de_usuarios(
    db: Session,
    busca: Optional[str] = None,
    incluir_removidos: bool = False,
    limite: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Página da lista de usuários, com o uso de cada um."""
    condicoes = []
    if not incluir_removidos:
        condicoes.append(User.deleted_at.is_(None))
    if busca:
        # `ilike` e não `like`: no Postgres `like` é sensível a maiúsculas, e a
        # busca por "Gabriel" não acharia "gabriel@..." — um filtro que mente
        # sobre não haver resultado é pior que não ter filtro.
        alvo = f"%{busca.strip()}%"
        condicoes.append(User.name.ilike(alvo) | User.email.ilike(alvo))

    total = db.exec(select(func.count(User.id)).where(*condicoes)).one()
    usuarios = db.exec(
        select(User)
        .where(*condicoes)
        .order_by(User.created_at.desc())
        .limit(limite)
        .offset(offset)
    ).all()

    ids = [u.id for u in usuarios]
    ultimo_login = _ultimo_login_por_usuario(db, ids)
    contagens = _contagem_por_usuario(db, ids)

    itens = [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "is_active": u.is_active,
            "platform_role": u.platform_role,
            "created_at": u.created_at,
            "deleted_at": u.deleted_at,
            "needs_onboarding": u.needs_onboarding,
            "last_login_at": _aware(ultimo_login.get(u.id)),
            "workspaces": contagens["workspaces"].get(u.id, 0),
            "lancamentos": contagens["lancamentos"].get(u.id, 0),
            "anexos_bytes": contagens["anexos_bytes"].get(u.id, 0),
        }
        for u in usuarios
    ]
    return {"total": total, "items": itens, "limit": limite, "offset": offset}


def saude(db: Session) -> Dict[str, Any]:
    """Sinais operacionais: o que o `cron` do Compose deveria estar mantendo.

    O frescor do câmbio é o item que importa aqui. O serviço `cron` roda
    `backfill_rates.py` de hora em hora, e se ele morrer nada quebra na hora — o
    store simplesmente para de crescer, e as recorrências em moeda estrangeira
    deixam de materializar em silêncio. Sem esta tela, o sintoma apareceria como
    "um lançamento que não nasceu", semanas depois.
    """
    ultima_cotacao = db.exec(
        select(func.max(ExchangeRate.rate_date))
    ).one()
    cotacoes = db.exec(select(func.count(ExchangeRate.id))).one()

    agora = datetime.now(UTC)
    sessoes_expiradas = db.exec(
        select(func.count(RefreshSession.id)).where(RefreshSession.expires_at < agora)
    ).one()
    auditoria_linhas = db.exec(select(func.count(AuditLog.id))).one()
    auditoria_mais_antiga = db.exec(select(func.min(AuditLog.created_at))).one()

    return {
        "cambio_ultima_data": ultima_cotacao,
        "cambio_cotacoes": cotacoes,
        "banco_bytes": tamanho_do_banco(db),
        "anexos_bytes": db.exec(
            select(func.coalesce(func.sum(Attachment.size_bytes), 0))
        ).one(),
        "sessoes_expiradas_pendentes_de_expurgo": sessoes_expiradas,
        "auditoria_linhas": auditoria_linhas,
        "auditoria_mais_antiga": _aware(auditoria_mais_antiga),
    }
