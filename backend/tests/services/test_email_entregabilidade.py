"""A FORMA da mensagem — o que separa "entregue" de "caixa de spam".

Autenticação passando não basta. Os e-mails deste sistema caíram no spam do
`@live.com` com SPF, DKIM e DMARC corretos no DNS, e a causa estava na mensagem:
ela saía com seis cabeçalhos, sem `Date` (que a RFC 5322 exige), sem
`Message-ID`, e com o corpo inteiro em base64. Cada um é uma regra de filtro com
nome próprio — `MISSING_DATE`, `MISSING_MID`, `MIME_BASE64_TEXT` —, e a soma
decide a pasta.

É um defeito invisível para todo o resto da rede: o SMTP aceita a mensagem, o
provedor a entrega, o teste da tela de Admin responde "enviado". Ninguém
descobre pelo caminho do envio — só abrindo a pasta de spam de quem recebeu.
"""
import html as html_lib
import re
from email import message_from_string
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pytest

from app.services import email_templates
from app.services.email_service import EmailService

# Os três e-mails que precisam CHEGAR, com o link que cada um carrega.
ENVIOS_REAIS = (
    (
        "senha",
        lambda: EmailService.send_password_reset("a@live.com", "https://app.exemplo.com/r?t=1"),
        "https://app.exemplo.com/r?t=1",
    ),
    (
        "Convite",
        lambda: EmailService.send_registration_invite(
            "a@live.com", "Ana", "https://app.exemplo.com/register?invite=2"
        ),
        "https://app.exemplo.com/register?invite=2",
    ),
    (
        "Convite",
        lambda: EmailService.send_workspace_invite(
            "a@live.com", "Casa", "Ana", "https://app.exemplo.com/invite/3"
        ),
        "https://app.exemplo.com/invite/3",
    ),
)


def _texto_e_html(msg):
    """As duas partes de um `multipart/alternative`, na ordem que a RFC pede."""
    assert msg.get_content_type() == "multipart/alternative", (
        f"mensagem saiu como {msg.get_content_type()}: sem parte HTML, um texto "
        "curto com URL de token solta tem a forma exata de um phishing"
    )
    partes = list(msg.iter_parts())
    assert [p.get_content_type() for p in partes] == ["text/plain", "text/html"], (
        "a ordem importa: o cliente exibe a ÚLTIMA parte que sabe ler, então o "
        "texto vem primeiro e o HTML por último"
    )
    return partes


@pytest.fixture(name="capturada")
def capturada_fixture(monkeypatch):
    """Intercepta no transporte: exercita o caminho real de `EmailService.send`."""
    entregues = []

    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr(
        "app.core.config.settings.EMAIL_FROM",
        "Controle Financeiro <noreply@notify.exemplo.com>",
    )
    # Explícito para o resultado não depender do `.env` da máquina que roda a
    # suíte: o padrão do produto é NÃO emitir o cabeçalho.
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", None)
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )

    def envia(assunto="Assunto", corpo="Corpo com acentuação: ação.", **kwargs):
        EmailService.send("alguem@live.com", assunto, corpo, **kwargs)
        return entregues[-1]

    return envia


def test_mensagem_tem_date(capturada):
    """`Date` é OBRIGATÓRIO na RFC 5322 — sem ele a mensagem é malformada."""
    msg = capturada()
    assert msg["Date"], "mensagem sem Date: regra MISSING_DATE em qualquer filtro"
    # Não basta existir: tem de ser uma data que o destinatário consiga ler.
    assert parsedate_to_datetime(msg["Date"]).tzinfo is not None


def test_mensagem_tem_message_id_do_dominio_do_remetente(capturada):
    """E não o hostname do container, que é um ID aleatório do Docker."""
    msg = capturada()
    message_id = msg["Message-ID"]
    assert message_id, "mensagem sem Message-ID: regra MISSING_MID"
    assert message_id.rstrip(">").endswith("@notify.exemplo.com"), (
        f"Message-ID {message_id!r} não usa o domínio do remetente — dentro de um "
        "container isso vira <...@3f2a9c1b4d5e>, marca de robô mal configurado"
    )


def test_cada_mensagem_tem_message_id_proprio(capturada):
    """Dois e-mails com o mesmo ID viram duplicata para o cliente do destinatário."""
    assert capturada()["Message-ID"] != capturada()["Message-ID"]


def test_corpo_de_texto_nao_vai_em_base64(capturada):
    """Texto curto inteiro em base64 é a forma de quem esconde o conteúdo.

    O `set_content` escolhe base64 sozinho quando o corpo tem acento — e todo
    corpo deste sistema tem.
    """
    msg = capturada()
    assert msg["Content-Transfer-Encoding"] == "quoted-printable"
    assert "ação" in msg.get_content(), "o corpo precisa continuar legível"


