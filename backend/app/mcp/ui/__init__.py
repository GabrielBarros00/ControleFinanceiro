"""Componente MCP Apps (HTML único, gerado por `npm run build:mcp-widget`).

A URI é CHAVE DE CACHE no ChatGPT. Na documentação da OpenAI: "Treat the resource URI
as a cache key. When you make a breaking change to the HTML, JavaScript, or CSS,
publish a new URI and update every tool that references it." Mudar o `widget.html`
sem mudar a URI faria o ChatGPT seguir servindo o componente antigo, sem erro
nenhum.

Por isso o hash do HTML publicado fica registrado ao lado da versão, e
`tests/mcp/test_audit_and_safety.py` reprova quando os dois divergem. Mudou o
componente (inclusive por atualização de dependência)? Some 1 em `WIDGET_VERSION` e
atualize `WIDGET_SHA256` com o valor que o teste mostrar.
"""
WIDGET_VERSION = 2
WIDGET_URI = f"ui://controle-financeiro/widget-v{WIDGET_VERSION}.html"
#: sha256 do `widget.html` desta versão, com fim de linha normalizado para LF. No
#: Windows, os fontes são baixados com CRLF e o CRLF entra no bundle; o git grava LF,
#: e o build do Linux (CI) sai com LF. Normalizado, o hash é o mesmo nos dois.
WIDGET_SHA256 = "f21576ad92cba29551bdbb2f9723e1a428c2e09d3c6d37ff7208aad9b2c9ccbd"
