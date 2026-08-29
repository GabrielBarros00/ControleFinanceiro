"""Gera o par de chaves VAPID do Web Push (ADR 0033).

    cd backend && python scripts/gerar_vapid.py

Rode UMA vez por instalação e guarde a saída no `.env`. Girar a chave depois
INVALIDA todas as inscrições existentes — cada navegador precisa se reinscrever,
e ninguém recebe aviso no intervalo —, então não é operação de rotina.

A chave pública é o `applicationServerKey` que o navegador recebe; a privada
nunca sai do servidor.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.push_service import gerar_par_vapid  # noqa: E402


def main() -> None:
    publica, privada = gerar_par_vapid()
    print("# Aviso de vencimento (ADR 0033) — cole no .env")
    print(f"VAPID_PUBLIC_KEY={publica}")
    print(f"VAPID_PRIVATE_KEY={privada}")
    print("# Contato do responsável por esta origem (mailto: ou https:)")
    print("VAPID_SUBJECT=mailto:voce@seudominio.com")


if __name__ == "__main__":
    main()
