"""Prose claims in `README.md` and `docs/architecture.md` are checkable.

Phase A's assurance pack (`docs/assurance/README.md`) extracted seventy
claims from those two documents and found that **no test read any of
them**. Three tests touched a README at all — a `COPY` line in the
container contract, the eval marker block, and the runbooks index — and
none of them checked a claim. That single structural absence is why five
sentences were false on `main` at the time the index was written, and why
one of them (the test counts) went stale *twice in the week the index was
being drafted*: once from a peer's merge and once from its own.

This module is the missing direction. `tests/test_operability_docs.py`
already proves that alert rules, dashboards and runbooks name signals the
code actually emits, by re-parsing `src/` rather than trusting a
checked-in list; the same technique applies to a sentence. The one thing
this file adds to that model is where the *number* lives.

## The number lives in the prose, and only there

A count written in a document and asserted again in a test is two places
to update, and the second one is invisible to whoever edits the first. So
every check below **parses the number out of the sentence it is checking**
and compares it against a value re-derived from the artifact the sentence
describes. Editing the sentence is therefore the whole of the edit, and a
sentence that stops being true fails a test that quotes it back.

## Floor or equality, decided per claim rather than by policy

Neither is right everywhere, and the choice is made on how the underlying
number moves:

* **Floor**, where the truth changes on most pull requests. The Python
  suite gained 1,193 tests during Phase A alone. An equality there would
  mean every PR that adds a test also edits `README.md`, which is exactly
  the churn that produces a number nobody updates. `over 3,300 tests` is
  therefore a floor — with a *band*: a floor that has fallen more than
  `_FLOOR_BAND` behind the truth is not a floor any more, it is an
  abandoned number, and `test_the_python_floor_has_not_fallen_out_of_date`
  fails so somebody raises it. That test firing is not a defect; it is the
  once-a-year nudge the design pays for the rest of the time.
* **Equality**, where the number moves only by a deliberate act. The
  Vitest count of record moves when somebody re-seeds the coverage
  thresholds in `web/vitest.config.mts`, which is a decision with its own
  paragraph of justification every time it has happened. The `e2e` tier is
  sixteen tests by design and a seventeenth is worth a sentence. The OTel
  instrument count and the `run_job` kind branches are *closed sets* — the
  claim is that these are all of them, so an equality is the claim.

## Where this test deliberately stops

Three kinds of claim are not mechanisable and are not weakened here to
make one pass. Weakening prose until a test can pass it would be a worse
outcome than the drift this file exists to catch, so the gaps stay in the
index instead:

1. **"Quality preserved."** There is no quality measurement anywhere in
   this repository — no eval campaign has ever completed. What is checked
   about the routing claim is the *arithmetic* (the price ratio the
   modelled band is computed from) and the presence of the qualifier that
   says the band is modelled. That second check is a tripwire against the
   qualifier being deleted, not a proof of anything.
2. **The nightly eval's state.** `.github/workflows/eval-nightly.yml` is
   disabled with `disabled_manually`, which is a GitHub-side attribute of
   the repository and is not in the tree at all — the file itself still
   carries a live `cron`. A test reading the file would assert the
   opposite of the truth. A24/A25 in the index stay unenforced with that
   reason attached.
3. **Anything requiring a browser or a paid call.** The Vitest figure is
   checked against `web/vitest.config.mts`'s own record of it, not against
   a run: this is a Python tier and running the web suite from it would be
   both slow and a lie about what was measured. The check is therefore an
   *agreement between two documents*, and the index says so.

## The one expensive test in here

`_collect_tiers` spawns `pytest --collect-only -m e2e`, which costs about
seven seconds and makes this the slowest module in the suite. It is paid
once (the result is cached) and it buys the only sound count: `pytest`'s
own collection, with markers resolved. The cheap alternatives are all
wrong — counting `def test_` in the AST undercounts every parametrised
test, and reading `session.items` of the *running* session would report
whatever selection the invoker happened to ask for, so the same test would
pass under `pytest -q` and fail under `pytest tests/test_documented_claims.py`.
A count that depends on how you invoked it is not a count.

Mutation-check: restore any of the five sentences this module was written
against — "3,277 tests", "2,970 Vitest tests across 136 files", "the
`e2e` cassette tier is registered but not built", "nothing else in
`run_job` branches on the kind", "nine OTel instruments" — and exactly one
test here goes red for each.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import sys
from functools import lru_cache
from typing import Final

import pytest
import yaml

from tests.test_operability_docs import INSTRUMENTS

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_ROOT: Final = pathlib.Path(__file__).resolve().parents[1]
_README: Final = _ROOT / "README.md"
_ARCHITECTURE: Final = _ROOT / "docs" / "architecture.md"
_CI_WORKFLOW: Final = _ROOT / ".github" / "workflows" / "ci.yml"
_VITEST_CONFIG: Final = _ROOT / "web" / "vitest.config.mts"
_DECISIONS: Final = _ROOT / "docs" / "decisions"
_E2E_DIR: Final = _ROOT / "tests" / "e2e"

#: How far the README's Python floor is allowed to lag the collected
#: count before it stops counting as a floor. Wide enough that ordinary
#: growth never touches the sentence, narrow enough that the sentence
#: cannot be gutted to `over 100 tests` and left there forever.
_FLOOR_BAND: Final = 500

#: Number words this repository's prose actually uses. A map rather than a
#: library so that an unrecognised word is a **failure** — a check that
#: silently skips the sentence it cannot parse is the same species of
#: nothing-is-watching that this whole file exists to end.
_NUMBER_WORDS: Final[dict[str, int]] = {
    "four": 4,
    "five": 5,
    "nine": 9,
    "sixteen": 16,
    "twenty-one": 21,
}


def _prose(path: pathlib.Path) -> str:
    """One document as a single line, so a claim can span a line break.

    Both documents are hard-wrapped at ~72 columns, so every sentence
    below is split across lines at a position nobody controls: reflowing
    a paragraph moves the break and would otherwise silently stop a
    pattern matching — which `_claim` would then report as a missing
    sentence rather than as a stale number. Collapsing whitespace first
    makes the checks depend on the words and not on the wrapping.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _readme() -> str:
    return _prose(_README)


