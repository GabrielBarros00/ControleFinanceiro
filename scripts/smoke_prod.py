"""Smoke test de produção: exercita a jornada completa contra o stack rodando.

Uso:
    python scripts/smoke_prod.py                     # http://localhost:8890
    SMOKE_BASE_URL=https://meuapp.com python scripts/smoke_prod.py

Valida o deploy real (nginx + backend em modo production + Postgres):
auth, onboarding, categorias, transações com split, convites, dívidas,
recorrência, financiamento, orçamento, rendas, faturas, validações de
borda, rate limit e SPA. Sai com código != 0 se qualquer passo falhar.
"""
import os
import sys
import time

import httpx

BASE = os.environ.get("SMOKE_BASE_URL", "http://localhost:8890").rstrip("/")
API = f"{BASE}/api/v1"

# PNG válido pelos magic bytes — o upload valida o CONTEÚDO, não só o Content-Type
PNG_MINIMO = b"\x89PNG\r\n\x1a\n" + b"recibo-do-smoke-test" * 8

_passed = 0


def check(name: str, condition: bool, detail: str = ""):
    global _passed
    if condition:
        _passed += 1
        print(f"  ok  {name}")
    else:
        print(f" FAIL {name} {detail}")
        sys.exit(1)


class Session:
    """Cookies manuais: cookies Secure não seriam enviados via http pelo jar."""

    def __init__(self):
        self.cookies: dict[str, str] = {}
        self.client = httpx.Client(timeout=30)

    def _headers(self):
        if not self.cookies:
            return {}
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}

    def req(self, method: str, path: str, **kwargs):
        res = self.client.request(method, f"{API}{path}", headers=self._headers(), **kwargs)
        for k, v in res.cookies.items():
            self.cookies[k] = v
        return res

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, **kw): return self.req("POST", path, **kw)
    def put(self, path, **kw): return self.req("PUT", path, **kw)
    def patch(self, path, **kw): return self.req("PATCH", path, **kw)
    def delete(self, path, **kw): return self.req("DELETE", path, **kw)


