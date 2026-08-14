"""A descoberta automática da rota SMTP (`app/services/smtp_transport.py`).

O caso que originou o módulo está em `test_cai_para_a_alternativa_...`: em
produção o provedor do VPS bloqueia a saída em 25, 465 e 587, o provedor de
e-mail atende em 2587, e a única pista era um `TimeoutError` de socket vinte
segundos depois de clicar em "enviar teste".

Os outros testes existem porque "tentar outra porta" é perigoso quando aplicado
sem critério — senha errada repetida cinco vezes, e-mail duplicado, credencial
em texto claro. Cada um fixa uma das fronteiras.
"""
import smtplib
from dataclasses import dataclass, field

import pytest

from app.services import smtp_transport
from app.services.email_service import EmailService


@dataclass
class Servidor:
    """Servidor de mentira: obedece ao roteiro e registra o que aconteceu."""

    portas_abertas: set[int]
    anuncia_starttls: bool = True
    credencial_invalida: bool = False
    cai_durante_o_envio: bool = False

    conexoes: list[tuple[int, bool]] = field(default_factory=list)
    starttls_em: list[int] = field(default_factory=list)
    logins: list[tuple[int, bool]] = field(default_factory=list)
    entregues: list[int] = field(default_factory=list)
    sondagens: int = 0

    def cifrada(self, porta: bool) -> bool:
        return porta in self.starttls_em


class _Conexao:
    def __init__(self, servidor: Servidor, porta: int, ssl_implicito: bool):
        self.servidor = servidor
        self.porta = porta
        self.ssl_implicito = ssl_implicito
        if porta not in servidor.portas_abertas:
            raise TimeoutError("timed out")
        servidor.conexoes.append((porta, ssl_implicito))

    def ehlo(self, *_args):
        return (250, b"ok")

    def has_extn(self, nome: str) -> bool:
        return nome == "starttls" and self.servidor.anuncia_starttls

    def starttls(self, *, context=None):
        self.servidor.starttls_em.append(self.porta)

    def login(self, usuario, senha):
        cifrada = self.ssl_implicito or self.porta in self.servidor.starttls_em
        self.servidor.logins.append((self.porta, cifrada))
        if self.servidor.credencial_invalida:
            raise smtplib.SMTPAuthenticationError(535, b"Invalid API key")

    def send_message(self, msg):
        if self.servidor.cai_durante_o_envio:
            raise smtplib.SMTPServerDisconnected("conexão perdida no DATA")
        self.servidor.entregues.append(self.porta)

    def quit(self):
        return (221, b"bye")

    def close(self):
        pass


@pytest.fixture(autouse=True)
def rota_limpa():
    """Cada teste começa sem memória de rota — e não deixa memória para o próximo."""
    smtp_transport.esquece_rota()
    yield
    smtp_transport.esquece_rota()


@pytest.fixture(name="monta")
def monta_fixture(monkeypatch):
    def _monta(
        portas_abertas,
        *,
        porta_configurada: int = 587,
        smtp_tls: bool = True,
        com_senha: bool = True,
        **roteiro,
    ) -> Servidor:
        servidor = Servidor(portas_abertas=set(portas_abertas), **roteiro)

        monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")
        monkeypatch.setattr("app.core.config.settings.SMTP_PORT", porta_configurada)
        monkeypatch.setattr("app.core.config.settings.SMTP_TLS", smtp_tls)
        monkeypatch.setattr("app.core.config.settings.EMAIL_FROM", "eu@exemplo.com")
        monkeypatch.setattr(
            "app.core.config.settings.SMTP_USER", "api" if com_senha else None
        )
        monkeypatch.setattr(
            "app.core.config.settings.SMTP_PASSWORD", "chave" if com_senha else None
        )

        def sonda(host, porta, timeout):
            servidor.sondagens += 1
            return porta in servidor.portas_abertas

        monkeypatch.setattr(smtp_transport, "_resolve", lambda host: True)
        monkeypatch.setattr(smtp_transport, "_alcancavel", sonda)
        monkeypatch.setattr(
            smtplib, "SMTP",
            lambda host, porta, timeout=None: _Conexao(servidor, porta, False),
        )
        monkeypatch.setattr(
            smtplib, "SMTP_SSL",
            lambda host, porta, timeout=None, context=None: _Conexao(servidor, porta, True),
        )
        return servidor

    return _monta


def envia(**kwargs):
    return EmailService.send("alguem@exemplo.com", "assunto", "corpo", **kwargs)


# --------------------------------------------------------------------------
# O caminho feliz e o caso que originou o módulo
# --------------------------------------------------------------------------

def test_usa_a_porta_configurada_quando_ela_responde(monta):
    """Configuração que funciona não pode virar exploração de portas."""
    servidor = monta({587})

    rota = envia(raise_on_error=True)

    assert servidor.entregues == [587]
    assert [porta for porta, _ in servidor.conexoes] == [587]
    assert rota.porta == 587


def test_cai_para_a_alternativa_quando_a_porta_configurada_esta_bloqueada(monta):
    """A produção inteira: 25/465/587 bloqueadas na saída, provedor atende na 2587."""
    servidor = monta({2587, 2465})

    rota = envia(raise_on_error=True)

    assert servidor.entregues == [2587], (
        "com 587 bloqueada pelo provedor do VPS, o e-mail tinha de sair pela "
        "porta alternativa — foi este timeout que deixou a produção sem e-mail"
    )
    assert rota.porta == 2587
    assert 587 not in [porta for porta, _ in servidor.conexoes]


