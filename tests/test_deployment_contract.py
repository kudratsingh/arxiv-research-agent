"""Static production-boundary contracts for the Hetzner stack (ADR 0054)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = (ROOT / "docker-compose.yml").read_text()
PROD_COMPOSE = (
    ROOT / "deploy" / "hetzner" / "compose.prod.yml"
).read_text()
CADDYFILE = (ROOT / "deploy" / "hetzner" / "Caddyfile").read_text()
ENV_EXAMPLE = (
    ROOT / "deploy" / "hetzner" / "env.example"
).read_text()


def test_local_host_ports_default_to_loopback() -> None:
    assert (
        "${APP_BIND_ADDRESS:-127.0.0.1}:${APP_PORT:-8000}:8000"
        in BASE_COMPOSE
    )
    assert (
        "${WEB_BIND_ADDRESS:-127.0.0.1}:${WEB_PORT:-3000}:3000"
        in BASE_COMPOSE
    )


def test_database_password_is_not_hard_coded() -> None:
    assert "postgresql://arxiv:arxiv@" not in BASE_COMPOSE
    assert "POSTGRES_PASSWORD: arxiv" not in BASE_COMPOSE
    assert "${POSTGRES_PASSWORD:-arxiv}" in BASE_COMPOSE
    assert "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}" in (
        PROD_COMPOSE
    )


def test_production_only_publishes_the_tls_edge() -> None:
    assert PROD_COMPOSE.count("ports: !reset []") == 2
    assert '      - "${CADDY_HTTP_PORT:-80}:80"' in PROD_COMPOSE
    assert '      - "${CADDY_HTTPS_PORT:-443}:443"' in PROD_COMPOSE
    assert "6379:6379" not in PROD_COMPOSE
    assert "5432:5432" not in PROD_COMPOSE


def test_production_enforces_both_authentication_layers() -> None:
    assert 'ENABLE_API_AUTH: "true"' in PROD_COMPOSE
    assert "API_KEYS: web:${WEB_API_KEY:?" in PROD_COMPOSE
    assert "ARXIV_API_KEY: ${WEB_API_KEY:?" in PROD_COMPOSE
    assert "basic_auth" in CADDYFILE
    assert "{$APP_PASSWORD_HASH}" in CADDYFILE
    assert "plaintext" not in CADDYFILE.lower()


def test_caddy_owns_https_and_persists_its_certificates() -> None:
    assert "image: caddy:2.11.4-alpine" in PROD_COMPOSE
    assert "{$APP_DOMAIN}" in CADDYFILE
    assert "reverse_proxy web:3000" in CADDYFILE
    assert "caddy-data:/data" in PROD_COMPOSE
    assert "caddy-config:/config" in PROD_COMPOSE
    assert "Strict-Transport-Security" in CADDYFILE


def test_production_env_template_contains_no_deployable_secret() -> None:
    required_empty = {
        "ANTHROPIC_API_KEY=",
        "APP_DOMAIN=",
        "ACME_EMAIL=",
        "APP_USERNAME=",
        "APP_PASSWORD_HASH=''",
        "WEB_API_KEY=",
        "POSTGRES_PASSWORD=",
    }
    assert required_empty <= set(ENV_EXAMPLE.splitlines())
    assert "sk-ant-" not in ENV_EXAMPLE
