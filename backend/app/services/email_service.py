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
    def send(to: str, subject: str, body: str) -> None:
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

        # Best-effort: falha de SMTP não pode derrubar a request (o convite/
        # token já foi persistido) nem revelar emails via erro/timing
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_TLS:
                    smtp.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        except Exception:
            logger.exception("Falha ao enviar email para %s (assunto: %s)", to, subject)

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
