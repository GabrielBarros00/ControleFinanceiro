import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("app.email")


class EmailService:
    """Envio de emails transacionais via SMTP.

    Sem SMTP_HOST configurado (ambiente de desenvolvimento), o conteúdo é
    apenas logado — o link aparece no console do backend.
    """

    @staticmethod
    def send(to: str, subject: str, body: str, raise_on_error: bool = False) -> None:
        """Envia um e-mail.

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
            return

        msg = EmailMessage()
        msg["From"] = settings.EMAIL_FROM or settings.SMTP_USER or "noreply@example.com"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_TLS:
                    smtp.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        except Exception:
            logger.exception("Falha ao enviar email para %s (assunto: %s)", to, subject)
            if raise_on_error:
                raise

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
