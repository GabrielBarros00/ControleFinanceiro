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

# O console do Windows é cp1252: um "→" no nome de um check derrubava o SCRIPT
# no `print`, depois de a verificação ter PASSADO — o gate de deploy morria com
# UnicodeEncodeError no meio da jornada e nunca chegava ao veredito. Aqui o que
# não couber vira "?" em vez de exceção.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

        # 429 em rota de auth: espera a janela e tenta de novo, em vez de dar o
        # gate por reprovado. O limite por IP+rota é proteção REAL, que não se
        # desliga para testar, e qualquer coisa que tenha rodado antes (a suíte
        # e2e-prod, outra execução deste script) já consumiu parte da cota.
        # Sem isto, o gate de deploy reprovava por motivo que não é o deploy.
        if res.status_code == 429 and path.startswith("/auth/"):
            for _ in range(7):
                time.sleep(10)
                res = self.client.request(
                    method, f"{API}{path}", headers=self._headers(), **kwargs
                )
                if res.status_code != 429:
                    break

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
    admin = Session()
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

    # --- Portão de cadastro e o primeiro superadministrador (ADR 0026) ---
    #
    # Em produção o cadastro nasce POR CONVITE, e é isso que este bloco prova
    # contra o stack real. Alice é o `SUPERADMIN_EMAIL`: ela entra pela janela de
    # bootstrap — a única forma de a primeira conta existir num site fechado — e
    # a partir daí a janela se fecha.
    res = httpx.get(f"{API}/auth/registration-policy", timeout=15)
    check("política de cadastro é pública", res.status_code == 200)
    politica = res.json()
    check(
        "cadastro exige convite em produção",
        politica["exige_convite"] is True,
        f"modo={politica['mode']}",
    )

    res = httpx.post(
        f"{API}/auth/register", timeout=15,
        json={"name": "Penetra", "email": f"penetra_{ts}@teste.com", "password": "senha123"},
    )
    check("cadastro sem convite é recusado", res.status_code == 403)

    email_admin = os.environ.get("SMOKE_SUPERADMIN_EMAIL", "smoke-admin@example.com")
    res = admin.post(
        "/auth/register",
        json={"name": "Admin Smoke", "email": email_admin, "password": "senha123"},
    )
    # 400 = a conta já existe de uma execução anterior contra o mesmo stack. O
    # smoke precisa ser repetível: em CI o banco é novo e cai no 200; rodado à
    # mão contra um stack de pé cai no 400 e segue pelo login.
    check("registro do superadmin (bootstrap)", res.status_code in (200, 400),
          f"{res.status_code} {res.text[:200]}")
    if res.status_code == 200:
        check("primeira conta nasce superadministradora",
              res.json()["platform_role"] == "superadmin")

    res = admin.post("/auth/login", json={"email": email_admin, "password": "senha123"})
    check("login do superadmin", res.status_code == 200)

    res = admin.get("/admin/overview")
    check("área administrativa responde ao superadmin", res.status_code == 200)
    check("visão geral traz contagem, não dinheiro",
          "usuarios_total" in res.json() and not any(
              c in res.json() for c in ("total_amount", "saldo", "valor")))

    # Alice entra POR CONVITE — o caminho que todo mundo além do primeiro usa.
    # Continua sendo uma conta nova a cada execução: as verificações seguintes
    # contam workspaces e lançamentos e não sobreviveriam a uma conta reusada.
    email_a = f"smoke_a_{ts}@teste.com"
    res = admin.post("/admin/registration-invites", json={"email": email_a})
    check("superadmin emite convite de cadastro", res.status_code == 201)
    convite_a = res.json()["token"]

    res = alice.post("/auth/register", json={
        "name": "Alice Smoke", "email": email_a, "password": "senha123",
        "invite_token": convite_a,
    })
    check("registro Alice com convite", res.status_code == 200, f"{res.status_code} {res.text[:200]}")
    check("quem entra por convite NÃO nasce com poder de plataforma",
          res.json()["platform_role"] == "user")

    res = httpx.post(f"{API}/auth/register", timeout=15, json={
        "name": "Reuso", "email": f"reuso_{ts}@teste.com",
        "password": "senha123", "invite_token": convite_a,
    })
    check("convite de uso único não serve duas vezes", res.status_code == 403)

    res = alice.post("/auth/login", json={"email": email_a, "password": "senha123"})
    check("login Alice (cookies)", res.status_code == 200 and "access_token" in alice.cookies)
    res = alice.get("/auth/me")
    check("GET /auth/me", res.status_code == 200)
    alice_id = res.json()["id"]

    res = alice.get("/workspaces/")
    ws_id = res.json()[0]["id"]
    check("workspace padrão criado", res.status_code == 200 and len(res.json()) == 1)

    # `/workspaces` (sem barra) já NÃO redireciona: a rota irmã foi registrada
    # depois que a auditoria mostrou que o 307 perdia o cookie e devolvia 401.
    # A checagem continua porque é a garantia de que a irmã existe.
    res = alice.get("/workspaces")
    check("GET /workspaces (sem barra) responde direto, sem 307",
          res.status_code == 200, f"status={res.status_code}")

    # Regressão do NGINX, que segue valendo: onde ainda há redirecionamento, o
    # `Location` precisa preservar host:porta (`$http_host`). Com `$host` a porta
    # some, o navegador segue para a porta errada e a sessão cai.
    #
    # O alvo é `/auth/me/` — registrada SEM barra, então chamá-la COM barra ainda
    # produz o 307. Antes este teste usava `/workspaces`, e ao consertar aquela
    # rota a verificação passou a ser pulada em silêncio: o gate perdia uma
    # asserção sem que nada ficasse vermelho.
    res = alice.client.get(f"{BASE}/api/v1/auth/me/", headers=alice._headers(),
                           follow_redirects=False)
    check("ainda existe rota que redireciona (senão este teste não mede nada)",
          res.status_code == 307, f"status={res.status_code}")
    loc = res.headers.get("location", "")
    check("307 preserva host:porta no Location",
          loc.startswith(f"{BASE}/") or loc.startswith("/"), f"Location={loc}")
    seguido = alice.client.get(
        loc if loc.startswith("http") else f"{BASE}{loc}", headers=alice._headers()
    )
    check("seguir o 307 chega ao backend autenticado", seguido.status_code == 200)

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
    res = alice.get("/me/credit-cards")
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

    # Pela MÊS, não pelo índice: a listagem devolve também a fatura do ciclo
    # corrente (vazia), e ela vem na frente da de fevereiro. Assumir `[0]` fazia
    # o gate depender da ordenação e da data em que ele roda.
    res = alice.get(f"/me/credit-cards/{card_id}/statements")
    fatura_fev = next(
        (f for f in res.json() if f["month"] == "2026-02"), None
    ) if res.status_code == 200 else None
    check(
        "fatura de fevereiro criada com o total da compra",
        fatura_fev is not None and float(fatura_fev["computed_total"]) == 150.0,
        res.text[:300],
    )

    # A UI anuncia o destino da compra ANTES de salvar (ADR 0002) — e perguntar
    # não pode criar fatura. Cartão do onboarding fecha dia 31.
    faturas_antes = len(res.json())
    res = alice.get(
        f"/me/credit-cards/{card_id}/statement-for", params={"on": "2026-05-10"}
    )
    alvo = res.json() if res.status_code == 200 else {}
    check(
        "statement-for anuncia a fatura de destino",
        res.status_code == 200 and alvo.get("month") == "2026-05" and "due_date" in alvo,
        str(alvo),
    )
    res = alice.get(f"/me/credit-cards/{card_id}/statements")
    check("consultar o destino NÃO cria fatura", len(res.json()) == faturas_antes)

    # Excluir cartão com fatura em aberto é 409: o soft delete escondia o cartão
    # e deixava a dívida sem nenhuma tela por onde ser quitada.
    res = alice.delete(f"/me/credit-cards/{card_id}")
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
    res = admin.post("/admin/registration-invites", json={"email": email_b})
    check("convite de cadastro para Bruno", res.status_code == 201)
    res = bruno.post("/auth/register", json={
        "name": "Bruno Smoke", "email": email_b, "password": "senha123",
        "invite_token": res.json()["token"],
    })
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

    # --- Contas a pagar: liquidação (ADR 0029) ---
    # A coluna `settled_at` e o índice PARCIAL que a sustenta vêm da migração —
    # e é aqui, contra o Postgres de verdade e atrás do nginx, que isso é
    # exercitado. Um índice parcial com predicado inválido só falha no banco real.
    res = alice.post(f"/workspaces/{ws_id}/transactions/", json={
        "title": "Boleto do futuro", "total_amount": "80.00",
        "transaction_date": "2099-01-10T12:00:00", "billing_month": "2099-01",
        "payment_method": "boleto",
        "payers": [{"user_id": alice_id, "amount": "80.00"}],
        "splits": [{"user_id": alice_id, "split_method": "equal", "input_value": "0"}],
    })
    boleto_id = res.json()["id"]
    check("boleto futuro nasce A PAGAR", res.status_code == 200 and res.json()["settled_at"] is None)

    res = alice.get("/me/payables?month=2099-01")
    check("boleto aparece em Contas a pagar",
          res.status_code == 200
          and any(e["transaction_id"] == boleto_id for e in res.json()["entries"]))

    res = alice.post(f"/workspaces/{ws_id}/payables/settle", json={
        "transaction_ids": [boleto_id], "settled": True, "settled_on": "2099-01-15",
    })
    check("marcar como paga", res.status_code == 200 and res.json()["updated"] == 1)

    res = alice.get("/me/payables?month=2099-01")
    check("sai da fila depois de pago",
          not any(e["transaction_id"] == boleto_id for e in res.json()["entries"]))

    res = alice.delete(f"/workspaces/{ws_id}/transactions/{boleto_id}")
    check("boleto do smoke removido", res.status_code == 200)

    # --- Recorrência / Financiamento / Orçamento / Renda ---
    res = alice.post(f"/workspaces/{ws_id}/recurring", json={"title": "Internet", "base_amount": "99.90", "day_of_month": 10})
    rec_id = res.json()["id"]
    check("recorrência criada", res.status_code == 200)

    # A revisão (ADR 0030) é POST e leva corpo: passa por proxy, CSRF e sessão —
    # exatamente o que só o stack de produção exercita.
    res = alice.post(f"/workspaces/{ws_id}/recurring/{rec_id}/preview",
                     json={"action": "update", "changes": {"day_of_month": 20}})
    check("revisão da recorrência responde", res.status_code == 200 and "items" in res.json())

    res = alice.delete(f"/workspaces/{ws_id}/recurring/{rec_id}")
    check("recorrência excluída", res.status_code == 200)

    res = alice.post("/me/financing", json={
        "title": "Carro Smoke", "total_amount": "12000", "interest_rate": "0.015",
        "start_date": "2026-03-01", "installments_count": 12, "method": "PRICE",
    })
    fin_id = res.json()["id"]
    check("financiamento PRICE criado", res.status_code == 200)
    res = alice.get(f"/me/financing/{fin_id}/schedule")
    check("cronograma com 12 parcelas", len(res.json()) == 12)
    res = alice.post(f"/me/financing/{fin_id}/early-settlement", json={})
    check("simulação de quitação", res.status_code == 200 and float(res.json()["savings"]) > 0)
    res = alice.post(f"/me/financing/{fin_id}/installments/1/pay")
    check("parcela 1 paga", res.status_code == 200)

    res = alice.post(f"/workspaces/{ws_id}/analytics/estimates", json={"category": "Geral", "amount": "2500", "month": "2026-02"})
    check("orçamento definido", res.status_code == 200)
    res = alice.get(f"/workspaces/{ws_id}/analytics/forecast?month=2026-02")
    check("forecast com orçamento", res.status_code == 200 and float(res.json()["total_budget"]) == 2500.0)

    res = alice.post("/me/income", json={
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

    # E-mails DIFERENTES a cada tentativa: com o mesmo e-mail quem responde é o
    # balde por CONTA, e o que interessa aqui é esgotar o balde por IP para a
    # verificação seguinte. O teto é configurável no backend, então o laço vai
    # bem além do default (20/min) em vez de repetir o número.
    TENTATIVAS = 40
    got_429 = False
    for i in range(TENTATIVAS):
        res = httpx.post(f"{API}/auth/login", json={"email": f"naoexiste{i}@x.com", "password": "errada1"}, timeout=15)
        if res.status_code == 429:
            got_429 = True
            break
    check(
        "rate limit ativo no login (429)", got_429,
        f"nenhum 429 em {TENTATIVAS} tentativas — RATE_LIMIT_AUTH_PER_MINUTE alto demais?",
    )

    # O balde por IP só existe de verdade se o cliente não puder escolher o
    # próprio IP. O nginx sobrescreve `X-Forwarded-For` com `$remote_addr` e o
    # uvicorn só confia na rede do Compose; enquanto a lista do cliente era
    # PRESERVADA, um valor novo a cada tentativa dava um balde novo e a proteção
    # não existia. E-mail inédito de propósito: com um já usado, o 429 poderia
    # vir do balde por conta e o teste passaria pelo motivo errado.
    res = httpx.post(
        f"{API}/auth/login",
        json={"email": "forjado@x.com", "password": "errada1"},
        headers={"X-Forwarded-For": "203.0.113.7"},
        timeout=15,
    )
    check(
        "X-Forwarded-For forjado nao escapa do rate limit", res.status_code == 429,
        f"status={res.status_code} — o backend aceitou o IP que o cliente inventou",
    )

    # --- Fronteira da área administrativa (ADR 0026) -----------------------
    #
    # A promessa que sustenta os ADRs 0018 e 0021 é que administrar o SITE não dá
    # acesso ao dinheiro de ninguém. A suíte prova isso em SQLite; aqui é contra
    # o stack real, com dado que Alice acabou de criar nesta mesma execução.
    res = alice.get("/admin/overview")
    check("usuário comum não alcança a área administrativa (404)", res.status_code == 404)

    res = admin.get(f"/workspaces/{ws_id}/transactions/")
    check(
        "superadmin não entra no workspace alheio", res.status_code in (403, 404),
        f"status={res.status_code} — a política consultou o papel de plataforma?",
    )

    corpo = admin.get("/admin/users").text
    check(
        "listagem de pessoas não devolve dado financeiro",
        "Mercado do smoke" not in corpo and "Aluguel" not in corpo,
    )

    res = admin.get("/admin/health")
    check("saúde do site responde", res.status_code == 200 and "cambio_ultima_data" in res.json())

    # A trava que impede o site de ficar sem administração.
    res = admin.get("/auth/me")
    admin_id = res.json()["id"]
    res = admin.patch(f"/admin/users/{admin_id}", json={"platform_role": "admin"})
    check(
        "último superadministrador não consegue se rebaixar", res.status_code == 409,
        f"status={res.status_code} — o site ficaria sem quem o configure",
    )

    res = admin.patch(f"/admin/users/{admin_id}", json={"is_active": False})
    check(
        "ninguém desativa a própria conta", res.status_code == 409,
        f"status={res.status_code} — o admin acabaria de se trancar do lado de fora",
    )

    # Curinga do LIKE: `%` precisa ser texto, não "todo mundo". Vale a pena aqui
    # e não só na suíte porque o escape é o tipo de coisa que muda de
    # comportamento entre SQLite e Postgres, e produção é Postgres.
    res = admin.get("/admin/users", params={"busca": "%"})
    check(
        "busca não trata '%' como curinga", res.json()["total"] == 0,
        f"devolveu {res.json()['total']} pessoas — o filtro casou com a lista inteira",
    )
    res = admin.get("/admin/users", params={"busca": email_a})
    check("busca literal continua achando", res.json()["total"] == 1)

    # O teto do processo (`IMPORT_MAX_ROWS`) já é aplicado pelo Pydantic ANTES do
    # handler: aceitar um valor maior aqui salvaria uma configuração que a tela
    # mostra como vigente e que não vale nada.
    res = admin.put("/admin/settings", json={"valores": {"import_max_rows": 999_999}})
    check(
        "configuração não afrouxa o teto de importação do processo",
        res.status_code == 422, f"status={res.status_code}",
    )

    # --- O convite de workspace é a MESMA capacidade ------------------------
    #
    # `who_can_invite` só valia em `/me/registration-invites`, e um
    # `WorkspaceInvite` autoriza cadastro igual. Como todo usuário nasce `owner`
    # do próprio workspace, a chave não valia nada: bastava convidar pela tela de
    # membros. Vale conferir no stack real porque a decisão depende de uma
    # consulta ("este endereço já tem conta?") que roda em Postgres.
    admin.put("/admin/settings", json={"valores": {"who_can_invite": "admins_only"}})
    try:
        res = alice.post(
            f"/workspaces/{ws_id}/invites", json={"email": "de-fora-do-smoke@example.com"}
        )
        check(
            "usuário comum não traz gente de fora pelo convite de workspace",
            res.status_code == 403, f"status={res.status_code} — a porta dos fundos do convite",
        )
        res = alice.post(f"/workspaces/{ws_id}/invites/link", json={})
        check(
            "usuário comum não gera link de workspace com o convite fechado",
            res.status_code == 403, f"status={res.status_code}",
        )
        res = alice.post(f"/workspaces/{ws_id}/invites/link", json={"max_uses": 999_999})
        check(
            "link de workspace tem teto de usos", res.status_code in (403, 422),
            f"status={res.status_code} — seria um cadastro público com outro nome",
        )
    finally:
        admin.put("/admin/settings", json={"valores": {"who_can_invite": "all_users"}})

    # --- Pausado é pausado: não nascem contas -------------------------------
    #
    # O middleware libera `/auth/*` para o administrador CONSEGUIR ENTRAR e
    # desligar o modo; o cadastro passava de carona. O `finally` não é zelo: uma
    # falha com a manutenção ligada deixaria o stack inutilizável para os testes
    # e2e que rodam DEPOIS deste script.
    admin.put("/admin/settings", json={"valores": {"maintenance_mode": True}})
    try:
        res = httpx.post(
            f"{API}/auth/register",
            json={"name": "Intrusa", "email": "durante-manutencao@example.com",
                  "password": "senha123"},
            timeout=15,
        )
        check(
            "cadastro não passa com a manutenção ligada", res.status_code == 503,
            f"status={res.status_code} — o site pausado seguiu fazendo nascer conta",
        )
    finally:
        admin.put("/admin/settings", json={"valores": {"maintenance_mode": False}})

    res = httpx.get(f"{API}/notifications", timeout=15)
    check(
        "a manutenção foi mesmo desligada", res.status_code != 503,
        "o stack ficou em manutenção — os testes seguintes falhariam todos",
    )

    print(f"\nSMOKE DE PRODUCAO: {_passed} verificacoes OK — stack aprovado.")


if __name__ == "__main__":
    main()