def test_porta_de_ssl_implicito_abre_a_conexao_ja_cifrada(monta):
    """465/2465 é SMTPS: TLS no primeiro byte, sem STARTTLS."""
    servidor = monta({465}, porta_configurada=465)

    envia(raise_on_error=True)

    assert servidor.conexoes == [(465, True)]
    assert servidor.starttls_em == []
    assert servidor.logins == [(465, True)]


# --------------------------------------------------------------------------
# As fronteiras do "tentar outra porta"
# --------------------------------------------------------------------------

def test_credencial_recusada_nao_e_repetida_em_outras_portas(monta):
    """Senha errada é a mesma resposta em qualquer porta.

    Sem esta fronteira, uma chave de API vencida viraria cinco tentativas de
    login no provedor a cada e-mail — que é como se ganha um bloqueio de conta.
    """
    servidor = monta({25, 465, 587, 2465, 2525, 2587}, credencial_invalida=True)

    with pytest.raises(smtplib.SMTPAuthenticationError):
        envia(raise_on_error=True)

    assert len(servidor.logins) == 1, f"tentou logar {len(servidor.logins)}x"
    assert servidor.entregues == []


def test_queda_depois_do_envio_nao_reenvia_por_outra_porta(monta):
    """Entregue-e-perdi-a-confirmação não pode virar e-mail duplicado."""
    servidor = monta({587, 2587}, cai_durante_o_envio=True)

    with pytest.raises(smtp_transport.EntregaIncerta):
        envia(raise_on_error=True)

    assert [porta for porta, _ in servidor.conexoes] == [587], (
        "tentou outra porta depois de a mensagem já ter ido para o servidor"
    )


def test_recusa_mandar_a_senha_em_texto_claro(monta):
    """Servidor sem STARTTLS e senha na mão: a rota é descartada, não degradada."""
    servidor = monta({587}, anuncia_starttls=False)

    with pytest.raises(smtp_transport.SemRota):
        envia(raise_on_error=True)

    assert servidor.logins == [], "a credencial saiu em texto claro"


def test_sobe_para_starttls_mesmo_com_smtp_tls_desligado_quando_ha_senha(monta):
    """`SMTP_TLS=False` com senha no `.env` é engano, não pedido de texto claro."""
    servidor = monta({587}, smtp_tls=False)

    envia(raise_on_error=True)

    assert servidor.starttls_em == [587]
    assert servidor.logins == [(587, True)]


# --------------------------------------------------------------------------
# Memória: descobrir uma vez, não a cada mensagem
# --------------------------------------------------------------------------

def test_rota_detectada_vale_para_os_proximos_envios(monta):
    servidor = monta({2587})

    envia(raise_on_error=True)
    sondagens_da_descoberta = servidor.sondagens
    envia(raise_on_error=True)

    assert servidor.entregues == [2587, 2587]
    assert servidor.sondagens == sondagens_da_descoberta, (
        "sondou de novo uma rota que já era conhecida"
    )


def test_espera_apos_falha_total_para_nao_sondar_a_cada_mensagem(monta):
    """SMTP fora do ar não pode custar a sondagem completa por convite enviado."""
    servidor = monta(set())

    envia()  # best-effort: não levanta
    sondagens_da_descoberta = servidor.sondagens
    assert sondagens_da_descoberta > 0

    envia()
    assert servidor.sondagens == sondagens_da_descoberta


def test_o_botao_de_teste_ignora_a_espera_e_redescobre(monta):
    """Quem clica em "enviar teste" acabou de mexer no firewall e quer o agora."""
    servidor = monta(set())
    envia()
    servidor.portas_abertas.add(2587)

    rota = envia(raise_on_error=True, redescobrir_rota=True)

    assert rota.porta == 2587
    assert servidor.entregues == [2587]


def test_rota_memorizada_que_cai_e_redescoberta_na_hora(monta):
    """Firewall novo derruba a porta de ontem: descobre outra, sem esperar."""
    servidor = monta({587, 2587})
    envia(raise_on_error=True)

    servidor.portas_abertas.remove(587)
    rota = envia(raise_on_error=True)

    assert rota.porta == 2587
    assert servidor.entregues == [587, 2587]


# --------------------------------------------------------------------------
# O diagnóstico
# --------------------------------------------------------------------------

def test_bloqueio_total_de_saida_explica_o_que_fazer(monta):
    """A mensagem é o produto aqui: `timed out` não dizia nada a ninguém."""
    monta(set())

    with pytest.raises(smtp_transport.SemRota) as erro:
        envia(raise_on_error=True, redescobrir_rota=True)

    detalhe = str(erro.value)
    assert "2587" in detalhe and "2465" in detalhe
    assert "bloqueia" in detalhe.lower()


def test_host_que_nao_resolve_nao_e_confundido_com_porta_bloqueada(monta, monkeypatch):
    monta({587})
    monkeypatch.setattr(smtp_transport, "_resolve", lambda host: False)

    with pytest.raises(smtp_transport.SemRota) as erro:
        envia(raise_on_error=True, redescobrir_rota=True)

    assert "DNS" in str(erro.value)


def test_falha_de_rota_continua_best_effort_para_quem_nao_pediu_erro(monta):
    """O convite já está no banco; a entrega é aviso, não transação."""
    monta(set())
    assert envia() is None
