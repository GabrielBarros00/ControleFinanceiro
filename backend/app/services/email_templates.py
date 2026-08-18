"""O par texto/HTML de cada e-mail — as duas partes saem da MESMA fonte.

Até aqui toda mensagem do sistema era `text/plain` pura com a URL do token solta
no meio do corpo. Isso é, literalmente, a forma de um phishing: texto curto,
sem identidade visual, e um link com um token opaco pedindo que você clique.
Nenhum produto transacional real manda assim, e o classificador sabe disso.

Duas decisões estruturais moram aqui:

**As duas partes vêm da mesma chamada.** `corpo()` recebe o conteúdo uma vez e
renderiza texto e HTML a partir dele. Manter dois textos escritos à mão que
precisam dizer a mesma coisa é como o `MPART_ALT_DIFF` nasce — a regra que
pune justamente quem mostra uma coisa a quem lê HTML e outra a quem lê texto.

**Nada é carregado de fora.** Sem logo remoto, sem fonte do Google, sem pixel de
rastreio. O Outlook bloqueia imagem externa por padrão (a mensagem chega
quebrada) e o pedido a um servidor de terceiros no momento da leitura é, ele
próprio, sinal negativo. O que dá identidade aqui é cor, espaço e tipografia de
sistema.

A cor da marca (`#4c55bc`) é o `--primary` do app (`frontend/src/index.css`,
`oklch(0.50 0.16 275)`) e o fundo é o `theme_color` do manifesto — o e-mail
parece o produto de onde ele veio.
"""
import html
from typing import Optional, Sequence, Tuple

PRODUTO = "Controle Financeiro"

_FUNDO = "#fcfbf9"
_CARTAO = "#ffffff"
_BORDA = "#e7e5e4"
_TEXTO = "#292524"
_SECUNDARIO = "#78716c"
_MARCA = "#4c55bc"

# Tipografia do sistema: nenhuma webfont, nenhum pedido externo.
_FONTE = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',"
    "Arial,sans-serif"
)

_RODAPE = (
    f"{PRODUTO} — esta é uma mensagem automática, enviada porque alguém pediu "
    "esta ação no sistema."
)


def corpo(
    *,
    titulo: str,
    paragrafos: Sequence[str],
    acao: Optional[Tuple[str, str]] = None,
    fecho: Sequence[str] = (),
) -> Tuple[str, str]:
    """Devolve `(texto, html)` equivalentes para um mesmo conteúdo.

    `paragrafos` e `fecho` chegam em texto puro, com o valor real do usuário
    dentro; o escape para HTML acontece AQUI e só aqui. Pedir ao chamador que
    escape antes funcionaria até o dia em que alguém esquecesse — e o nome de um
    workspace é dado que o usuário escolhe.

    `acao` é o par `(rótulo, url)`. O botão leva um rótulo em verbo, e a URL
    completa aparece logo abaixo como link cujo texto visível é o próprio
    endereço: quem desconfia consegue conferir para onde vai antes de clicar, e
    nenhuma âncora exibe um destino diferente do que carrega.
    """
    texto = _texto(titulo, paragrafos, acao, fecho)
    return texto, _html(titulo, paragrafos, acao, fecho)


def _texto(
    titulo: str,
    paragrafos: Sequence[str],
    acao: Optional[Tuple[str, str]],
    fecho: Sequence[str],
) -> str:
    blocos = [titulo, *paragrafos]
    if acao:
        rotulo, url = acao
        blocos.append(f"{rotulo}:\n{url}")
    blocos.extend(fecho)
    blocos.append(f"--\n{_RODAPE}")
    return "\n\n".join(blocos) + "\n"


def _html(
    titulo: str,
    paragrafos: Sequence[str],
    acao: Optional[Tuple[str, str]],
    fecho: Sequence[str],
) -> str:
    partes = [
        f'<h1 style="margin:0 0 24px;font-size:20px;line-height:1.3;'
        f'font-weight:600;color:{_TEXTO};">{html.escape(titulo)}</h1>'
    ]
    partes.extend(_paragrafo(p) for p in paragrafos)

    if acao:
        rotulo, url = acao
        partes.append(_botao(rotulo, url))
        partes.append(
            f'<p style="margin:0 0 24px;font-size:13px;line-height:1.6;'
            f'color:{_SECUNDARIO};">Se o botão não funcionar, copie este '
            f'endereço:<br>'
            f'<a href="{html.escape(url, quote=True)}" '
            f'style="color:{_MARCA};word-break:break-all;">'
            f"{html.escape(url)}</a></p>"
        )

    partes.extend(_paragrafo(p, cor=_SECUNDARIO, tamanho=14) for p in fecho)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title>
