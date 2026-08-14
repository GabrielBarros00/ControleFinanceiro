"""Contrato de IP real entre cloudflared, nginx e o backend."""

import ipaddress
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NGINX = ROOT / "frontend" / "nginx.conf"
DOCKERFILE = ROOT / "frontend" / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
DEPLOY_GUIDE = ROOT / "docs" / "deploy-vps.md"


def test_cloudflare_ip_exige_container_e_porta_interna():
    config = NGINX.read_text(encoding="utf-8")

    assert "geo $cloudflared_source_trusted" in config
    assert "172.31.255.2 1;" in config
    assert (
        'map "$cloudflared_source_trusted:$server_port:$http_cf_connecting_ip"'
        " $trusted_client_ip"
    ) in config
    assert "~^1:8080:" in config
    assert "listen 80;" in config
    assert "listen 8080;" in config


def test_porta_interna_rejeita_origem_que_nao_e_cloudflared():
    config = NGINX.read_text(encoding="utf-8")

    assert '"8080:0" 1;' in config
    assert "if ($reject_untrusted_tunnel_request)" in config
    assert "return 403;" in config


def test_deploy_sem_cloudflare_cai_na_conexao_direta():
    config = NGINX.read_text(encoding="utf-8")

    assert "default $remote_addr;" in config
    assert "default $scheme;" in config
    assert config.count(
        "proxy_set_header X-Forwarded-For $trusted_client_ip;"
    ) == 2
    assert config.count(
        "proxy_set_header X-Forwarded-Proto $trusted_forwarded_proto;"
    ) == 2


def test_nginx_nao_preserva_x_forwarded_for_do_cliente():
    config_ativa = "\n".join(
        line for line in NGINX.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )

    assert "$proxy_add_x_forwarded_for" not in config_ativa
    assert "$http_x_forwarded_for" not in config_ativa


def test_imagem_usa_configuracao_estatica_sem_segredo_de_header():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY nginx.conf /etc/nginx/conf.d/default.conf" in dockerfile
    assert "EXPOSE 80\n" in dockerfile
    assert "EXPOSE 80 8080" not in dockerfile
    assert "envsubst" not in dockerfile.lower()
    assert "CLOUDFLARE_ORIGIN_SECRET" not in dockerfile


def test_compose_oferece_cloudflared_opcional_e_isolado():
    compose = COMPOSE.read_text(encoding="utf-8")

    assert 'profiles: ["cloudflare"]' in compose
    assert "image: cloudflare/cloudflared:latest" in compose
    assert "pull_policy: always" in compose
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:-}" in compose
    assert "command: tunnel --no-autoupdate run" in compose
    assert '"${BIND_ADDR:-0.0.0.0}:${HTTP_PORT:-80}:80"' in compose
    assert "ipv4_address: 172.31.255.2" in compose
    assert "subnet: 172.31.255.0/29" in compose
    assert "cloudflare_edge:" in compose


SUB_REDE_DO_TUNNEL = ipaddress.ip_network("172.31.255.0/29")
IP_DO_CLOUDFLARED = "172.31.255.2"


def _servicos_do_compose() -> dict[str, str]:
    """Nome -> corpo de cada serviço, recortado do bloco `services:`."""
    servicos: dict[str, list[str]] = {}
    atual: str | None = None
    dentro = False

    for linha in COMPOSE.read_text(encoding="utf-8").splitlines():
        if linha.startswith("services:"):
            dentro = True
            continue
        if not dentro:
            continue
        if linha and not linha.startswith(" "):
            break  # chegou em `volumes:`/`networks:`, na raiz do arquivo
        cabecalho = re.fullmatch(r" {2}([\w.-]+):[ \t]*", linha)
        if cabecalho:
            atual = cabecalho.group(1)
            servicos[atual] = []
        elif atual is not None:
            servicos[atual].append(linha)

    return {nome: "\n".join(corpo) for nome, corpo in servicos.items()}


def _endereco_fixo_na_rede_do_tunnel(corpo: str) -> str | None:
    bloco = re.search(
        r"^ {6}cloudflare_edge:[ \t]*$\n((?:^ {8}\S.*$\n?)*)",
        corpo,
        re.MULTILINE,
    )
    if bloco is None:
        return None
    endereco = re.search(r"ipv4_address:\s*(\S+)", bloco.group(1))
    return endereco.group(1) if endereco else None


def test_todo_servico_da_rede_do_tunnel_tem_endereco_fixo():
    """Endereço dinâmico nessa rede é deploy quebrado, não detalhe de estilo.

    A `cloudflare_edge` é uma /29: livres, só .2 a .6 (o .1 é o gateway). O IPAM
    do Docker entrega o primeiro livre — o .2 — a quem sobe sem pedir endereço,
    e o `cloudflared` sobe por último, porque espera o healthcheck do frontend.
    Foi o que aconteceu no primeiro deploy com Tunnel: o frontend tomou o .2, o
    `cloudflared` pediu o mesmo .2 fixo e morreu em
    "failed to set up container networking: Address already in use", com todo o
    resto do stack `healthy` e o app inalcançável de fora.

    O .2 é endereço de contrato (o `geo` do nginx.conf), não pode mudar de dono.
    """
    na_rede = {
        nome: corpo
        for nome, corpo in _servicos_do_compose().items()
        if "cloudflare_edge:" in corpo
    }
    assert set(na_rede) == {"frontend", "cloudflared"}

    enderecos: dict[str, str] = {}
    for nome, corpo in na_rede.items():
        endereco = _endereco_fixo_na_rede_do_tunnel(corpo)
        assert endereco is not None, (
            f"`{nome}` entra na cloudflare_edge sem ipv4_address: o IPAM vai"
            f" dar a ele o {IP_DO_CLOUDFLARED} e o Tunnel não sobe."
        )
        assert ipaddress.ip_address(endereco) in SUB_REDE_DO_TUNNEL
        enderecos[nome] = endereco

    assert enderecos["cloudflared"] == IP_DO_CLOUDFLARED
    assert len(set(enderecos.values())) == len(enderecos)


def test_guia_deploy_documenta_tunnel_e_limite_de_confianca():
    guia = DEPLOY_GUIDE.read_text(encoding="utf-8")

    assert "COMPOSE_PROFILES=cloudflare" in guia
    assert "http://frontend:8080" in guia
    assert "172.31.255.2" in guia
    assert "recebe `403`" in guia
    assert "BIND_ADDR=127.0.0.1" in guia
    assert "7844" in guia
    assert "chmod 600 .env" in guia
    assert "Remove visitor IP headers" in guia


def test_abordagem_antiga_de_segredo_foi_removida():
    arquivos = [NGINX, DOCKERFILE, COMPOSE, ROOT / ".env.example", ROOT / "SETUP.md"]

    for arquivo in arquivos:
        conteudo = arquivo.read_text(encoding="utf-8")
        assert "CLOUDFLARE_ORIGIN_SECRET" not in conteudo
        assert "X-Origin-Verify" not in conteudo
