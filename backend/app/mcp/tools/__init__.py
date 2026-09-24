"""As tools do servidor MCP. A ORDEM de importação é a ordem do `tools/list`
(determinística, como a spec pede): perfil, descoberta, consultas, prévias e,
por último, as escritas — agrupadas pelo escopo que exigem."""
from app.mcp.tools import profile  # noqa: F401
from app.mcp.tools import catalog  # noqa: F401
from app.mcp.tools import transactions  # noqa: F401
from app.mcp.tools import statements  # noqa: F401
from app.mcp.tools import reports  # noqa: F401
from app.mcp.tools import obligations  # noqa: F401
from app.mcp.tools import transactions_write  # noqa: F401
from app.mcp.tools import bulk  # noqa: F401
from app.mcp.tools import imports  # noqa: F401
from app.mcp.tools import accounts_write  # noqa: F401
from app.mcp.tools import income_write  # noqa: F401
from app.mcp.tools import settlements_write  # noqa: F401
from app.mcp.tools import planning_write  # noqa: F401
from app.mcp.tools import attachments  # noqa: F401
