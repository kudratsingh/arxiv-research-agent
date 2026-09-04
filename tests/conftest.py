"""The harness the suite cannot lie to.

Until this file existed the Python suite had no `conftest.py` anywhere,
and four properties everyone assumed were true were only *usually* true:

- **A developer's `.env` could change a test outcome.** `src/config.py`
  declares `env_file=".env"`, a real `.env` sits at the repo root, and
  more than thirty test modules construct a bare `Settings()`. Nothing
  stopped a locally-exported `MAX_PAPERS=3` from quietly rewriting an
  assertion that passed in CI.
- **Nothing stopped a test reaching the network.** One module patched
  `socket.getaddrinfo` to test SSRF defence; every other module was on
  the honour system, so a renamed import could silently turn a unit test
  into a live call to arxiv.org.
- **Nothing stopped a test constructing a real Anthropic client.** Two
  modules patched `src.llm._get_client` by hand and said so in their
  docstrings; the other ninety-six did not.
- **Nothing pinned the sources of non-determinism.** `random.seed`
  appeared zero times in the suite and `PYTHONHASHSEED` was whatever the
  invoking shell happened to carry.

Each of those is a *structural* absence: no quantity of additional tests
of the existing kind detects any of them. So the fixes here are process-
wide and autouse rather than opt-in, and where a test genuinely needs an
exception it has to say so in a marker — which puts the opt-out in the
diff, where a reviewer sees it.

Order matters. Environment isolation runs at *import* time, before any
test module can import `src.config` and freeze a polluted `settings`
singleton; the guards run per test, because they need the node's name
for their error message and monkeypatch's per-test teardown for their
restoration.

See `docs/decisions/0065-test-isolation-and-coverage-floor.md` for the
rationale and the alternatives that were rejected, and `docs/testing.md`
for the marker model these guards are selected by.
"""

from __future__ import annotations

import ipaddress
import os
import random
import socket
import sys
import time
from datetime import UTC, datetime
from typing import Any

import dotenv
import pytest
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# 1. Environment isolation — executed at import, not in a fixture
# ---------------------------------------------------------------------------
#
# `src/config.py` builds its `settings` singleton at module import. Test
# modules import it during *collection*, which happens after conftest is
# imported but before any fixture runs — so a fixture is too late to stop
# a `.env` value from reaching that singleton. Everything in this section
# therefore runs at conftest import time.

#: The invalid key the rest of the repository already uses to mean "no
#: paid call may succeed" — the Makefile's zero-spend targets, the
#: Compose overlay and the web e2e config all pin this exact string. It
#: is deliberately *truthy*: an empty key would send `_get_client` down
#: its "not configured" branch and hide the spend guard below behind a
#: different error.
DISABLED_API_KEY = "local-preview-disabled"

#: Values the suite declares for itself. Everything not named here falls
#: back to the field default in `src/config.py`, which is the point: a
#: test reads the shipped default unless it overrides one explicitly.
DECLARED_TEST_ENV: dict[str, str] = {
    "ANTHROPIC_API_KEY": DISABLED_API_KEY,
    # Read only by child interpreters — see `_pin_determinism` below for
    # why this cannot affect the process that is already running.
    "PYTHONHASHSEED": "0",
}

_ORIGINAL_SETTINGS_INIT = BaseSettings.__init__


def _init_without_dotenv(self: BaseSettings, **values: Any) -> None:
    """Construct any `BaseSettings` subclass with the dotenv source off.

    `_env_file` is pydantic-settings' own per-construction override and
    `None` means "read no file at all", so this suppresses the dotenv
    source without reaching into private machinery or editing a class's
    `model_config` after the fact. `setdefault` rather than an
    unconditional assignment: a test that deliberately points a
    `Settings` at a fixture `.env` still gets the file it asked for.
    """
    values.setdefault("_env_file", None)
    _ORIGINAL_SETTINGS_INIT(self, **values)


BaseSettings.__init__ = _init_without_dotenv  # type: ignore[method-assign]


