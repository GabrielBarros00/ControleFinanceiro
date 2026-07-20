"""Exporta o schema OpenAPI do app para o typegen do frontend.

Uso (da raiz do backend):
    python scripts/dump_openapi.py [saida.json]

O frontend consome via `npm run typegen` (gera src/types/api.gen.ts).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
output.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"OpenAPI schema escrito em {output} ({output.stat().st_size} bytes)")
