"""Proof that `tests/conftest.py` actually guards what it claims to.

A guard nobody has watched fire is a convention, not a gate. Every
assertion here fails if the corresponding half of the harness is removed
or quietly weakened, which is the same contract the web suite's
must-fail copy fixtures carry (`docs/testing.md`).

Also home to the two integrity checks that keep the coverage floor from
becoming theatre: the tier-marker census, and the inline-pragma census.
"""

from __future__ import annotations

import random
import re
import socket
import tomllib
from pathlib import Path
from typing import Any

import pytest

import src.llm as llm_module
from src.config import Settings

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
PYPROJECT: dict[str, Any] = tomllib.loads(
    (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
)

#: The tier vocabulary, restated here rather than imported from conftest:
#: this file is the specification's second opinion, and a check that
#: imports its expectation from the thing it checks proves nothing.
TIERS = ("unit", "integration", "e2e")
_TIER_RE = re.compile(rf"pytest\.mark\.(?:{'|'.join(TIERS)})\b")


class TestEnvironmentIsolation:
    """`src/config.py:53` sets `env_file=".env"`; a real `.env` exists."""

    def test_a_dotenv_in_the_working_directory_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `MAX_PAPERS` is a real field with a default of 10, so a leak
        # shows up as a value, not as an exception.
        (tmp_path / ".env").write_text("MAX_PAPERS=1\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert Settings().max_papers == Settings.model_fields["max_papers"].default

    def test_the_dotenv_source_still_works_when_asked_for_explicitly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The harness suppresses the *default*, it does not break the feature.

        Without this second half, a conftest that broke dotenv loading
        outright would pass the test above and ship a `Settings` that
        cannot read a file in production either.
        """
        (tmp_path / ".env").write_text("MAX_PAPERS=1\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert Settings(_env_file=".env").max_papers == 1

    def test_the_dotenv_loader_itself_is_neutralised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Suppressing pydantic's dotenv source is not enough.

        Four `src` modules call `dotenv.load_dotenv()` at import, which
        writes the file into `os.environ` where it outranks everything
        and is invisible to an already-built `Settings`. Measured: with
        that path open, importing `src.eval.runner` mid-session moved
        eight assertions in four other modules.
        """
        import os

        from dotenv import load_dotenv

        (tmp_path / ".env").write_text("HARNESS_CANARY=leaked\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        load_dotenv()

        assert "HARNESS_CANARY" not in os.environ

    def test_the_production_config_still_declares_the_dotenv_file(self) -> None:
        assert Settings.model_config["env_file"] == ".env"

    def test_the_api_key_is_the_disabled_sentinel(self) -> None:
        """Truthy, so `_get_client` reaches the spend guard rather than
        its own "not configured" branch, and useless to a real API."""
        import os

        assert os.environ["ANTHROPIC_API_KEY"] == "local-preview-disabled"

    def test_no_undeclared_settings_variable_survives_into_the_run(
        self, harness_environment: tuple[frozenset[str], dict[str, str]]
    ) -> None:
        """A developer's exported `MAX_PAPERS=3` must not reach a test
        any more than a `.env` line may."""
        import os

        settings_vars, declared = harness_environment
        leaked = {
            name
            for name in settings_vars
            if name in os.environ and name not in declared
        }
        assert leaked == set()


class TestNetworkGuard:
    def test_a_non_loopback_connect_is_refused(
        self, guard_exceptions: tuple[type[BaseException], type[BaseException]]
    ) -> None:
        network_denied, _ = guard_exceptions
        # TEST-NET-3 (RFC 5737) — reserved for documentation, routed
        # nowhere, so this address cannot succeed even if the guard is
        # gone; it would hang or refuse rather than reach a real host.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(network_denied) as caught:
                sock.connect(("203.0.113.7", 443))
        finally:
            sock.close()
        assert "test_a_non_loopback_connect_is_refused" in str(caught.value)

    def test_loopback_still_connects(self) -> None:
        """The integration tier needs this: `pytest-postgresql` runs a
        real server, and every ASGI transport talks to itself."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            client.connect(server.getsockname())
            accepted, _ = server.accept()
            accepted.close()
        finally:
            client.close()
            server.close()

    @pytest.mark.network
    def test_the_network_marker_removes_the_guard(self) -> None:
        """The marker's only user, and the reason it exists.

        It asserts the guard is *absent*, not that traffic flows: this
        test must stay offline like every other one. If a real network
        user ever appears, it shows up in a diff next to this line.
        """
        assert socket.socket.connect is socket.SocketType.connect


class TestSpendGuard:
    def test_get_client_raises_without_a_fake(
        self, guard_exceptions: tuple[type[BaseException], type[BaseException]]
    ) -> None:
        _, spend_denied = guard_exceptions
        with pytest.raises(spend_denied) as caught:
            llm_module._get_client()
        assert "test_get_client_raises_without_a_fake" in str(caught.value)

    def test_the_whole_call_path_raises_not_just_the_constructor(
        self, guard_exceptions: tuple[type[BaseException], type[BaseException]]
    ) -> None:
        """`call_llm_json` is what agents call; `_get_client` is where it
        bottoms out. Pinning the outer entry point too means a future
        refactor that bypasses the singleton still trips the guard."""
        _, spend_denied = guard_exceptions
        with pytest.raises(spend_denied):
            llm_module.call_llm_json(prompt="hi", system_prompt="hi")

    def test_a_fake_sdk_constructor_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`tests/test_llm.py::TestGetClient` installs its fake this way
        and needs the real `_get_client` body to run."""

        class _FakeAnthropic:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        monkeypatch.setattr(llm_module, "_client", None)
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        assert isinstance(llm_module._get_client(), _FakeAnthropic)

    def test_a_patched_get_client_is_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other twenty call sites install their fake this way."""
        sentinel = object()
        monkeypatch.setattr(llm_module, "_get_client", lambda: sentinel)

        assert llm_module._get_client() is sentinel


class TestTierMarkers:
    def test_every_test_module_declares_a_tier(self) -> None:
        """Walks the directory rather than a list, so a module added by
        another branch is covered the moment it lands."""
        missing = sorted(
            path.name
            for path in TESTS_DIR.glob("test_*.py")
            if not _TIER_RE.search(path.read_text(encoding="utf-8"))
        )
        assert missing == [], (
            f"{len(missing)} test module(s) carry no tier marker: {missing}. "
            "Add `pytestmark = pytest.mark.unit` (or integration/e2e) — see "
            "docs/testing.md."
        )

    def test_every_collected_test_resolves_to_exactly_one_tier(
        self, tier_marker_violations: list[str]
    ) -> None:
        """The per-item half of the rule, which the file walk cannot see:
        a module can declare a tier and still leave one class carrying
        two of them."""
        assert tier_marker_violations == []

    def test_the_tier_and_purpose_markers_are_registered(self) -> None:
        registered = {
            entry.split(":", 1)[0]
            for entry in PYPROJECT["tool"]["pytest"]["ini_options"]["markers"]
        }
        assert set(TIERS) <= registered
        assert {"security", "property", "fault", "contract", "network"} <= registered


class TestDeterminism:
    #: Both tests draw from the same seeded generator. If the reseed were
    #: per session instead of per test, the second draw would differ.
    def test_random_is_reseeded_before_each_test(self) -> None:
        assert random.random() == pytest.approx(0.8444218515250481)

    def test_random_is_reseeded_before_each_test_again(self) -> None:
        assert random.random() == pytest.approx(0.8444218515250481)

    def test_frozen_clock_does_not_move_on_its_own(self, frozen_clock: Any) -> None:
        import time

        assert time.monotonic() == time.monotonic()
        assert time.time() == time.time()

    def test_frozen_clock_advances_only_when_told(self, frozen_clock: Any) -> None:
        import time

        before = time.monotonic()
        frozen_clock.advance(90.0)
        assert time.monotonic() - before == pytest.approx(90.0)
        assert frozen_clock.now().isoformat() == "2026-01-01T00:01:30+00:00"

    def test_frozen_clock_sleep_advances_instead_of_blocking(
        self, frozen_clock: Any
    ) -> None:
        import time

        time.sleep(3600)
        assert time.monotonic() == pytest.approx(3600.0)


class TestStrictnessIsConfigured:
    """`pyproject.toml` assertions, in the style of
    `tests/test_repo_hygiene.py`: these settings are one deletion away
    from silence, and nothing else notices their absence."""

    @property
    def _ini(self) -> dict[str, Any]:
        return PYPROJECT["tool"]["pytest"]["ini_options"]  # type: ignore[no-any-return]

    def test_markers_and_config_are_strict(self) -> None:
        assert "--strict-markers" in self._ini["addopts"]
        assert "--strict-config" in self._ini["addopts"]

    def test_xfail_is_strict(self) -> None:
        assert self._ini["xfail_strict"] is True

    def test_a_per_test_timeout_exists(self) -> None:
        assert isinstance(self._ini["timeout"], int)
        assert self._ini["timeout"] > 0

    def test_warnings_are_errors_and_every_exemption_is_scoped(self) -> None:
        filters = self._ini["filterwarnings"]
        assert filters[0] == "error"
        for entry in filters[1:]:
            action, _, rest = entry.partition(":")
            assert action == "ignore"
            # A bare `ignore` or `ignore::SomeWarning` silences a whole
            # category. Every exemption here names the message it mutes.
            assert rest and not rest.startswith(":"), entry


class TestCoverageIntegrity:
    """Coverage is a floor, and floors get gamed. These two checks are
    worth more than a higher percentage (ADR 0065)."""

    #: Census taken when the floor was adopted. It may fall. A PR that
    #: raises it is adding an untested branch and saying so in a comment
    #: instead of in a test, which is the trade this number makes visible.
    #: Twelve when WO-A02 was written; sixteen after WO-A01 and WO-A03
    #: merged ahead of it — three in `src/observability/logging.py`
    #: around the OpenTelemetry import guard, one in `src/api/app.py`.
    #: The check earned its keep before it landed: it caught that drift
    #: in CI rather than letting the number move unnoticed.
    PRAGMA_CENSUS = 16

    def _pragmas(self) -> list[tuple[Path, str]]:
        found: list[tuple[Path, str]] = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "pragma: no cover" in line:
                    found.append((path, line.strip()))
        return found

    def test_inline_pragmas_have_not_multiplied(self) -> None:
        found = self._pragmas()
        assert len(found) <= self.PRAGMA_CENSUS, (
            f"{len(found)} inline `pragma: no cover` in src/, census is "
            f"{self.PRAGMA_CENSUS}. Prefer a rule in "
            "[tool.coverage.report].exclude_also, which is visible in the "
            "config; a pragma is invisible in the report."
        )

    def test_every_inline_pragma_carries_a_reason(self) -> None:
        unexplained = [
            f"{path.relative_to(REPO_ROOT)}: {line}"
            for path, line in self._pragmas()
            if not re.search(r"pragma: no cover\s*-\s*\S", line)
        ]
        assert unexplained == [], (
            "write the reason inline, as `# pragma: no cover - why`: "
            f"{unexplained}"
        )

    def test_branch_coverage_is_on(self) -> None:
        """Line coverage over-reports on compound conditions, which this
        codebase has plenty of."""
        assert PYPROJECT["tool"]["coverage"]["run"]["branch"] is True

    def test_nothing_is_omitted_from_measurement(self) -> None:
        """An `omit` entry is an exclusion with no reason attached and no
        line in the report. Exclusions belong in `exclude_also`."""
        assert PYPROJECT["tool"]["coverage"]["run"]["omit"] == []

    def test_the_floor_is_set(self) -> None:
        assert PYPROJECT["tool"]["coverage"]["report"]["fail_under"] > 0


class TestMakefileTestTargets:
    """Every test target keeps the ADR 0052 thread pin.

    `tests/test_repo_hygiene.py` asserts this for the four targets that
    existed when it was written; this one discovers the targets instead,
    so a new selector cannot be added without the prefix.
    """

    def test_every_test_target_pins_the_test_environment(self) -> None:
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        recipes = re.findall(
            r"^(test[\w-]*):[^\n]*\n((?:\t[^\n]*\n)+)", makefile, re.MULTILINE
        )
        assert recipes, "no test targets found in the Makefile"
        missing = [
            name
            for name, body in recipes
            if "$(VENV_PYTHON)" in body and "$(TEST_ENV)" not in body
        ]
        assert missing == []