def main():
    ts = int(time.time())
    alice = Session()
    bruno = Session()

    # --- Infra ---
    res = httpx.get(f"{API}/health", timeout=15)
    check("health via nginx", res.status_code == 200 and res.json()["status"] == "ok")

    res = httpx.get(f"{BASE}/settings", timeout=15)
    check("SPA deep-link (/settings) responde HTML", res.status_code == 200 and "<html" in res.text.lower())

    # A CSP só existe no nginx real — nenhum teste da suíte a enxerga. `ws:`/`wss:`
    # sem host liberavam WebSocket para QUALQUER origem (exfiltração pós-XSS);
    # `connect-src 'self'` já cobre o WebSocket same-origin.
    csp = res.headers.get("content-security-policy", "")
    check("CSP presente no HTML da SPA", "default-src 'self'" in csp, f"CSP={csp[:120]}")
    check(
        "CSP não libera WebSocket para qualquer host",
        "connect-src 'self'" in csp and " ws:" not in csp and " wss:" not in csp,
        f"CSP={csp[:200]}",
    )

    res = httpx.get(f"{API}/rota-inexistente", timeout=15)
    check("404 JSON para rota de API inexistente", res.status_code == 404 and "error" in res.json())

    # --- Cadastro e sessão (Alice) ---
    email_a = f"smoke_a_{ts}@teste.com"
    res = alice.post("/auth/register", json={"name": "Alice Smoke", "email": email_a, "password": "senha123"})
    check("registro Alice", res.status_code == 200)
    res = alice.post("/auth/login", json={"email": email_a, "password": "senha123"})
    check("login Alice (cookies)", res.status_code == 200 and "access_token" in alice.cookies)
    res = alice.get("/auth/me")
    check("GET /auth/me", res.status_code == 200)
    alice_id = res.json()["id"]

    res = alice.get("/workspaces/")
    ws_id = res.json()[0]["id"]
    check("workspace padrão criado", res.status_code == 200 and len(res.json()) == 1)

    # Regressão: path sem barra final gera 307 do FastAPI; o Location precisa
    # preservar host:porta (nginx com $http_host). Com $host a porta some,
    # o browser segue para a porta errada e o frontend derruba a sessão.
    res = alice.get("/workspaces")
    if res.status_code == 307:
        loc = res.headers.get("location", "")
        check("307 sem barra preserva host:porta", loc.startswith(f"{BASE}/") or loc.startswith("/"),
              f"Location={loc}")
        follow_url = loc if loc.startswith("http") else f"{BASE}{loc}"
        res = alice.client.get(follow_url, headers=alice._headers())
    check("GET /workspaces (sem barra) chega ao backend autenticado", res.status_code == 200)

    res = alice.post("/auth/onboarding", json={
        "workspace_id": ws_id, "salary": 5000,
        "credit_card_name": "Cartão Smoke", "credit_card_limit": 3000, "credit_card_closing_day": 31,
    })
    check("onboarding (renda + cartão dia 31)", res.status_code == 200)

    res = alice.post("/auth/refresh")
    check("refresh de sessão", res.status_code == 200)

    # --- Categorias ---
    res = alice.get(f"/workspaces/{ws_id}/categories")
    check("categorias seed (9)", res.status_code == 200 and len(res.json()) == 9)
    cat_id = res.json()[0]["id"]

    # --- Transações (com categoria e fatura de cartão dia 31) ---
    res = alice.get(f"/workspaces/{ws_id}/credit-cards/")
    card_id = res.json()[0]["id"]
    res = alice.post(f"/workspaces/{ws_id}/transactions/", json={
        "title": "Mercado Smoke", "total_amount": "150.00",
        "transaction_date": "2026-02-10T12:00:00", "billing_month": "2026-02",
        "credit_card_id": card_id,
        "payers": [{"user_id": alice_id, "amount": "150.00"}],
        "splits": [{"user_id": alice_id, "split_method": "equal", "input_value": "0"}],
        "items": [{"title": "Mercado Smoke", "amount": "150.00", "category_id": cat_id}],
    })
    check("transação com categoria + cartão (fev, fechamento 31)", res.status_code == 200 and res.json()["statement_id"])
    tx_anexo_id = res.json()["id"]  # recebe o anexo mais adiante

    res = alice.get(f"/workspaces/{ws_id}/credit-cards/{card_id}/statements")
    check("fatura criada com total", res.status_code == 200 and float(res.json()[0]["computed_total"]) == 150.0)

    # A UI anuncia o destino da compra ANTES de salvar (ADR 0002) — e perguntar
    # não pode criar fatura. Cartão do onboarding fecha dia 31.
    faturas_antes = len(res.json())
    res = alice.get(
        f"/workspaces/{ws_id}/credit-cards/{card_id}/statement-for", params={"on": "2026-05-10"}
    )
    alvo = res.json() if res.status_code == 200 else {}
    check(
        "statement-for anuncia a fatura de destino",
        res.status_code == 200 and alvo.get("month") == "2026-05" and "due_date" in alvo,
        str(alvo),
    )
    res = alice.get(f"/workspaces/{ws_id}/credit-cards/{card_id}/statements")
    check("consultar o destino NÃO cria fatura", len(res.json()) == faturas_antes)

    # Excluir cartão com fatura em aberto é 409: o soft delete escondia o cartão
    # e deixava a dívida sem nenhuma tela por onde ser quitada.
    res = alice.delete(f"/workspaces/{ws_id}/credit-cards/{card_id}")
    check("excluir cartão com fatura em aberto → 409", res.status_code == 409, res.text)

    # --- Validações de borda em produção ---
    res = alice.get(
        f"/workspaces/{ws_id}/analytics/exchange-rate", params={"from_currency": "../../etc"}
    )
    check("moeda fora do formato ISO-3 rejeitada (400)", res.status_code == 400, res.text)
    res = alice.post(f"/workspaces/{ws_id}/transactions/", json={
        "title": "Negativa", "total_amount": "-10",
        "transaction_date": "2026-02-10T12:00:00",
        "payers": [{"user_id": alice_id, "amount": "-10"}],
        "splits": [{"user_id": alice_id, "split_method": "equal", "input_value": "0"}],
    })
    check("valor negativo rejeitado (422)", res.status_code == 422)
    res = alice.get(f"/workspaces/{ws_id}/analytics/summary?month=lixo")
    check("mês inválido rejeitado (400)", res.status_code == 400)
    res = alice.get(f"/workspaces/{ws_id}/transactions/?limit=0")
    check("limit=0 rejeitado (422)", res.status_code == 422)

    # --- Convite + segundo usuário ---
    email_b = f"smoke_b_{ts}@teste.com"
    res = bruno.post("/auth/register", json={"name": "Bruno Smoke", "email": email_b, "password": "senha123"})
    check("registro Bruno", res.status_code == 200)
    res = bruno.post("/auth/login", json={"email": email_b, "password": "senha123"})
    check("login Bruno", res.status_code == 200)
    res = bruno.get("/auth/me")
    bruno_id = res.json()["id"]

    # Convite exige ACEITE: usuário já cadastrado não entra mais direto (era
    # possível dar a si mesmo acesso às finanças de quem tivesse o e-mail).
    res = alice.post(f"/workspaces/{ws_id}/invites", json={"email": email_b, "role": "member"})
    check("convite enviado (não entra direto)", res.status_code == 200 and res.json()["status"] == "invite_sent")

    res = bruno.get(f"/workspaces/{ws_id}/members")
    check("convidado ainda NÃO é membro (403)", res.status_code == 403)

    res = bruno.get("/notifications")
    convites = [n for n in res.json()["items"] if n["type"] == "workspace_invite" and n["invite_token"]]
    check("convite chega como notificação no app", res.status_code == 200 and len(convites) == 1)
    token_convite = convites[0]["invite_token"]

    res = bruno.post(f"/invites/accept/{token_convite}")
    check("Bruno aceita o convite", res.status_code == 200)

    res = bruno.get("/notifications")
    check("notificação do convite deixa de estar pendente",
          all(n["read_at"] for n in res.json()["items"] if n["type"] == "workspace_invite"))

    res = bruno.get(f"/workspaces/{ws_id}/members")
    check("Bruno vê os membros do workspace", res.status_code == 200 and len(res.json()) == 2)

    # --- Split entre dois usuários + dívidas ---
    res = bruno.post(f"/workspaces/{ws_id}/transactions/", json={
        "title": "Jantar Compartilhado", "total_amount": "100.00",
        "transaction_date": "2026-02-11T12:00:00", "billing_month": "2026-02",
        "payers": [{"user_id": bruno_id, "amount": "100.00"}],
        "splits": [
            {"user_id": alice_id, "split_method": "equal", "input_value": "0"},
            {"user_id": bruno_id, "split_method": "equal", "input_value": "0"},
        ],
    })
    check("transação dividida A/B", res.status_code == 200)
    tx_id = res.json()["id"]

    res = alice.get(f"/workspaces/{ws_id}/debts")
    check("dívida calculada (Alice deve 50 a Bruno)", res.status_code == 200 and len(res.json()) == 1
          and float(res.json()[0]["amount"]) == 50.0)

    res = bruno.delete(f"/workspaces/{ws_id}/transactions/{tx_id}")
    check("Bruno exclui a própria transação", res.status_code == 200)
    res = alice.get(f"/workspaces/{ws_id}/debts")
    check("dívidas zeradas após exclusão", res.json() == [])

    # --- Recorrência / Financiamento / Orçamento / Renda ---
    res = alice.post(f"/workspaces/{ws_id}/recurring", json={"title": "Internet", "base_amount": "99.90", "day_of_month": 10})
    rec_id = res.json()["id"]
    check("recorrência criada", res.status_code == 200)
    res = alice.delete(f"/workspaces/{ws_id}/recurring/{rec_id}")
    check("recorrência excluída", res.status_code == 200)

    res = alice.post(f"/workspaces/{ws_id}/financing", json={
        "title": "Carro Smoke", "total_amount": "12000", "interest_rate": "0.015",
        "start_date": "2026-03-01", "installments_count": 12, "method": "PRICE",
    })
    fin_id = res.json()["id"]
    check("financiamento PRICE criado", res.status_code == 200)
    res = alice.get(f"/workspaces/{ws_id}/financing/{fin_id}/schedule")
    check("cronograma com 12 parcelas", len(res.json()) == 12)
    res = alice.post(f"/workspaces/{ws_id}/financing/{fin_id}/early-settlement", json={})
    check("simulação de quitação", res.status_code == 200 and float(res.json()["savings"]) > 0)
    res = alice.post(f"/workspaces/{ws_id}/financing/{fin_id}/installments/1/pay")
    check("parcela 1 paga", res.status_code == 200)

    res = alice.post(f"/workspaces/{ws_id}/analytics/estimates", json={"category": "Geral", "amount": "2500", "month": "2026-02"})
    check("orçamento definido", res.status_code == 200)
    res = alice.get(f"/workspaces/{ws_id}/analytics/forecast?month=2026-02")
    check("forecast com orçamento", res.status_code == 200 and float(res.json()["total_budget"]) == 2500.0)

    res = alice.post(f"/workspaces/{ws_id}/income/", json={
        "title": "Freela", "amount": "800", "received_at": "2026-02-15T12:00:00",
    })
    check("renda extra criada", res.status_code == 200)

    # --- Anexos: o ÚNICO passo que prova o volume (ADR 0007) ---
    # Nenhum teste da suíte toca no volume real — eles apontam o armazenamento
    # para um tmpdir. Volume nomeado nasce root e o container roda como appuser:
    # sem este passo, "permission denied" no upload só apareceria para o usuário.
    res = alice.post(
        f"/workspaces/{ws_id}/transactions/{tx_anexo_id}/attachments",
        files={"file": ("recibo.png", PNG_MINIMO, "image/png")},
    )
    check("upload de anexo grava no volume", res.status_code == 200, res.text[:200])
    anexo_id = res.json()["id"]

    res = alice.get(f"/workspaces/{ws_id}/attachments/{anexo_id}")
    check("download devolve os bytes gravados", res.status_code == 200 and res.content == PNG_MINIMO)

    res = alice.delete(f"/workspaces/{ws_id}/attachments/{anexo_id}")
    check("anexo removido", res.status_code == 200)

    # --- Papéis: Bruno (member) não gerencia membros ---
    res = bruno.post(f"/workspaces/{ws_id}/invites", json={"email": "x@y.com", "role": "member"})
    check("member não convida (403)", res.status_code == 403)

    # --- Troca de senha + rate limit (por último: polui o limiter) ---
    res = alice.post("/auth/change-password", json={"current_password": "senha123", "new_password": "novaSenha1"})
    check("troca de senha", res.status_code == 200)
    res = alice.post("/auth/login", json={"email": email_a, "password": "novaSenha1"})
    check("login com senha nova", res.status_code == 200)

    got_429 = False
    for _ in range(7):
        res = httpx.post(f"{API}/auth/login", json={"email": "naoexiste@x.com", "password": "errada1"}, timeout=15)
        if res.status_code == 429:
            got_429 = True
            break
    check("rate limit ativo no login (429)", got_429)

    print(f"\nSMOKE DE PRODUCAO: {_passed} verificacoes OK — stack aprovado.")


if __name__ == "__main__":
    main()