def _load_dotenv_disabled(*args: Any, **kwargs: Any) -> bool:
    """Neutralise `dotenv.load_dotenv` for the whole session.

    Suppressing pydantic's dotenv *source* is not enough on its own, and
    the gap is not theoretical — it was measured. Four modules
    (`src/main.py`, `src/eval/runner.py`, `src/eval/simulate_learner.py`,
    `src/eval/record_learning_fixtures.py`) call `load_dotenv()` at
    import, which copies the file straight into `os.environ`, where it
    outranks every default and is invisible to a `Settings` that has
    already been built. With a `.env` at the repo root and this patch
    absent, importing `src.eval.runner` mid-session moved eight tests in
    `test_config.py`, `test_observability.py`, `test_search_honesty.py`
    and `test_session_cost_cap.py`.

    A no-op rather than a raise: calling it at import is correct
    production behaviour, and a raise would break the import instead of
    the leak. Patched here, before any `from dotenv import load_dotenv`
    can bind the real one.
    """
    return False


dotenv.load_dotenv = _load_dotenv_disabled

# Being the first importer of `src.config` is the whole guarantee: the
# singleton it builds at import must be built under the patch above and
# under the scrubbed environment below. If something imported it earlier
# — a pytest plugin, a `-p` module — that singleton already read the
# developer's `.env`, and silently continuing would restore exactly the
# ambiguity this file exists to remove.
if "src.config" in sys.modules:
    raise RuntimeError(
        "src.config was imported before tests/conftest.py; the settings "
        "singleton may carry .env values. Load no plugin that imports src."
    )

import src.config as _config_module  # noqa: E402  (must follow the patch above)

#: Every environment variable `Settings` reads, derived from the model
#: rather than listed, so a new field is covered the day it lands.
#: `case_sensitive=False` means pydantic matches on the upper-cased
#: field name, which is what gets removed here.
SETTINGS_ENV_VARS: frozenset[str] = frozenset(
    name.upper() for name in _config_module.Settings.model_fields
)

for _name in SETTINGS_ENV_VARS:
    os.environ.pop(_name, None)
os.environ.update(DECLARED_TEST_ENV)

# Rebuilt under the declared environment. Safe precisely because of the
# `sys.modules` check above: nothing has done `from src.config import
# settings` yet, so there is no stale alias to leave behind.
_config_module.settings = _config_module.Settings()


# ---------------------------------------------------------------------------
# 2. The guards
# ---------------------------------------------------------------------------


class NetworkAccessDenied(BaseException):
    """A test tried to open a non-loopback socket.

    Deliberately a `BaseException`. This codebase degrades gracefully on
    purpose — the reader falls back to abstracts, the supervisor falls
    back to a default route, the cache falls back to a miss — and around
    fifty `except Exception` sites implement that. A guard those handlers
    can swallow is not a guard: the test would go green while the run it
    describes had reached the internet.
    """


class LLMSpendDenied(BaseException):
    """A test reached the real Anthropic client constructor.

    `BaseException` for the same reason as `NetworkAccessDenied`, and
    with more at stake: `src/llm.py`'s callers are exactly the ones with
    fallbacks, so a swallowable spend guard reports success on the run
    that spent the money.
    """


#: Address literals that mean "this machine". `pytest-postgresql` binds a
#: real server on loopback (or a unix socket, which never reaches the
#: family check below) and the ASGI transports talk to themselves, so
#: loopback has to stay open or the integration tier cannot run at all.
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.", "localhost.localdomain"})


def _current_test_name() -> str:
    """Name the test in the guard's message.

    pytest exports the running node id here for exactly this purpose. A
    guard that fires during a plugin's own work, or at interpreter
    shutdown, has no node and says so rather than guessing.
    """
    return os.environ.get("PYTEST_CURRENT_TEST", "<no active test>")


