from sqlmodel import Session

from app.models.category import Category

# Categorias padrão criadas junto com cada workspace novo
DEFAULT_CATEGORIES = [
    {"name": "Alimentação", "color": "#f97316", "icon": "utensils"},
    {"name": "Mercado", "color": "#22c55e", "icon": "shopping-cart"},
    {"name": "Transporte", "color": "#3b82f6", "icon": "car"},
    {"name": "Moradia", "color": "#8b5cf6", "icon": "home"},
    {"name": "Saúde", "color": "#ef4444", "icon": "heart-pulse"},
    {"name": "Lazer", "color": "#ec4899", "icon": "gamepad-2"},
    {"name": "Educação", "color": "#eab308", "icon": "graduation-cap"},
    {"name": "Assinaturas", "color": "#06b6d4", "icon": "repeat"},
    {"name": "Outros", "color": "#64748b", "icon": "tag"},
]


def seed_default_categories(session: Session, workspace_id: int) -> None:
    """Cria as categorias padrão de um workspace recém-criado (não comita)."""
    for data in DEFAULT_CATEGORIES:
        session.add(Category(workspace_id=workspace_id, **data))
