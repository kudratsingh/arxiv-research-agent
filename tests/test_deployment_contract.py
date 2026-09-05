"""Static production-boundary contracts for the Hetzner stack (ADR 0054)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings

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


class TestTheComposeEnumerationForwardsWhatTheHostSets:
    """WO-C4. `environment:` here is an allowlist, and it was missing three.

    `docker-compose.yml` names every variable the `app` container gets.
    That is a deliberate choice — the container's configuration is
    readable in one place — but it has a failure mode nobody sees: a
    variable absent from the list does not reach the container however
    loudly the host exported it, and Compose says nothing.

    WO-C3 found the first instance: `LOG_PRINCIPAL_SALT` was absent, so
    a Compose deployment drew a per-process salt whatever the operator
    set, and `principal_hash` could not join a principal's lines across
    containers. Checking the rest of the list turned up two more of the
    same shape — a spend ceiling that could not be lowered and a log
    level that could not be raised.
    """

    @pytest.mark.parametrize(
        "declaration",
        [
            # The one WO-C3 measured. Blank is unset rather than a salt
            # (`Settings._blank_salt_is_unset`), so `:-` with nothing on
            # the host is the per-process behaviour the demo always had.
            "LOG_PRINCIPAL_SALT: ${LOG_PRINCIPAL_SALT:-}",
            # A cost guard an operator could not tighten: the production
            # overlay forwarded this and the base stack did not.
            "MAX_COST_USD: ${MAX_COST_USD:-2.00}",
            # Was pinned to `INFO`, which silently outranked
            # `LOG_LEVEL=DEBUG docker compose up`.
            "LOG_LEVEL: ${LOG_LEVEL:-INFO}",
        ],
    )
    def test_the_variable_is_forwarded_from_the_host(
        self, declaration: str
    ) -> None:
        assert declaration in BASE_COMPOSE, (
            f"`docker-compose.yml` must forward {declaration.split(':')[0]} "
            "from the host. The environment block is exhaustive: a "
            "variable missing from it is silently dropped, not defaulted "
            "by omission."
        )

    def test_the_compose_defaults_are_the_shipped_field_defaults(self) -> None:
        """A `:-` default in Compose is a second copy of a default.

        Two copies drift, and this pair drifts silently: the operator
        reads `src/config.py`, gets the container's number, and the two
        disagree with nobody to say so. Pinned against the model rather
        than against a literal so the check follows the field.
        """
        shipped = Settings()
        assert f"MAX_COST_USD: ${{MAX_COST_USD:-{shipped.max_cost_usd:.2f}}}" in (
            BASE_COMPOSE
        )
        assert f"LOG_LEVEL: ${{LOG_LEVEL:-{shipped.log_level}}}" in BASE_COMPOSE

    def test_no_compose_file_pins_a_literal_salt(self) -> None:
        """Every declaration of the salt interpolates; none carries a value.

        Production is the deployment the missing salt was actually
        hurting — it is the stack that runs more than one process — and
        it inherits the base forwarding rather than needing a copy. The
        durable rule is the one stated here, which survives a later
        hardening (`:?` to make the salt mandatory in production) and
        covers the overlays too: a salt committed to the repository is
        a salt every reader of the repository has, which is worse than
        no salt at all because it looks like one.
        """
        declarations: list[tuple[Path, str]] = []
        for path in sorted(ROOT.glob("**/*compose*.y*ml")):
            if "node_modules" in path.parts:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.strip().partition(":")
                if sep and key == "LOG_PRINCIPAL_SALT":
                    declarations.append((path, value.strip()))

        assert declarations, (
            "no compose file declares LOG_PRINCIPAL_SALT — the base stack "
            "must forward it, or this check has quietly become a no-op."
        )
        for path, value in declarations:
            assert value.startswith("${LOG_PRINCIPAL_SALT"), (
                f"{path.relative_to(ROOT)} pins a salt value ({value!r}). "
                "It must interpolate from the host: a salt in the "
                "repository is a salt every reader of it has."
            )