def _architecture() -> str:
    return _prose(_ARCHITECTURE)


def _claim(pattern: str, text: str, where: str) -> re.Match[str]:
    """Find the sentence a check is about, or fail naming it.

    A rewritten sentence that no longer matches must fail loudly rather
    than leave the check silently unenforced, which is what a
    `pytest.skip` here would do.
    """
    match = re.search(pattern, text)
    assert match is not None, (
        f"{where} no longer contains a sentence matching {pattern!r}. This "
        "check reads its number out of the prose, so rewording the sentence "
        "means updating the pattern in the same commit — that coupling is "
        "deliberate, and it is what stops the number drifting."
    )
    return match


def _word_to_int(word: str, where: str) -> int:
    number = _NUMBER_WORDS.get(word.lower())
    assert number is not None, (
        f"{where} spells a count as {word!r}, which "
        "`_NUMBER_WORDS` does not know. Add it there in the same commit "
        "rather than letting the check pass over a number it cannot read."
    )
    return number


def _digits(text: str) -> int:
    return int(text.replace(",", ""))


# ---------------------------------------------------------------------------
# The collected suite, counted the only way that is sound
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _collect_tiers() -> tuple[int, int]:
    """Return `(tests collected in total, tests carrying the e2e marker)`.

    One subprocess answers both questions: `pytest --collect-only -m e2e`
    reports the selected count over the total in the same line, so the
    seven seconds buys two numbers rather than one.

    The child's environment is scrubbed of `PYTEST_ADDOPTS` (an outer
    invocation's flags would change the child's selection and therefore
    its answer) and of `COV_CORE_*` (pytest-cov's subprocess hooks, which
    would have the child writing coverage data for a run that executes
    nothing).
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COV_CORE") and key != "PYTEST_ADDOPTS"
    }
    env["ANTHROPIC_API_KEY"] = "local-preview-disabled"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            "e2e",
        ],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        "collection of the whole suite failed, so no count below means "
        f"anything:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
    # "16/3306 tests collected (3290 deselected) in 4.33s", or
    # "3306 tests collected in 4.88s" if the selection ever became the
    # whole suite.
    split = re.search(r"(\d+)/(\d+) tests collected", result.stdout)
    if split is not None:
        return int(split.group(2)), int(split.group(1))
    whole = re.search(r"(\d+) tests collected", result.stdout)
    assert whole is not None, f"no collection tally in:\n{result.stdout[-2000:]}"
    return int(whole.group(1)), int(whole.group(1))


# ---------------------------------------------------------------------------
# Re-deriving what the sentences describe
# ---------------------------------------------------------------------------


def _ci_jobs() -> dict[str, object]:
    document = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs: dict[str, object] = document["jobs"]
    return jobs


def _last_vitest_reseed() -> tuple[int, int]:
    """The most recent `N tests across M files` note in the Vitest config.

    That file's coverage thresholds are re-seeded by hand, and every
    re-seed since WO-05 has recorded the suite size it was measured at in
    the comment above the numbers. The *last* such note is the count of
    record; the earlier ones are the audit trail the file keeps on purpose.

    Comment prefixes are stripped before matching because the note wraps:
    `3,380` and `tests across 155 files` are on different lines.
    """
    text = _VITEST_CONFIG.read_text(encoding="utf-8")
    flattened = " ".join(
        re.sub(r"^\s*//\s?", "", line) for line in text.splitlines()
    )
    notes = re.findall(r"([\d,]+) tests across (\d+) files", flattened)
    assert notes, (
        "web/vitest.config.mts records no `N tests across M files` note, so "
        "the README's Vitest figure has no source of truth in the tree"
    )
    tests, files = notes[-1]
    return _digits(tests), int(files)


def _model_prices() -> dict[str, dict[str, float]]:
    """The shipped price table, read from `src/observability/costs.py`.

    Imported through the module rather than re-parsed: unlike the OTel
    instrument names, this is a plain module-level dict that costs nothing
    to import and cannot be shadowed by a call-site rename.
    """
    from src.observability.costs import PRICES_USD_PER_MILLION

    return PRICES_USD_PER_MILLION


def _run_job_kind_branches() -> list[int]:
    """Line numbers of every comparison against `job.kind` inside `run_job`.

    Nested functions count: `on_node` is defined inside `run_job` and one
    of the five branches lives there, so a walk of the whole function body
    is what the sentence means by "in `run_job`".
    """
    tree = ast.parse((_ROOT / "src" / "api" / "runner.py").read_text(encoding="utf-8"))

    def is_job_kind(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "kind"
            and isinstance(node.value, ast.Name)
            and node.value.id == "job"
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "run_job":
            continue
        return sorted(
            sub.lineno
            for sub in ast.walk(node)
            if isinstance(sub, ast.Compare)
            and (is_job_kind(sub.left) or any(is_job_kind(c) for c in sub.comparators))
        )
    raise AssertionError("src/api/runner.py declares no `run_job` coroutine")


# ---------------------------------------------------------------------------
# R22 — the CI paragraph's three numbers
# ---------------------------------------------------------------------------


class TestTheCiJobCount:
    def test_the_readme_job_count_is_the_workflow_job_count(self) -> None:
        claimed = _word_to_int(
            _claim(r"\*\*(\w+) parallel jobs\*\*", _readme(), "README.md").group(1),
            "README.md",
        )
        jobs = _ci_jobs()
        assert claimed == len(jobs), (
            f"README.md claims {claimed} parallel CI jobs; ci.yml declares "
            f"{len(jobs)}: {sorted(jobs)}"
        )

    def test_no_ci_job_waits_on_another(self) -> None:
        # "Parallel" is the load-bearing word: nine jobs behind a `needs:`
        # chain is one job that takes nine times as long, and the sentence
        # would still be arithmetically true.
        serialised = sorted(
            name
            for name, body in _ci_jobs().items()
            if isinstance(body, dict) and "needs" in body
        )
        assert not serialised, (
            f"these CI jobs wait on another job: {serialised}. The README "
            "calls the nine parallel; a `needs:` edge makes that false "
            "without changing the count."
        )


class TestThePythonSuiteCount:
    def test_the_collected_suite_clears_the_readme_floor(self) -> None:
        floor = _digits(
            _claim(r"\*\*over ([\d,]+) tests\*\*", _readme(), "README.md").group(1)
        )
        collected, _ = _collect_tiers()
        assert collected > floor, (
            f"README.md claims over {floor:,} Python tests; `pytest "
            f"--collect-only` finds {collected:,}. If the suite legitimately "
            "shrank, lower the sentence and say why in the pull request — a "
            "drop with no explanation is the thing this floor is for."
        )

    def test_the_python_floor_has_not_fallen_out_of_date(self) -> None:
        floor = _digits(
            _claim(r"\*\*over ([\d,]+) tests\*\*", _readme(), "README.md").group(1)
        )
        collected, _ = _collect_tiers()
        assert collected - floor <= _FLOOR_BAND, (
            f"the README's floor of {floor:,} is {collected - floor:,} behind "
            f"the collected {collected:,}, which is more than the "
            f"{_FLOOR_BAND:,} this file allows. A floor that far behind the "
            "truth has stopped describing the suite. Raise the sentence to "
            "the next round hundred below the current count."
        )


class TestTheVitestCounts:
    def test_the_readme_matches_the_last_coverage_reseed(self) -> None:
        """An agreement between two documents, and no more than that.

        Nothing here runs Vitest — this is the Python tier, and a count it
        obtained by shelling out to `npm` would be slower and no more
        honest. What it does catch is precisely what went wrong: the
        thresholds in `web/vitest.config.mts` were re-seeded twice, each
        re-seed recording the suite size it measured, and the README was
        left quoting a figure from two re-seeds earlier.
        """
        match = _claim(
            r"\*\*([\d,]+) Vitest tests across (\d+) files\*\*",
            _readme(),
            "README.md",
        )
        claimed = (_digits(match.group(1)), int(match.group(2)))
        recorded = _last_vitest_reseed()
        assert claimed == recorded, (
            f"README.md says {claimed[0]:,} Vitest tests across {claimed[1]} "
            f"files; the last coverage re-seed recorded in "
            f"web/vitest.config.mts measured {recorded[0]:,} across "
            f"{recorded[1]}. Re-seeding those thresholds and leaving this "
            "sentence alone is how the previous figure got two re-seeds "
            "behind."
        )


# ---------------------------------------------------------------------------
# R25 — the e2e tier is built, and gates
# ---------------------------------------------------------------------------


class TestTheE2eTier:
    def test_the_readme_count_is_the_marker_selected_count(self) -> None:
        match = _claim(
            r"\*\*(\w+) tests across (\w+) modules\*\*", _readme(), "README.md"
        )
        claimed_tests = _word_to_int(match.group(1), "README.md")
        _, selected = _collect_tiers()
        assert claimed_tests == selected, (
            f"README.md claims {claimed_tests} tests in the `e2e` tier; "
            f"`pytest -m e2e` selects {selected}. An equality rather than a "
            "floor here on purpose: the tier is small and deliberately "
            "bounded, so a seventeenth test is worth the sentence it costs."
        )

    def test_the_readme_module_count_is_the_directory(self) -> None:
        match = _claim(
            r"\*\*(\w+) tests across (\w+) modules\*\*", _readme(), "README.md"
        )
        claimed_modules = _word_to_int(match.group(2), "README.md")
        present = sorted(path.name for path in _E2E_DIR.glob("test_*.py"))
        assert claimed_modules == len(present), (
            f"README.md claims {claimed_modules} modules under tests/e2e/; "
            f"there are {len(present)}: {present}"
        )

    def test_the_marker_and_the_directory_are_the_same_set(self) -> None:
        """The claim is about a *tier*, and the tier is the marker.

        `docs/testing.md`'s rule is that a directory groups by purpose and
        never selects a tier, so counting files under `tests/e2e/` proves
        nothing on its own. This is the test that lets the two counts above
        be read as one claim: every module in that directory declares the
        marker, and no module outside it does.
        """
        marked = {
            path
            for path in _ROOT.joinpath("tests").rglob("test_*.py")
            if re.search(r"pytest\.mark\.e2e", path.read_text(encoding="utf-8"))
        }
        in_directory = set(_E2E_DIR.glob("test_*.py"))
        stray = sorted(str(p.relative_to(_ROOT)) for p in marked - in_directory)
        unmarked = sorted(str(p.relative_to(_ROOT)) for p in in_directory - marked)
        assert not stray, f"e2e-marked modules outside tests/e2e/: {stray}"
        assert not unmarked, f"modules in tests/e2e/ with no e2e marker: {unmarked}"

    def test_the_tier_runs_in_ci(self) -> None:
        """"Gates every pull request" is a claim about a workflow step.

        Before WO-A13 the tier existed and nothing ran it: `-m "not e2e"`
        was the only Python selection in CI, so the tier's assertions —
        including "nothing is spent before you approve the plan" — had
        their strongest form in a suite no pull request executed.
        """
        jobs = _ci_jobs()
        tests_job = jobs.get("tests")
        assert isinstance(tests_job, dict), "ci.yml declares no `tests` job"
        steps = tests_job.get("steps")
        assert isinstance(steps, list)
        runs = " ".join(
            str(step.get("run", "")) for step in steps if isinstance(step, dict)
        )
        assert "make test-e2e" in runs, (
            "the `tests` job no longer runs `make test-e2e`, so the `e2e` "
            "tier gates nothing — which is the state the README described "
            "for as long as it was true and kept describing after it was not"
        )


# ---------------------------------------------------------------------------
# R33 — the routing saving is arithmetic, and says so
# ---------------------------------------------------------------------------


class TestTheModelledRoutingSaving:
    def test_haiku_is_one_third_of_sonnet_on_both_token_directions(self) -> None:
        prices = _model_prices()
        haiku = prices["claude-haiku-4-5-20251001"]
        sonnet = prices["claude-sonnet-4-6"]
        for direction in ("input", "output"):
            assert haiku[direction] * 3 == pytest.approx(sonnet[direction]), (
                f"Haiku is no longer exactly one third of Sonnet on "
                f"{direction} tokens ({haiku[direction]} against "
                f"{sonnet[direction]}). The README's modelled routing saving "
                "is `2/3 x routed share`, which is that ratio and nothing "
                "else — re-derive the band before editing the price table."
            )

    def test_the_readme_band_is_the_arithmetic_it_states(self) -> None:
        match = _claim(
            r"\*\*(\d+)-(\d+)% if those three agents carry (\d+)-(\d+)% of it\*\*",
            _readme(),
            "README.md",
        )
        low_saving, high_saving, low_share, high_share = (
            int(group) for group in match.groups()
        )
        prices = _model_prices()
        ratio = (
            prices["claude-haiku-4-5-20251001"]["input"]
            / prices["claude-sonnet-4-6"]["input"]
        )
        for share, saving in ((low_share, low_saving), (high_share, high_saving)):
            expected = round(share * (1 - ratio))
            assert expected == saving, (
                f"the README says a {share}% routed share gives a {saving}% "
                f"cut; the shipped price table gives {expected}%. The whole "
                "point of stating the arithmetic was that the number could "
                "be recomputed instead of remembered."
            )

    def test_the_readme_still_says_the_saving_is_unmeasured(self) -> None:
        """A tripwire on the qualifier, and not a proof of anything.

        No measurement of this saving exists anywhere in the repository and
        none can be manufactured here — the eval campaign that would
        produce one has never run. What can be defended mechanically is
        that the sentence keeps saying so, because the failure this row
        records is a modelled figure being read as a measured one.
        """
        text = _readme()
        assert "modelled, not measured" in text, (
            "README.md no longer says the routing saving is modelled. It is: "
            "no run in this repository has ever been priced under the routed "
            "mapping, and ADR 0021 defers that evidence to paired-diff eval "
            "runs that have never happened."
        )


# ---------------------------------------------------------------------------
# A24, A09 — two closed sets in docs/architecture.md
# ---------------------------------------------------------------------------


class TestTheInstrumentCount:
    def test_the_architecture_number_is_the_measured_number(self) -> None:
        claimed = _word_to_int(
            _claim(
                r"\*\*([\w-]+)\*\* OTel instruments", _architecture(), "architecture.md"
            ).group(1),
            "docs/architecture.md",
        )
        assert claimed == len(INSTRUMENTS), (
            f"docs/architecture.md claims {claimed} OTel instruments; the AST "
            f"scan of `src/` finds {len(INSTRUMENTS)}: "
            f"{sorted(INSTRUMENTS)}. This sentence read `nine` across three "
            "ADRs' worth of additions, because nothing read it back."
        )


class TestTheJobKindBranches:
    def test_the_architecture_number_is_the_measured_number(self) -> None:
        claimed = _word_to_int(
            _claim(
                r"\*\*(\w+) further branches on `job\.kind`\*\*",
                _architecture(),
                "architecture.md",
            ).group(1),
            "docs/architecture.md",
        )
        branches = _run_job_kind_branches()
        assert claimed == len(branches), (
            f"docs/architecture.md names {claimed} further `job.kind` "
            f"branches in `run_job`; the AST finds {len(branches)}, at "
            f"src/api/runner.py lines {branches}. An equality because the "
            "claim is that the set is closed — the sentence's predecessor "
            "said `nothing else branches on the kind` while five did."
        )


# ---------------------------------------------------------------------------
# R16 — every non-trivial decision has an ADR
# ---------------------------------------------------------------------------


class TestTheAdrIndex:
    """The half of R16 that is mechanisable.

    "Non-trivial" is a judgement and no test will ever hold it. The
    reverse direction is arithmetic and was checked by nothing at all: the
    index and the directory have to be the same set, and an ADR a document
    links to has to exist.
    """

    def test_the_index_and_the_directory_are_the_same_set(self) -> None:
        on_disk = {path.name for path in _DECISIONS.glob("[0-9][0-9][0-9][0-9]-*.md")}
        index = (_DECISIONS / "README.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"\]\((\d{4}-[a-z0-9-]+\.md)\)", index))
        assert not listed - on_disk, (
            f"the ADR index links files that do not exist: "
            f"{sorted(listed - on_disk)}"
        )
        assert not on_disk - listed, (
            f"these ADRs exist and the index does not list them: "
            f"{sorted(on_disk - listed)}. An unindexed ADR is a decision "
            "nobody can find, which is the same as not having written it."
        )

    def test_every_adr_the_two_documents_cite_exists(self) -> None:
        missing: list[str] = []
        for label, text in (
            ("README.md", _readme()),
            ("docs/architecture.md", _architecture()),
        ):
            for target in re.findall(
                r"\]\((?:docs/)?decisions/(\d{4}-[a-z0-9-]+\.md)\)", text
            ):
                if not (_DECISIONS / target).is_file():
                    missing.append(f"{label} -> {target}")
        assert not missing, f"documents link ADRs that do not exist: {missing}"
