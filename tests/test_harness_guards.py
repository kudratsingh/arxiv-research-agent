"""Proof that `tests/conftest.py` actually guards what it claims to.

A guard nobody has watched fire is a convention, not a gate. Every
assertion here fails if the corresponding half of the harness is removed
or quietly weakened, which is the same contract the web suite's
must-fail copy fixtures carry (`docs/testing.md`).

Also home to the integrity checks that keep the coverage floor and the
tiers from becoming theatre: the tier-marker census, the purpose-marker
bands, and the inline-pragma census.
"""

from __future__ import annotations

import ast
import random
import re
import socket
import tomllib
from collections import Counter
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


class TestPurposeMarkerBands:
    """A band around each purpose tier, so an emptied one goes red.

    `property`, `fault`, `security` and `contract` gate a pull request
    only because they sit inside the merge gate's `-m "not e2e"`
    selection. Nothing names them there and nothing counts them, so a
    renamed marker, a moved directory or a deleted `pytestmark` leaves
    CI green and the tier dark — the one failure a test suite cannot
    report on its own, because the tests that would have failed were
    never selected. `.github/workflows/ci.yml` records the gap in the
    `tests` job and points here: WO-A13 considered running each tier as
    its own step for attribution and rejected it, ~30 s of re-collection
    to buy what a node id already carries, so this census is the agreed
    fix rather than the cheap one.

    IT READS THE SOURCE, NOT THE LIVE COLLECTION, which is the same
    choice `test_every_test_module_declares_a_tier` above makes and for
    a sharper reason. A census that counts the items pytest happened to
    select reports zero for every tier a `-m` filter excluded, and zero
    is exactly what an emptied tier reports — the two are
    indistinguishable in the one measurement that matters. Reading the
    tree instead holds under `pytest -m property`, under a single-file
    run, and under CI's selection alike.

    What it counts is test *functions*, not collected items: pytest
    reports 152 items for `property` against the 40 functions counted
    here, because `parametrize` and Hypothesis expand them. Both
    numbers are real and the function count is the conservative one to
    put a floor under, since items can only ever be a multiple of it.
    The walk was checked against the whole tree — it finds 2,977 test
    functions, exactly the number a regex over `tests/**/test_*.py`
    finds — so no test is hiding in a scope it does not visit.
    """

    #: BANDS, NOT A POPULATION: `(floor, ceiling)` per marker. The two
    #: edges catch different things and neither is decoration.
    #:
    #: THE FLOOR is 80% of the population measured on `c3d63da`
    #: (property 40, fault 158, security 267, contract 84), rounded
    #: down — except `contract`, re-centred on 229 at P0-WO08 when it
    #: outgrew its ceiling and this check said so; the 20% is
    #: deliberate slack for a refactor that folds
    #: functions into a `parametrize` or merges two modules without
    #: touching the tier. What it defends is worth checking rather than
    #: taking on the percentage: in every one of the four tiers,
    #: dropping the single largest contributing module's purpose marker
    #: lands *below* the floor.
    #:
    #:   tier      population  largest single module            drops to  floor
    #:   property          40  test_property_redaction.py  (10)       30     32
    #:   fault            158  test_job_redriver.py        (40)      118    126
    #:   security         267  test_safety_suite.py       (105)      162    213
    #:   contract         229  test_contract_runtime_bridge.py (75)  154    183
    #:
    #: That last row is the ceiling's argument made on this very band
    #: while it was being written: `contract` was 65 when these numbers
    #: were first taken, and WO-B1's `test_documented_claims.py` took it
    #: to 81 two commits later. The floor of 52 that had been correct
    #: for 65 no longer caught the loss of the tier's largest module at
    #: 81 — it passed at 58. It has moved twice more since, to 84, while
    #: this branch was open, and again to 229 when P0-WO08 landed two
    #: contract modules of its own. Re-centred here each time; the check
    #: below is what makes the next occurrence loud instead of
    #: arithmetic nobody redid.
    #:
    #: THE CEILING is 2x the population, and it exists because a floor
    #: only ever looks down. `docs/architecture.md` claimed nine OTel
    #: instruments while the real set grew to twenty-one, and
    #: `tests/test_operability_docs.py`'s then-bare `>= 20` stayed green
    #: through all of it: a number left behind by growth fails silently
    #: in the direction a floor cannot see. That assertion is a band as
    #: of the same commit as this one. At 2x, a floor written as 80% of
    #: its tier is really 40% of it and no longer the check its own
    #: comment describes, so the tier that got there has to come back to
    #: this line. The ceiling is deliberately looser than the band on
    #: the instrument count, because the two guard different things:
    #: that one guards a number prose quotes, this one guards a ratio
    #: nothing outside this file states.
    BANDS: dict[str, tuple[int, int]] = {
        "property": (32, 80),
        "fault": (126, 316),
        "security": (213, 534),
        "contract": (183, 458),
    }

    #: pytest's own discovery prefixes, which the walk below assumes and
    #: `test_the_scan_and_pytest_agree_on_what_a_test_is` pins.
    TEST_FUNCTION_PREFIX = "test"
    TEST_CLASS_PREFIX = "Test"

    @classmethod
    def _markers_in(cls, expression: ast.expr) -> set[str]:
        """Every `pytest.mark.<name>` reachable inside one expression.

        Three forms appear in this suite and all three have to resolve
        to the same name: a bare `pytest.mark.security`, a called one
        (`pytest.mark.parametrize(...)`), and a list of either, which is
        how nearly every module here carries its tier and its purpose
        together.
        """
        names: set[str] = set()
        pending: list[ast.expr] = [expression]
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.List, ast.Tuple)):
                pending.extend(node.elts)
            elif isinstance(node, ast.Call):
                pending.append(node.func)
            elif isinstance(node, ast.Attribute):
                owner = node.value
                if isinstance(owner, ast.Attribute) and owner.attr == "mark":
                    names.add(node.attr)
                else:
                    pending.append(owner)
        return names

    @classmethod
    def _scope_markers(cls, body: list[ast.stmt]) -> set[str]:
        """The markers a `pytestmark` assignment applies to one scope."""
        names: set[str] = set()
        for statement in body:
            if isinstance(statement, ast.Assign):
                targets, value = list(statement.targets), statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets, value = [statement.target], statement.value
            else:
                continue
            if value is None:
                continue
            if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
                names |= cls._markers_in(value)
        return names

    @classmethod
    def _decorator_markers(cls, node: ast.AST) -> set[str]:
        decorators: list[ast.expr] = getattr(node, "decorator_list", [])
        names: set[str] = set()
        for decorator in decorators:
            names |= cls._markers_in(decorator)
        return names

    @classmethod
    def _walk(cls, body: list[ast.stmt], inherited: set[str], counts: Counter[str]) -> None:
        """Count one scope's test functions, then recurse into classes.

        Markers compose by scope exactly as pytest composes them: a
        class inherits the module's `pytestmark`, a function inherits
        its class's, and a decorator adds to whatever it inherited.
        """
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith(cls.TEST_FUNCTION_PREFIX):
                    counts.update(inherited | cls._decorator_markers(node))
            elif isinstance(node, ast.ClassDef) and node.name.startswith(cls.TEST_CLASS_PREFIX):
                cls._walk(
                    node.body,
                    inherited | cls._decorator_markers(node) | cls._scope_markers(node.body),
                    counts,
                )

    @classmethod
    def population(cls) -> Counter[str]:
        """Test functions per marker across every module in `tests/`.

        `rglob`, not `glob`: three of the four tiers live in their own
        directories (`tests/property/`, `tests/fault/`, `tests/e2e/`),
        and a census that only walked the flat layout would report zero
        for them the day someone moved a fourth.
        """
        counts: Counter[str] = Counter()
        for path in sorted(TESTS_DIR.rglob("test_*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"))
            cls._walk(module.body, cls._scope_markers(module.body), counts)
        return counts

    def test_no_purpose_tier_has_been_emptied(self) -> None:
        counts = self.population()
        below = [
            f"{marker}: {counts[marker]} members against a floor of {floor}"
            for marker, (floor, _) in sorted(self.BANDS.items())
            if counts[marker] < floor
        ]
        assert below == [], (
            f"a purpose tier has lost members — {'; '.join(below)}. These four "
            "markers gate a PR only by sitting inside CI's `-m \"not e2e\"` "
            "selection, so a tier that stops selecting tests stays green and "
            "silent; that is what this floor exists to make loud. If the drop "
            "is deliberate, move the band in the same commit and say why."
        )

    def test_no_band_has_been_left_behind_by_growth(self) -> None:
        """The upper edge, which is a different defect from the lower one
        and deserves its own node id.

        A tier that doubled has a floor set against a suite that no
        longer exists: the number still passes, still reads as "80% of
        the tier" in the comment above, and is really 40% of it. That is
        how `docs/architecture.md` went on saying nine instruments while
        the set grew to twenty-one under a `>= 20` that could only ever
        look down. Nothing here is wrong when this fails — the tier grew,
        which is the goal — but the band has to be re-centred by the
        change that grew it rather than by nobody.
        """
        counts = self.population()
        above = [
            f"{marker}: {counts[marker]} members against a ceiling of {ceiling}"
            for marker, (_, ceiling) in sorted(self.BANDS.items())
            if counts[marker] > ceiling
        ]
        assert above == [], (
            f"a purpose tier has outgrown its band — {'; '.join(above)}. Nothing "
            "is broken; the floor below it has stopped being the fraction of the "
            "tier its comment claims. Re-centre both edges on the new population "
            "in this commit, and check that the floor still catches the loss of "
            "the tier's largest single module — that is what the number is for."
        )

    def test_a_new_purpose_marker_cannot_arrive_without_a_band(self) -> None:
        """A marker registered but left out of `BANDS` is a fifth tier
        nobody is counting, which is the original silence with an extra
        step. `network` is excluded by name: it has exactly one member
        by design (the proof that the guard opt-out works), so its only
        possible floor is the decorative one."""
        registered = {
            entry.split(":", 1)[0]
            for entry in PYPROJECT["tool"]["pytest"]["ini_options"]["markers"]
        }
        assert registered - set(TIERS) - {"network"} == set(self.BANDS)

    def test_every_band_is_a_band(self) -> None:
        """A ceiling at or below its floor is an unsatisfiable band, and
        a ceiling far above one is a floor with a decoration on top. Both
        are edits somebody could make while believing they had kept the
        check; this is the line that says otherwise."""
        for marker, (floor, ceiling) in sorted(self.BANDS.items()):
            assert floor < ceiling, marker
            assert ceiling <= floor * 3, marker

    def test_the_scan_and_pytest_agree_on_what_a_test_is(self) -> None:
        """The walk above uses pytest's default discovery prefixes. If
        `pyproject.toml` ever overrides them, the census is counting a
        different set of functions than the gate runs and this says so
        rather than drifting quietly."""
        ini = PYPROJECT["tool"]["pytest"]["ini_options"]
        assert "python_classes" not in ini
        assert "python_functions" not in ini

    def test_no_selection_option_narrows_every_run_at_once(self) -> None:
        """The one route around a source-level census: leave the markers
        in place and stop collecting them. A `-m`, `-k`, `--ignore` or
        `--deselect` in `addopts` applies to every invocation in the
        repository, including CI's, and would be invisible in the
        workflow file where a reader looks for the selection."""
        ini = PYPROJECT["tool"]["pytest"]["ini_options"]
        assert ini["testpaths"] == ["tests"]
        for option in ini["addopts"]:
            assert not option.startswith(("-m", "-k", "--ignore", "--deselect")), option


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
