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
#: sha256 do `widget.html` desta versão. Os fontes do componente e o HTML gerado são
#: LF em qualquer sistema (`.gitattributes`); com CRLF, o texto dos fontes entrava no
#: bundle e o build do Windows divergia do build do CI. O teste ainda normaliza o fim
#: de linha antes de comparar, por garantia.
WIDGET_SHA256 = "39f3e36c59a3a158223638f391e1d4ae75fb8e00c60b0611f7eec0de38331013"
