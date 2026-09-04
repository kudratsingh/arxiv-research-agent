"""API guardrails + deploy hygiene (ADR 0042).

Pure-unit coverage for the pieces the HTTPX suites can't reach
cheaply: the Plan schema bounds as model validation, the uvicorn
graceful-shutdown wiring in `serve.py`, the Postgres pool's
server-side timeouts + purge-enabling indexes, and the shipped
docker-compose contract (CORS allowlist, auth pass-through,
bounded drain) that a browser-level e2e would otherwise be needed
to regress.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from src.api.schemas import (
    MAX_PLAN_ITEM_LEN,
    MAX_PLAN_ITEMS,
    Plan,
    ReviewRequest,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

_REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPlanBounds:
    def test_plan_at_the_caps_validates(self) -> None:
        plan = Plan(
            sub_questions=["s" * MAX_PLAN_ITEM_LEN] * MAX_PLAN_ITEMS,
            search_queries=["q" * MAX_PLAN_ITEM_LEN] * MAX_PLAN_ITEMS,
        )
        assert len(plan.search_queries) == MAX_PLAN_ITEMS

    def test_too_many_search_queries_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Plan(search_queries=["q"] * (MAX_PLAN_ITEMS + 1))

    def test_too_many_sub_questions_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Plan(sub_questions=["s"] * (MAX_PLAN_ITEMS + 1))

    def test_oversized_item_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Plan(search_queries=["q" * (MAX_PLAN_ITEM_LEN + 1)])

    def test_review_request_carries_the_same_bounds(self) -> None:
        # The HITL revise path is the attack surface — the bound must
        # hold through the request envelope, not just the bare model.
        with pytest.raises(ValidationError):
            ReviewRequest.model_validate(
                {
                    "action": "revise",
                    "plan": {
                        "sub_questions": [],
                        "search_queries": ["q"] * 2000,
                    },
                }
            )

    def test_planner_shaped_plan_validates(self) -> None:
        # What the planner actually emits: 2-6 short items per list.
        plan = Plan(
            sub_questions=["what is X", "how does Y compare"],
            search_queries=["X survey", "Y benchmarks", "X vs Y"],
        )
        assert plan.sub_questions


class TestServeGracefulShutdown:
    def test_uvicorn_run_gets_bounded_graceful_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without `timeout_graceful_shutdown`, uvicorn waits forever
        on open SSE connections and the lifespan cleanup never runs
        on SIGTERM (ADR 0042)."""
        import src.api.serve as serve_module

        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            serve_module.uvicorn,
            "run",
            lambda *args, **kwargs: captured.update(kwargs),
        )
        serve_module.main()
        assert (
            captured["timeout_graceful_shutdown"]
            == serve_module.GRACEFUL_SHUTDOWN_TIMEOUT_SEC
        )
        assert serve_module.GRACEFUL_SHUTDOWN_TIMEOUT_SEC == 10


class TestPostgresPoolTimeouts:
    def test_pool_kwargs_carry_server_side_timeouts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lock-blocked query without `statement_timeout` holds its
        executor thread forever (ADR 0042); the options must reach
        the pool's connection kwargs."""
        import src.tools.postgres_pool as pool_module

        captured: dict[str, Any] = {}

        class FakePool:
            def __init__(self, url: str, **kwargs: Any) -> None:
                captured.update(kwargs)

            def open(self, wait: bool = True, timeout: float = 0.0) -> None:
                return None

        monkeypatch.setattr(pool_module, "ConnectionPool", FakePool)
        pool_module._make_pool("postgresql://u:p@h:5432/db")

        conn_kwargs = captured["kwargs"]
        assert conn_kwargs["connect_timeout"] == 5
        assert "statement_timeout=10000" in conn_kwargs["options"]
        assert "lock_timeout=5000" in conn_kwargs["options"]

    def test_schema_declares_purge_enabling_indexes(self) -> None:
        # Age-based cache purges need `created_at` indexes; the DDL
        # can only ever ADD, so they must exist from the start
        # (ADR 0042).
        from src.tools.postgres_pool import SCHEMA_DDL

        assert "paper_cache_created_at_idx" in SCHEMA_DDL
        assert "embedding_cache_created_at_idx" in SCHEMA_DDL


def _compose_app_service() -> dict[str, Any]:
    compose = yaml.safe_load(
        (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    service: dict[str, Any] = compose["services"]["app"]
    return service


class TestComposeContract:
    """Pin the deploy-hygiene decisions in the shipped compose file.

    These are contract tests over the YAML — cheap, no Docker — so a
    refactor can't silently revert the ADR 0042 fixes that only
    manifest in a browser or during a `docker compose down`.
    """

    def test_cors_defaults_off_for_same_origin_proxy(self) -> None:
        env = _compose_app_service()["environment"]
        value = env["API_CORS_ALLOW_ORIGINS"]
        # The browser calls Next.js at same-origin /api now. FastAPI
        # should install no CORS middleware unless an operator supplies
        # a separate trusted-client allowlist (ADR 0054).
        assert value == "${API_CORS_ALLOW_ORIGINS:-}"

    def test_auth_env_is_wired_through(self) -> None:
        env = _compose_app_service()["environment"]
        # Off by default (zero-config demo) but bootable: the
        # documented mitigation is one env flip away, not a compose
        # file edit.
        assert "ENABLE_API_AUTH" in env
        assert ":-false" in env["ENABLE_API_AUTH"]
        assert "API_KEYS" in env

    def test_host_ports_default_to_loopback(self) -> None:
        compose = yaml.safe_load(
            (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        )
        assert compose["services"]["app"]["ports"] == [
            "${APP_BIND_ADDRESS:-127.0.0.1}:${APP_PORT:-8000}:8000"
        ]
        assert compose["services"]["web"]["ports"] == [
            "${WEB_BIND_ADDRESS:-127.0.0.1}:${WEB_PORT:-3000}:3000"
        ]

    def test_app_drains_with_a_bounded_grace_period(self) -> None:
        from src.api.serve import GRACEFUL_SHUTDOWN_TIMEOUT_SEC

        service = _compose_app_service()
        # The app container must boot through `src.api.serve` — the
        # one place that sets `log_config=None` and the bounded
        # drain. A raw uvicorn CLI override cannot: `--log-config
        # /dev/null` is rejected at boot (`fileConfig` refuses an
        # empty file), and re-stating the drain flag here would be a
        # second copy that drifts.
        assert service["command"][-2:] == ["-m", "src.api.serve"]
        # The container grace period must exceed the drain so the
        # lifespan cleanup after the drain isn't SIGKILLed.
        grace = service["stop_grace_period"]
        assert grace.endswith("s")
        assert int(grace[:-1]) > GRACEFUL_SHUTDOWN_TIMEOUT_SEC

    def test_healthcheck_still_points_at_healthz(self) -> None:
        # /healthz is auth-exempt, so the probe keeps passing when
        # ENABLE_API_AUTH=true — that's what keeps auth-on bootable.
        service = _compose_app_service()
        assert "/healthz" in " ".join(service["healthcheck"]["test"])
