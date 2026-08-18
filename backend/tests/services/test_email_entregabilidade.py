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
from email.utils import parsedate_to_datetime

import pytest

from app.services.email_service import EmailService


@pytest.fixture(name="capturada")
def capturada_fixture(monkeypatch):
    """Intercepta no transporte: exercita o caminho real de `EmailService.send`."""
    entregues = []

    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr(
        "app.core.config.settings.EMAIL_FROM",
        "Controle Financeiro <noreply@notify.exemplo.com>",
    )
    monkeypatch.setattr(
        "app.services.smtp_transport.entrega",
        lambda msg, **kwargs: entregues.append(msg) or None,
    )

    def envia(assunto="Assunto", corpo="Corpo com acentuação: ação.") :
        EmailService.send("alguem@live.com", assunto, corpo)
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


@pytest.mark.parametrize(
    "envio,esperado",
    (
        (lambda: EmailService.send_password_reset("a@live.com", "https://x/y"), "senha"),
        (
            lambda: EmailService.send_registration_invite("a@live.com", "Ana", "https://x/y"),
            "Convite",
        ),
        (
            lambda: EmailService.send_workspace_invite("a@live.com", "Casa", "Ana", "https://x/y"),
            "Convite",
        ),
    ),
)
def test_todos_os_emails_do_sistema_saem_bem_formados(capturada, monkeypatch, envio, esperado):
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
    assert msg["Content-Transfer-Encoding"] == "quoted-printable"
