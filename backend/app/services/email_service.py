import logging
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Optional

from app.core.config import settings
from app.services import smtp_transport
from app.services.smtp_transport import Endpoint

logger = logging.getLogger("app.email")


def _monta(remetente: str, to: str, subject: str, body: str) -> EmailMessage:
    """Monta a mensagem com o que um e-mail legítimo tem — e o nosso não tinha.

    A mensagem que este serviço entregava saía com SEIS cabeçalhos: From, To,
    Subject e os três de MIME. Faltavam os dois que a RFC 5322 pede (`Date` é
    OBRIGATÓRIO, `Message-ID` é SHOULD), e o corpo inteiro ia em base64. Os três
    são regra conhecida de filtro antispam — `MISSING_DATE`, `MISSING_MID` e
    `MIME_BASE64_TEXT` no SpamAssassin —, e a soma deles cai na caixa de spam de
    um destinatário que aplica a régua com rigor, mesmo com SPF, DKIM e DMARC
    passando. Foi o que aconteceu no `@live.com`.

    O domínio do `Message-ID` é o do REMETENTE, e isso importa: o padrão do
    `make_msgid` é o hostname da máquina, que dentro de um container é o ID
    aleatório do Docker — `<...@3f2a9c1b4d5e>`. Um Message-ID que não casa com
    domínio nenhum é, por si, sinal de robô mal configurado.
    """
    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=parseaddr(remetente)[1].rpartition("@")[2] or None)
    # `quoted-printable`, e não o base64 que o `set_content` escolhe sozinho para
    # texto com acento: o corpo continua legível no fonte da mensagem, como o de
    # qualquer cliente de e-mail de verdade. Base64 num texto curto é exatamente
    # o formato de quem tem algo a esconder do classificador.
    msg.set_content(body, cte="quoted-printable")
    return msg


class EmailService:
    """Envio de emails transacionais via SMTP.

    Sem SMTP_HOST configurado (ambiente de desenvolvimento), o conteúdo é
    apenas logado — o link aparece no console do backend.

    O *como* falar com o servidor (porta e TLS) não está aqui: fica em
    `smtp_transport`, que o descobre e memoriza. Este módulo cuida do *o quê* —
    remetente, assunto, corpo — e da promessa de best-effort.
    """

    @staticmethod
    def send(
        to: str,
        subject: str,
        body: str,
        raise_on_error: bool = False,
        *,
        redescobrir_rota: bool = False,
    ) -> Optional[Endpoint]:
        """Envia um e-mail e devolve por qual rota ele saiu (ou `None`).

        `raise_on_error` existe para UM chamador: o teste de SMTP da tela de
        Admin (ADR 0026). Todos os outros querem o comportamento best-effort — o
        convite ou o token já foi persistido, e uma falha de entrega não pode
        derrubar a requisição nem revelar, pelo erro ou pelo tempo de resposta,
        quais endereços existem.

        No diagnóstico é o contrário: engolir a exceção faria o botão "enviar
        e-mail de teste" responder "enviado" com o SMTP recusando a conexão, que
        é precisamente o que o botão existe para descobrir.
        """
        if not settings.SMTP_HOST:
            logger.warning(
                "SMTP não configurado — email não enviado.\nPara: %s\nAssunto: %s\n%s",
                to, subject, body,
            )
            return None

        msg = _monta(
            settings.EMAIL_FROM or settings.SMTP_USER or "noreply@example.com",
            to,
            subject,
            body,
        )

        try:
            return smtp_transport.entrega(msg, redescobrir=redescobrir_rota)
        except Exception:
            logger.exception("Falha ao enviar email para %s (assunto: %s)", to, subject)
            if raise_on_error:
                raise
            return None

    @staticmethod
    def send_password_reset(to: str, reset_link: str) -> None:
        EmailService.send(
            to,
            "Recuperação de senha — Controle Financeiro",
            "Olá,\n\n"
            "Recebemos um pedido para redefinir a sua senha.\n"
            f"Acesse o link abaixo (válido por {settings.RESET_TOKEN_EXPIRES_MINUTES} minutos):\n\n"
            f"{reset_link}\n\n"
            "Se você não pediu a redefinição, ignore este email.\n",
        )

    @staticmethod
    def send_workspace_invite(to: str, workspace_name: str, invited_by: str, accept_link: str) -> None:
        EmailService.send(
            to,
            f"Convite para o workspace \"{workspace_name}\"",
            f"Olá,\n\n{invited_by} convidou você para participar do workspace "
            f"\"{workspace_name}\" no Controle Financeiro.\n\n"
            f"Acesse: {accept_link}\n",
        )

    @staticmethod
    def send_registration_invite(to: str, invited_by: str, register_link: str) -> None:
        """Convite para CRIAR CONTA — não é o de workspace (ADR 0026).

        Texto diferente porque a promessa é outra: aqui a pessoa ainda não existe
        no sistema e vai criar a própria conta e o próprio espaço. O convite de
        workspace chama para dentro de uma casa que já existe, e usar a mesma
        mensagem nos dois faria alguém aceitar esperando ver as finanças da
        família e cair num espaço vazio — ou o contrário.
        """
        EmailService.send(
            to,
            "Convite para o Controle Financeiro",
            f"Olá,\n\n{invited_by} convidou você para usar o Controle Financeiro.\n\n"
            f"Crie sua conta em: {register_link}\n\n"
            "O link é pessoal e tem prazo de validade.\n",
        )
