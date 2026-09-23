"""Authorization server OAuth 2.1 embutido, para os clientes MCP (ADR 0035).

O SDK oficial do MCP é só resource server ("verifica, anuncia, recusa"); quem
emite token é este pacote. Serviços puros: fazem `flush`, nunca `commit`
(ADR 0010) — a rota comanda a transação.
"""
