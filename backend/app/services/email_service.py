import logging
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Optional

from app.core.config import settings
from app.services import email_templates, smtp_transport
from app.services.smtp_transport import Endpoint

logger = logging.getLogger("app.email")


def _uma_linha(valor: str) -> str:
    """Tira CR e LF de um valor que vai para dentro de um cabeçalho.

    `Subject` recebe nome de workspace e nome de quem convidou — dado que o
    usuário escolhe. Um `\\r\\n` no meio deles acrescenta cabeçalhos que ninguém
    escreveu, e o `Bcc:` de um atacante é o exemplo clássico. `EMAIL_FROM` já
    tinha essa defesa declarada no `config.py`; estes campos não tinham nenhuma.
    """
    return valor.replace("\r", " ").replace("\n", " ").strip()


def _monta(
    remetente: str,
    to: str,
    subject: str,
    body: str,
    html: Optional[str] = None,
) -> EmailMessage:
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

    Faltavam ainda três coisas que só apareceram na segunda rodada:

    - **`Reply-To`.** O `From` é um `noreply@` num subdomínio de envio sem MX;
      quem responde recebe um erro de DNS, e nós nunca ficamos sabendo que
      alguém tentou falar conosco.
    - **`Auto-Submitted` (RFC 3834) e `X-Auto-Response-Suppress`.** Dizem que a
      mensagem é de sistema. Sem eles, a resposta automática de férias de quem
      recebeu volta para um endereço que não existe, e cada ciclo desses gasta
      reputação do domínio. O segundo cabeçalho é lido pelo Outlook.
    - **Uma parte HTML.** `text/plain` puro com uma URL de token solta no corpo
      é a forma de um phishing; nenhum produto transacional real manda assim.

    `List-Unsubscribe` ficou DE FORA de propósito: ele é de mala direta, e estas
    mensagens são transacionais — reset de senha e convite que alguém pediu. As
    regras de bulk sender do Gmail e do Yahoo as isentam, e oferecer descadastro
    num "redefinir sua senha" sinaliza marketing ao classificador.
    """
    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = _uma_linha(to)
    msg["Subject"] = _uma_linha(subject)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=parseaddr(remetente)[1].rpartition("@")[2] or None)
    if settings.EMAIL_REPLY_TO:
        msg["Reply-To"] = settings.EMAIL_REPLY_TO
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
    # `quoted-printable`, e não o base64 que o `set_content` escolhe sozinho para
    # texto com acento: o corpo continua legível no fonte da mensagem, como o de
    # qualquer cliente de e-mail de verdade. Base64 num texto curto é exatamente
    # o formato de quem tem algo a esconder do classificador.
    msg.set_content(body, cte="quoted-printable")
    if html is not None:
        # O `cte` vale para as DUAS partes. Sem ele aqui, a parte HTML — que tem
        # acento como qualquer outra — volta a sair em base64 e reintroduz
        # exatamente o defeito que a rodada anterior corrigiu, só que na metade
        # da mensagem que ninguém pensa em conferir.
        msg.add_alternative(html, subtype="html", cte="quoted-printable")
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
        html: Optional[str] = None,
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
            html,
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
        texto, html = email_templates.recuperacao_de_senha(
            reset_link, settings.RESET_TOKEN_EXPIRES_MINUTES
        )
        EmailService.send(
            to,
            "Recuperação de senha — Controle Financeiro",
            texto,
            html=html,
        )

    @staticmethod
    def send_workspace_invite(to: str, workspace_name: str, invited_by: str, accept_link: str) -> None:
        texto, html = email_templates.convite_de_workspace(
            workspace_name, invited_by, accept_link
        )
        EmailService.send(
            to,
            f"Convite para o workspace \"{workspace_name}\"",
            texto,
            html=html,
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
        texto, html = email_templates.convite_de_cadastro(invited_by, register_link)
        EmailService.send(
            to,
            "Convite para o Controle Financeiro",
            texto,
            html=html,
        )
