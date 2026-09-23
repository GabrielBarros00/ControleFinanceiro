"""Erros do protocolo OAuth (RFC 6749 §5.2 / RFC 7591 §3.2.2).

Não são o envelope do app (`{"error": {...}}`): cliente OAuth espera
`{"error": "invalid_grant", "error_description": "..."}` e decide pelo código —
o Claude, por exemplo, só descarta a conexão quando a renovação responde
`invalid_grant`. Por isso as rotas do protocolo devolvem isto direto, sem passar
pelos handlers globais.
"""


class OAuthError(Exception):
    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code

    def body(self) -> dict:
        return {"error": self.error, "error_description": self.description}