def _is_local_address(family: int, address: Any) -> bool:
    """Return whether `address` stays on this machine.

    Non-IP families (`AF_UNIX` above all) never leave the host, so they
    pass without inspection. An IP family is allowed only for a loopback
    literal: a *hostname* is refused because resolving it to find out
    would itself be the network access under test.
    """
    if family not in (socket.AF_INET, socket.AF_INET6):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    if host in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _network_guard(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse any connect that would leave this machine.

    `connect` and `connect_ex` are the two methods every higher-level
    client bottoms out in — `socket.create_connection`, `http.client`,
    `requests`, `httpx` and `psycopg` all call one of them — so patching
    the pair covers the stack without knowing which library is in play.
    DNS is left alone: `socket.getaddrinfo` is what
    `tests/test_pdf_parser.py` patches to drive the SSRF checks, and
    taking it over here would collide with that.

    Opt out with `@pytest.mark.network`. There are no legitimate users
    today; the marker exists so that the first one is visible in a diff.
    """
    if request.node.get_closest_marker("network") is not None:
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _deny(verb: str) -> Any:
        def _guarded(self: socket.socket, address: Any, /) -> Any:
            if _is_local_address(self.family, address):
                return (real_connect if verb == "connect" else real_connect_ex)(
                    self, address
                )
            raise NetworkAccessDenied(
                f"{_current_test_name()} tried to {verb} to {address!r}. "
                "Tests run offline: patch the client, or mark the test "
                "@pytest.mark.network and say why in the PR body."
            )

        return _guarded

    monkeypatch.setattr(socket.socket, "connect", _deny("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _deny("connect_ex"))


@pytest.fixture(autouse=True)
def _spend_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse to build a real Anthropic client.

    `src.llm._get_client` is the single choke point every paid path
    funnels through, and the suite already had two hand-rolled copies of
    this patch that said so in their docstrings. This is the structural
    version.

    It has to keep the two existing fake-installation styles working,
    because both are load-bearing and neither is going to be rewritten
    here:

    - `monkeypatch.setattr(llm, "_get_client", lambda: fake)` — twenty
      call sites. Their patch lands *after* this fixture's and simply
      replaces it, so nothing special is needed.
    - `monkeypatch.setattr(llm.anthropic, "Anthropic", FakeAnthropic)` —
      `tests/test_llm.py::TestGetClient`, which exercises the real
      construction logic (the retry clamp, the warning it emits) against
      a fake SDK. Those tests still need the real `_get_client` body to
      run, so the guard checks whether a fake is in place and delegates
      when one is.

    The denial therefore fires on exactly one condition: the code is
    about to hand a live `anthropic.Anthropic` a real API key.
    """
    import src.llm as llm_module

    real_get_client = llm_module._get_client
    real_sdk_client = llm_module.anthropic.Anthropic

    def _guarded_get_client() -> Any:
        fake_installed = (
            llm_module._client is not None
            or llm_module.anthropic.Anthropic is not real_sdk_client
        )
        if fake_installed:
            return real_get_client()
        raise LLMSpendDenied(
            f"{_current_test_name()} reached src.llm._get_client with no fake "
            "installed. Patch `src.llm._get_client`, or patch "
            "`src.llm.anthropic.Anthropic` if the test is about client "
            "construction itself."
        )

    monkeypatch.setattr(llm_module, "_get_client", _guarded_get_client)


# ---------------------------------------------------------------------------
# 3. Determinism
# ---------------------------------------------------------------------------

#: Fixed rather than derived from the node id. A per-test seed sounds
#: more thorough but makes a failure depend on the test's *name*, so
#: renaming a test can change whether it fails.
RANDOM_SEED = 0

#: 2026-01-01T00:00:00Z. A round, obviously-artificial instant, so a
#: timestamp that leaks into an assertion message is recognisable as the
#: frozen clock rather than mistaken for a real one.
FROZEN_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_determinism() -> None:
    """Reseed the global RNGs before every test.

    Per test rather than per session, so a test that draws from `random`
    is unaffected by how many draws the tests before it made — which is
    the property that makes a failure reproducible from its node id
    alone, without `-p no:randomly` or a recorded ordering.

    `PYTHONHASHSEED` is set in section 1 rather than here because CPython
    reads it once at interpreter start: setting it now cannot change this
    process's hash seed, only the seed of the subprocesses the suite
    spawns (`tests/test_api_lazy_imports.py` starts fresh interpreters).
    The Makefile's `TEST_ENV` exports it so the parent is pinned too.
    """
    random.seed(RANDOM_SEED)
    numpy = sys.modules.get("numpy")
    if numpy is not None:  # already imported by torch on most paths
        numpy.random.seed(RANDOM_SEED)


class FrozenClock:
    """A clock that only moves when a test moves it.

    Offered as the `frozen_clock` fixture to the modules that currently
    hand-patch time one call site at a time. It is deliberately *not*
    autouse: freezing the clock under every test would change the meaning
    of the drain, lease and timeout tests, which measure real elapsed
    time on purpose.

    `sleep` advances the clock instead of blocking. A frozen clock whose
    `sleep` really sleeps is a lie — the code under test would observe no
    time passing across a call that took a second of wall clock.
    """

    def __init__(self, start: datetime = FROZEN_EPOCH) -> None:
        self._epoch = start
        self._offset = 0.0

    def advance(self, seconds: float) -> None:
        """Move the clock forward. Never backwards — nothing does that."""
        if seconds < 0:
            raise ValueError("frozen_clock only moves forward")
        self._offset += seconds

    def time(self) -> float:
        return self._epoch.timestamp() + self._offset

    def monotonic(self) -> float:
        return self._offset

    def perf_counter(self) -> float:
        return self._offset

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def now(self) -> datetime:
        """The current instant as an aware UTC datetime."""
        return datetime.fromtimestamp(self.time(), tz=UTC)


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    """Freeze `time.time`, `time.monotonic`, `time.perf_counter`, `time.sleep`.

    Patched on the `time` module itself, which is how `src/` reads the
    clock (`import time` then `time.monotonic()`), so the code under test
    picks the frozen values up without knowing about the fixture.
    """
    clock = FrozenClock()
    monkeypatch.setattr(time, "time", clock.time)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    return clock


# ---------------------------------------------------------------------------
# 4. Tier-marker completeness
# ---------------------------------------------------------------------------

#: Exactly one of these applies to every test. See `docs/testing.md`.
TIER_MARKERS = frozenset({"unit", "integration", "e2e"})

_TIER_VIOLATIONS: list[str] = []


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Record every collected test whose tier is missing or ambiguous.

    `tryfirst` so this sees the full collection: pytest's own `-m`
    handling deselects inside this same hook, and a run filtered to one
    tier must still be able to report on the tiers it did not select.

    Recorded rather than raised. A hard failure here aborts collection
    for the whole session, which turns "someone forgot a marker" into
    "the suite does not run" — and this repository has several agents
    adding test modules concurrently. The report is asserted by
    `tests/test_harness_guards.py` instead, so it is a red test with a
    node id like any other failure.

    Markers compose by scope: a class- or function-level tier shadows a
    module-level one, which is how `pytestmark = pytest.mark.unit` plus a
    single `@pytest.mark.integration` class is meant to read. What is
    *not* allowed is two different tiers declared at the same scope, and
    what is never allowed is no tier at all.
    """
    _TIER_VIOLATIONS.clear()
    for item in items:
        by_scope: dict[str, set[str]] = {}
        for node, mark in item.iter_markers_with_node():
            if mark.name in TIER_MARKERS:
                by_scope.setdefault(node.nodeid, set()).add(mark.name)
        if not by_scope:
            _TIER_VIOLATIONS.append(f"{item.nodeid}: no tier marker")
            continue
        for scope, tiers in by_scope.items():
            if len(tiers) > 1:
                _TIER_VIOLATIONS.append(
                    f"{item.nodeid}: {sorted(tiers)} declared together on {scope}"
                )


@pytest.fixture
def tier_marker_violations() -> list[str]:
    """The tier problems found while collecting this session."""
    return list(_TIER_VIOLATIONS)


@pytest.fixture
def harness_environment() -> tuple[frozenset[str], dict[str, str]]:
    """The variables section 1 scrubbed, and the values it declared."""
    return SETTINGS_ENV_VARS, dict(DECLARED_TEST_ENV)


@pytest.fixture
def guard_exceptions() -> tuple[type[BaseException], type[BaseException]]:
    """The two guard exception types, for the tests that prove they fire.

    Handed over as a fixture rather than imported: `tests/` carries no
    `__init__.py`, so `import conftest` works only by way of the sys.path
    entry pytest happens to insert, and a guard proof should not rest on
    that.
    """
    return NetworkAccessDenied, LLMSpendDenied