def test_o_corpo_aparece_legivel_no_fonte_da_mensagem(capturada):
    """A prova de fogo do encoding: o texto se lê no `.as_string()`."""
    fonte = capturada(corpo="Acesse o link para entrar").as_string()
    assert "Acesse o link para entrar" in fonte


@pytest.mark.parametrize("esperado,envio,link", ENVIOS_REAIS)
def test_todos_os_emails_do_sistema_saem_bem_formados(
    capturada, monkeypatch, esperado, envio, link
):
    """Não só o de teste da tela de Admin: convite e recuperação passam pela
    mesma montagem, e são justamente os que precisam CHEGAR."""
    entregues = []
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )
    envio()

    msg = entregues[-1]
    assert esperado in msg["Subject"]
    assert msg["Date"] and msg["Message-ID"]
    for parte in _texto_e_html(msg):
        assert parte["Content-Transfer-Encoding"] == "quoted-printable", (
            f"a parte {parte.get_content_type()} escapou do quoted-printable — "
            "metade da mensagem voltou a sair em base64"
        )


# --------------------------------------------------------------------------
# A parte HTML — e as armadilhas que ela traz junto
# --------------------------------------------------------------------------


def test_o_encoding_nao_depende_de_quanto_acento_o_texto_tem(capturada):
    """O `cte=` explícito existe para o texto que AINDA vai ser escrito.

    Sem ele, o `set_content` decide por heurística e a decisão muda com a
    proporção de acentos do corpo: pouco acento vira `quoted-printable`, texto
    curto acentuado vira `8bit` (que o serializador reescreve na saída) e corpo
    muito acentuado vira `base64` — o `MIME_BASE64_TEXT` da rodada anterior. As
    mensagens de hoje caem no lado bom por sorte; alguém reescrevendo uma frase
    amanhã não deveria mudar a pasta em que o e-mail cai.
    """
    denso = "Ação, você é convidação à revisão do orçamento não-padrão. " * 20
    msg = capturada(corpo=denso, html=f"<html><body><p>{denso}</p></body></html>")

    for parte in _texto_e_html(msg):
        assert parte["Content-Transfer-Encoding"] == "quoted-printable", (
            f"a parte {parte.get_content_type()} caiu na heurística do "
            "set_content e voltou para base64"
        )


def test_mensagem_simples_continua_sem_parte_html(capturada):
    """`send` sem `html=` é o primitivo e não inventa uma parte vazia."""
    msg = capturada()
    assert msg.get_content_type() == "text/plain"
    assert msg["Content-Transfer-Encoding"] == "quoted-printable"


@pytest.mark.parametrize("esperado,envio,link", ENVIOS_REAIS)
def test_o_mesmo_link_aparece_nas_duas_partes(capturada, monkeypatch, esperado, envio, link):
    """Quem lê texto e quem lê HTML tem de chegar no MESMO lugar."""
    entregues = []
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )
    envio()

    texto, html = _texto_e_html(entregues[-1])
    assert link in texto.get_content()
    assert link in html_lib.unescape(html.get_content())


@pytest.mark.parametrize("esperado,envio,link", ENVIOS_REAIS)
def test_as_duas_partes_dizem_a_mesma_coisa(capturada, monkeypatch, esperado, envio, link):
    """Guarda contra `MPART_ALT_DIFF`.

    A regra existe para pegar quem mostra uma coisa a quem lê HTML e outra a
    quem lê texto — o truque de esconder o conteúdo real do classificador, que
    costuma ler só a parte de texto. Aqui as duas partes saem da mesma chamada a
    `email_templates.corpo()`, e este teste é o que impede alguém de "melhorar"
    só um lado depois.
    """
    entregues = []
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )
    envio()

    texto, html = _texto_e_html(entregues[-1])
    visivel = html_lib.unescape(re.sub(r"<[^>]+>", " ", html.get_content()))
    visivel = " ".join(visivel.split())

    for linha in texto.get_content().splitlines():
        frase = linha.strip()
        if len(frase) < 25 or frase.startswith("http"):
            continue
        assert " ".join(frase.split()) in visivel, (
            f"a frase {frase!r} está no texto e não no HTML"
        )