</head>
<body style="margin:0;padding:0;background-color:{_FUNDO};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" \
border="0" style="background-color:{_FUNDO};padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" \
border="0" style="max-width:600px;width:100%;background-color:{_CARTAO};\
border:1px solid {_BORDA};border-radius:12px;">
<tr><td style="padding:40px 40px 32px;font-family:{_FONTE};font-size:16px;\
line-height:1.6;color:{_TEXTO};">
{chr(10).join(partes)}
</td></tr>
</table>
<p style="margin:24px 0 0;font-family:{_FONTE};font-size:12px;line-height:1.6;\
color:{_SECUNDARIO};max-width:600px;">{html.escape(_RODAPE)}</p>
</td></tr>
</table>
</body>
</html>
"""


def _paragrafo(texto: str, *, cor: str = _TEXTO, tamanho: int = 16) -> str:
    return (
        f'<p style="margin:0 0 16px;font-size:{tamanho}px;line-height:1.6;'
        f'color:{cor};">{html.escape(texto)}</p>'
    )


def _botao(rotulo: str, url: str) -> str:
    """Botão em tabela, não em `<a>` com padding.

    O Outlook para Windows renderiza HTML com o motor do Word, que ignora
    `padding` em elemento inline: o botão vira um link sublinhado sem caixa. A
    célula com `bgcolor` é o jeito que funciona nos dois mundos.
    """
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px 0 24px;"><tr>'
        f'<td bgcolor="{_MARCA}" style="border-radius:8px;">'
        f'<a href="{html.escape(url, quote=True)}" '
        'style="display:inline-block;padding:14px 28px;font-size:16px;'
        f'font-weight:600;color:#ffffff;text-decoration:none;font-family:{_FONTE};">'
        f"{html.escape(rotulo)}</a>"
        "</td></tr></table>"
    )


def recuperacao_de_senha(reset_link: str, minutos: int) -> Tuple[str, str]:
    return corpo(
        titulo="Redefinir a sua senha",
        paragrafos=[
            "Olá,",
            "Recebemos um pedido para redefinir a senha da sua conta no "
            f"{PRODUTO}. O link abaixo vale por {minutos} minutos.",
        ],
        acao=("Redefinir minha senha", reset_link),
        fecho=[
            "Se você não pediu a redefinição, ignore este e-mail — a sua senha "
            "atual continua valendo."
        ],
    )


def convite_de_workspace(
    workspace_name: str, invited_by: str, accept_link: str
) -> Tuple[str, str]:
    return corpo(
        titulo=f"Convite para o espaço “{workspace_name}”",
        paragrafos=[
            "Olá,",
            f"{invited_by} convidou você para participar do espaço "
            f"“{workspace_name}” no {PRODUTO}, onde vocês acompanham juntos as "
            "despesas compartilhadas.",
        ],
        acao=("Aceitar o convite", accept_link),
        fecho=[
            "Se você não conhece quem convidou, pode ignorar esta mensagem."
        ],
    )


def convite_de_cadastro(invited_by: str, register_link: str) -> Tuple[str, str]:
    return corpo(
        titulo=f"Convite para o {PRODUTO}",
        paragrafos=[
            "Olá,",
            f"{invited_by} convidou você para usar o {PRODUTO}, onde você "
            "organiza suas contas e divide despesas com quem quiser.",
        ],
        acao=("Criar minha conta", register_link),
        fecho=[
            "O link é pessoal e tem prazo de validade.",
            "Se você não esperava este convite, pode ignorar esta mensagem.",
        ],
    )


def teste_de_configuracao() -> Tuple[str, str]:
    return corpo(
        titulo="O envio de e-mail está funcionando",
        paragrafos=[
            "Esta mensagem foi disparada pela tela de Administração do "
            f"{PRODUTO}. Se ela chegou, convites e recuperação de senha também "
            "conseguem sair.",
            "Vale conferir em qual PASTA ela caiu: o teste responde “enviado” "
            "mesmo quando a mensagem vai para o spam do destinatário.",
        ],
    )
