"""O registry de models tem de ficar completo com UM import qualquer.

Os `Relationship` referenciam as classes por nome (string) e o SQLAlchemy resolve
esses nomes configurando TODOS os mappers do registry na primeira query. Um
entrypoint que importe só parte dos models (os scripts de cron) morre com
`InvalidRequestError: expression 'RecurringExpense' failed to locate a name`
numa query que não tem nada a ver com recorrência. Por isso a lista única em
`app/models/__init__.py` — e por isso estes dois testes.
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BACKEND_DIR / "app" / "models"


def test_init_importa_todos_os_modulos_de_model():
    """Model novo esquecido fora do __init__.py falha aqui, não no cron."""
    from app import models  # noqa: F401  (garante o import do pacote)

    no_disco = {p.stem for p in MODELS_DIR.glob("*.py") if p.stem != "__init__"}
    carregados = {
        nome.split(".")[-1] for nome in sys.modules if nome.startswith("app.models.")
    }
    assert no_disco - carregados == set(), (
        "models fora da lista de app/models/__init__.py: "
        f"{sorted(no_disco - carregados)}"
    )


def test_entrypoint_minimo_configura_os_mappers():
    """Simula um script de cron: processo novo, importando pouca coisa.

    Precisa de subprocesso — dentro da suíte o conftest já importou tudo, então
    o cenário do bug não é reproduzível no processo atual.
    """
    codigo = (
        "import sys; sys.path.insert(0, %r)\n"
        "from sqlalchemy.orm import configure_mappers\n"
        "from app.services.exchange_rate_store import ExchangeRateStore  # noqa: F401\n"
        "from app.models.exchange_rate import ExchangeRate  # noqa: F401\n"
        "configure_mappers()\n"
    ) % str(BACKEND_DIR)

    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "SECRET_KEY": "x" * 32,
    }
    proc = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
