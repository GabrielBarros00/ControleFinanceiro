"""Contrato de IP real entre cloudflared, nginx e o backend."""

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