@pytest.mark.parametrize("nome,montar", (
    ("senha", lambda: email_templates.recuperacao_de_senha("https://x/y", 30)),
    ("cadastro", lambda: email_templates.convite_de_cadastro("Ana", "https://x/y")),
    ("workspace", lambda: email_templates.convite_de_workspace("Casa", "Ana", "https://x/y")),
    ("teste", email_templates.teste_de_configuracao),
))
def test_html_nao_pede_nada_a_servidor_nenhum(nome, montar):
    """Zero recurso externo — e este teste cobre também o e-mail de teste do Admin.

    O Outlook bloqueia imagem remota por padrão (a mensagem chega quebrada), e o
    pedido a um terceiro no momento da leitura é sinal negativo por si só. É a
    porta por onde um pixel de rastreio entraria sem ninguém notar.
    """
    _, html = montar()
    assert "<img" not in html.lower()
    assert "src=" not in html.lower()
    assert "@import" not in html.lower()
    # Todo `http` do documento tem de apontar para o link da ação, nunca para um
    # asset. A comparação é pelo HOST parseado, e não por `startswith`: o prefixo
    # `https://x/y` casa também com `https://x/y.dominio-malicioso.com/pixel.gif`,
    # que é precisamente o que este teste existe para barrar. Foi o CodeQL quem
    # apontou (`py/incomplete-url-substring-sanitization`), e ele estava certo.
    host_do_link = urlparse("https://x/y").hostname
    for url in re.findall(r'https?://[^\s"\'<>]+', html):
        assert urlparse(url).hostname == host_do_link, (
            f"{nome}: o HTML carrega {url!r} de fora"
        )


def test_a_url_exibida_e_a_url_do_link(capturada):
    """Âncora que mostra um endereço e aponta para outro é regra de phishing.

    O botão pode ter rótulo em verbo ("Aceitar o convite"); o que não pode é um
    link cujo texto visível PARECE uma URL e leva a lugar diferente.
    """
    _, html = email_templates.convite_de_cadastro("Ana", "https://app.exemplo.com/r?a=1&b=2")
    for href, visivel in re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', html):
        if html_lib.unescape(visivel).strip().startswith("http"):
            assert html_lib.unescape(href) == html_lib.unescape(visivel).strip()


def test_nome_de_workspace_nao_escapa_para_dentro_do_html(capturada, monkeypatch):
    """O nome do espaço é dado que o USUÁRIO escolhe e vai parar no HTML."""
    entregues = []
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )
    EmailService.send_workspace_invite(
        "a@live.com", "<script>alert(1)</script>", "Ana & Bob", "https://x/y"
    )

    _, html = _texto_e_html(entregues[-1])
    conteudo = html.get_content()
    assert "<script>" not in conteudo
    assert "&lt;script&gt;" in conteudo
    assert "Ana &amp; Bob" in conteudo


# --------------------------------------------------------------------------
# Cabeçalhos: resposta que chega em alguém, e mensagem que se declara robô
# --------------------------------------------------------------------------


def test_reply_to_sai_quando_configurado(capturada, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.EMAIL_REPLY_TO", "suporte@exemplo.com"
    )
    assert capturada()["Reply-To"] == "suporte@exemplo.com"


def test_sem_reply_to_configurado_o_cabecalho_nao_existe(capturada):
    """Vazio omite o cabeçalho — e não emite um `Reply-To:` em branco, que é
    pior que nenhum: alguns clientes o exibem como destinatário."""
    assert capturada()["Reply-To"] is None


def test_mensagem_se_declara_automatica(capturada):
    """Sem isto, a resposta de férias de quem recebeu volta para o `noreply@`.

    Cada ciclo desses é um bounce, e bounce gasta reputação do domínio — o
    contrário exato do que este trabalho todo persegue.
    """
    msg = capturada()
    assert msg["Auto-Submitted"] == "auto-generated"
    assert msg["X-Auto-Response-Suppress"] == "OOF, AutoReply"


@pytest.mark.parametrize(
    "workspace,convidou",
    (
        ("Casa\r\nBcc: atacante@example.com", "Ana"),
        ("Casa", "Ana\r\nBcc: atacante@example.com"),
    ),
)
def test_dado_do_usuario_no_assunto_nao_injeta_cabecalho(
    capturada, monkeypatch, workspace, convidou
):
    """`EMAIL_FROM` era o único campo com defesa declarada contra injeção.

    Nome de workspace e nome de quem convida entram no `Subject` e vêm do
    usuário; um `\\r\\n` no meio acrescenta cabeçalhos que ninguém escreveu.
    """
    entregues = []
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )
    EmailService.send_workspace_invite("a@live.com", workspace, convidou, "https://x/y")

    msg = entregues[-1]
    # O endereço CONTINUA no assunto, como texto — é o nome que a pessoa
    # digitou, e censurá-lo não é papel nosso. O que não pode existir é o
    # cabeçalho que ele tentou criar.
    assert msg["Bcc"] is None
    assert "\r" not in str(msg["Subject"]) and "\n" not in str(msg["Subject"])
    # A prova real é a ida e volta pelo fio: serializar e reabrir. Se o `\r\n`
    # tivesse sobrevivido, o cabeçalho só nasceria aqui — na mensagem em
    # memória ele ainda seria texto dentro do `Subject`.
    relido = message_from_string(msg.as_string())
    assert relido["Bcc"] is None
    assert sorted(relido.keys()) == sorted(msg.keys())
