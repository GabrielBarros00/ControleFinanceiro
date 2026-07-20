from sqlmodel import Session, select
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole, role_level
from app.models.user import User


def test_create_workspace(db_session: Session):
    user = User(name="Owner", email="owner@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    workspace = Workspace(name="Minha Casa", created_by_user_id=user.id)
    db_session.add(workspace)
    db_session.commit()

    assert workspace.id is not None
    assert workspace.name == "Minha Casa"


def test_membership_role_default_is_member(db_session: Session):
    user = User(name="U", email="u@example.com", password_hash="hash")
    ws = Workspace(name="WS")
    db_session.add_all([user, ws])
    db_session.commit()

    membership = WorkspaceMembership(workspace_id=ws.id, user_id=user.id)
    db_session.add(membership)
    db_session.commit()
    db_session.refresh(membership)

    assert membership.role == WorkspaceRole.member


def test_role_hierarchy_levels():
    assert role_level(WorkspaceRole.viewer) < role_level(WorkspaceRole.member)
    assert role_level(WorkspaceRole.member) < role_level(WorkspaceRole.admin)
    assert role_level(WorkspaceRole.admin) < role_level(WorkspaceRole.owner)
    # Aceita strings vindas do banco
    assert role_level("owner") == role_level(WorkspaceRole.owner)
    assert role_level("desconhecido") == -1


def test_workspace_isolation_memberships(db_session: Session):
    u1 = User(name="U1", email="u1@iso.com", password_hash="hash")
    u2 = User(name="U2", email="u2@iso.com", password_hash="hash")
    ws1 = Workspace(name="WS 1")
    ws2 = Workspace(name="WS 2")
    db_session.add_all([u1, u2, ws1, ws2])
    db_session.commit()

    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role=WorkspaceRole.owner))
    db_session.commit()

    ws2_members = db_session.exec(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws2.id)
    ).all()
    assert len(ws2_members) == 0
