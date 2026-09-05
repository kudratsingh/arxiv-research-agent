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

Four kinds of claim are not mechanisable and are not weakened here to
make one pass. Weakening prose until a test can pass it would be a worse
outcome than the drift this file exists to catch, so the gaps stay in the
index instead:

1. **"Quality preserved."** There is no quality measurement anywhere in
   this repository — no eval campaign has ever completed. What is checked
   about the routing claim is the *arithmetic* (the price ratio the
   modelled band is computed from) and the presence of the qualifier that
   says the band is modelled. That second check is a tripwire against the
   qualifier being deleted, not a proof of anything.
2. **The nightly eval's state**, as distinct from what the repository
   *says* about it. `disabled_manually` is an attribute GitHub stores
   against the workflow and it is not in the tree at all, while the
   workflow file still carries a `cron:` that does not fire. WO-B2 made
   both nightly files say that about themselves in prose, which is what
   `TestTheNightlyEvalState` reads: the four artifacts that describe the
   nightly — `README.md`, `docs/eval.md`, `docs/architecture.md` and the
   workflow — are held to one story, so re-enabling the workflow and
   updating only one of them goes red. `docs/architecture.md` joined
   that set in WO-D2 and was the last claim in the index still marked
   **False**; the index had recorded that its test was "already
   written", and it was not — no test in this repository read that
   document's nightly sentence at all. That is an agreement between documents and not a probe of
   GitHub; nothing here can tell you the workflow is really off, and the
   54 failed runs live in Actions history where no test reaches them.
3. **Whether a feature has a flag at all.** `TestTheFlagSet` enumerates
   `Settings`' `enable_*` fields and holds the README's flag section
   against them in both directions, which catches a flag nobody
   documented. It cannot catch a *feature* nobody flagged, because
   nothing can enumerate features. R15 stays Partial for that reason.
4. **Anything requiring a browser, a paid call, or a screenshot.** The
   Vitest figure is checked against `web/vitest.config.mts`'s own record
   of it, not against a run: this is a Python tier and running the web
   suite from it would be both slow and a lie about what was measured.
   The check is therefore an *agreement between two documents*, with
   two legs added to keep the source of truth from rotting quietly: the
   re-seed note is pinned to the coverage thresholds it claims to have
   measured, so a re-seed that skips the note fails rather than leaving
   the README agreeing with a stale source, and the note's *file* count
   is banded against the files actually on disk, because the other way
   a count of record goes stale is by ageing. On the tree WO-C2 was
   written against, the record (3,380 tests across 155 files) sits 97
   tests and 3 files behind a real run (3,477 across 158) — within the
   band, and a measured illustration of why the tests half of that
   figure is called an agreement and not a measurement. Likewise
   `TestTheScreenshotMechanism` checks the mechanism that makes the
   screenshots free (the seed script, the pinned sentinel) and not the
   committed PNGs, which nothing in this repository binds to a run.

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
test here goes red for each. WO-C2 adds five more: restore "so Sprint 1
behavior stays byte-identical" without the three backends it now names,
delete the enumeration of the eleven `enable_*` flags outside the table,
put the README's nightly paragraph back to "the workflow is wired" while
`docs/eval.md` says disabled, drop the seed script's
Postgres-and-Redis-only property, or re-seed `web/vitest.config.mts`'s
coverage thresholds without recording the measurement they came from.
WO-D2 adds three: restore `docs/architecture.md`'s unqualified "run
nightly in CI with regression diffing", put `docs/demo.md`'s two links
back to `eval.md#status-no-green-campaign-yet` (an anchor no heading has
minted since the section was renamed, and one GitHub resolves by
silently dropping the reader at the top of the page), or render an image
in `README.md` that `web/e2e/readme.spec.ts` does not capture.
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
_EVAL_NIGHTLY: Final = _ROOT / ".github" / "workflows" / "eval-nightly.yml"
_LIGHTHOUSE_NIGHTLY: Final = _ROOT / ".github" / "workflows" / "nightly.yml"
_EVAL_DOC: Final = _ROOT / "docs" / "eval.md"
_VITEST_CONFIG: Final = _ROOT / "web" / "vitest.config.mts"
_DECISIONS: Final = _ROOT / "docs" / "decisions"
_E2E_DIR: Final = _ROOT / "tests" / "e2e"
_SEED_SCRIPT: Final = _ROOT / "web" / "e2e" / "fixtures" / "seed.sh"
_README_SHOTS: Final = _ROOT / "web" / "e2e" / "readme.spec.ts"
_COMPOSE_E2E: Final = _ROOT / "web" / "e2e" / "support" / "compose.e2e.yml"

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
    "eight": 8,
    "nine": 9,
    "eleven": 11,
    "twelve": 12,
    "sixteen": 16,
    "nineteen": 19,
    "twenty": 20,
    "twenty-one": 21,
    "twenty-two": 22,
}

#: The words `README.md` uses for the three standalone storage backends,
#: mapped to the values `src/config.py` actually ships. Same rule as
#: `_NUMBER_WORDS`: a word this map does not know is a failure, not a
#: silently skipped sentence.
_BACKEND_WORDS: Final[dict[str, str]] = {
    "in-memory": "memory",
    "Redis": "redis",
    "SQLite": "sqlite",
    "Postgres": "postgres",
    "disk": "disk",
}

#: How far the Vitest count of record may fall behind the number of
#: test files actually in `web/`. The recorded count moves only on a
#: coverage re-seed, so it is *expected* to lag — the band is what
#: separates lagging from abandoned, exactly as `_FLOOR_BAND` does for
#: the Python floor. Roughly a work order's worth of new files.
_VITEST_FILE_BAND: Final = 15

#: How far a seeded coverage threshold may sit below the measurement its
#: own re-seed note records. `web/vitest.config.mts` seeds three of its
#: four columns *at* the measurement and gives `functions` a little
#: headroom because that column's denominator moves with which stories
#: run; the widest headroom in the file's history is 0.33 points.
_THRESHOLD_HEADROOM: Final = 0.5


def _prose(path: pathlib.Path) -> str:
    """One document as a single line, so a claim can span a line break.

    Both documents are hard-wrapped at ~72 columns, so every sentence
    below is split across lines at a position nobody controls: reflowing
    a paragraph moves the break and would otherwise silently stop a
    pattern matching — which `_claim` would then report as a missing
    sentence rather than as a stale number. Collapsing whitespace first
    makes the checks depend on the words and not on the wrapping.

    Blockquote markers come off for the same reason. The screenshot
    note is a hard-wrapped `>` block, so without this every line break
    inside it would put a `>` in the middle of a sentence, at a column
    nobody chose.
    """
    unquoted = re.sub(
        r"^\s*> ?", "", path.read_text(encoding="utf-8"), flags=re.MULTILINE
    )
    return re.sub(r"\s+", " ", unquoted)


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
    notes = re.findall(r"([\d,]+) tests across (\d+) files", _flattened_vitest_config())
    assert notes, (
        "web/vitest.config.mts records no `N tests across M files` note, so "
        "the README's Vitest figure has no source of truth in the tree"
    )
    tests, files = notes[-1]
    return _digits(tests), int(files)


def _flattened_vitest_config() -> str:
    """The Vitest config with comment prefixes stripped, as one line."""
    text = _VITEST_CONFIG.read_text(encoding="utf-8")
    return " ".join(re.sub(r"^\s*//\s?", "", line) for line in text.splitlines())


#: `2874/2928 statements, 2002/2128 branches, …` — the covered-over-total
#: pairs a re-seed note records for the run it measured.
_MEASURED_COLUMNS: Final = re.compile(
    r"(\d+)/(\d+) statements, (\d+)/(\d+) branches, "
    r"(\d+)/(\d+) functions, (\d+)/(\d+) lines"
)

#: The four numbers the config actually gates on.
_SEEDED_THRESHOLDS: Final = re.compile(
    r"thresholds:\s*\{\s*statements:\s*([\d.]+),\s*branches:\s*([\d.]+),\s*"
    r"functions:\s*([\d.]+),\s*lines:\s*([\d.]+),?\s*\}"
)


def _last_vitest_measurement() -> dict[str, float]:
    """The percentages the *last* re-seed note says it measured.

    Read from the raw counts the note records rather than from the
    percentages it also quotes, because the counts are what a re-seeder
    copies out of `coverage-summary.json` and the percentages are the
    part they round. Anchored to the last `N tests across M files` note —
    the same note `_last_vitest_reseed` calls the count of record — so
    the suite size, the measurement and the seeded thresholds are one
    fact rather than three that can drift apart.
    """
    flattened = _flattened_vitest_config()
    anchors = list(re.finditer(r"([\d,]+) tests across (\d+) files", flattened))
    assert anchors, "web/vitest.config.mts records no `N tests across M files` note"
    measured = _MEASURED_COLUMNS.search(flattened, anchors[-1].end())
    assert measured is not None, (
        "the last `N tests across M files` note in web/vitest.config.mts "
        "records no `covered/total` counts after it, so the coverage "
        "thresholds below it have nothing to be checked against. A re-seed "
        "note is the only source of truth for both numbers this repository "
        "quotes about the web suite; write it in the same shape as the one "
        "it replaces."
    )
    groups = [int(group) for group in measured.groups()]
    return {
        column: 100.0 * covered / total
        for column, (covered, total) in zip(
            ("statements", "branches", "functions", "lines"),
            zip(groups[0::2], groups[1::2], strict=True),
            strict=True,
        )
    }


def _seeded_vitest_thresholds() -> dict[str, float]:
    seeded = _SEEDED_THRESHOLDS.search(_VITEST_CONFIG.read_text(encoding="utf-8"))
    assert seeded is not None, (
        "web/vitest.config.mts declares no four-column `thresholds:` block"
    )
    return {
        column: float(value)
        for column, value in zip(
            ("statements", "branches", "functions", "lines"),
            seeded.groups(),
            strict=True,
        )
    }


# ---------------------------------------------------------------------------
# `Settings` as the sentences describe it
# ---------------------------------------------------------------------------


def _declared_defaults() -> dict[str, object]:
    """Every `Settings` field's *declared* default.

    `Settings()` would read the ambient environment, and a developer with
    `JOB_STORE=redis` exported would then be told the README is wrong
    about what the repository ships. The field defaults are the shipped
    values and nothing else can move them.
    """
    from src.config import Settings

    return {name: field.default for name, field in Settings.model_fields.items()}


def _enable_flags() -> dict[str, bool]:
    return {
        name: bool(default)
        for name, default in _declared_defaults().items()
        if name.startswith("enable_")
    }


def _flag_section() -> tuple[list[str], list[str]]:
    """`README.md`'s flag section, split into (table flags, prose flags).

    The table is the workflow-behavior set the section is about; the
    prose around it is where every other `enable_*` flag has to be
    named. Splitting on the leading `|` is what lets one check assert
    that the two together are all of them.
    """
    lines = _README.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## What lives behind")]
    assert starts, "README.md no longer has a `## What lives behind flags` section"
    start = starts[0]
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## ")),
        len(lines),
    )
    table: list[str] = []
    prose: list[str] = []
    for line in lines[start:end]:
        (table if line.lstrip().startswith("|") else prose).extend(
            re.findall(r"`(enable_[a-z_]+)`", line)
        )
    return table, prose


def _vitest_files() -> int:
    """How many files `vitest run` would collect under `web/`.

    The two globs are mirrored from the two projects rather than
    guessed: `web/vitest.config.mts`'s `unit` project collects
    `tests/**/*.test.{ts,tsx}`, and `.storybook/main.ts` hands the
    `storybook` project `components/**/*.stories.@(ts|tsx)`. Their sum
    is the "Test Files" line a run prints, which is what the README's
    `across N files` is about.
    """
    web = _ROOT / "web"
    unit = [
        path
        for suffix in ("*.test.ts", "*.test.tsx")
        for path in web.joinpath("tests").rglob(suffix)
    ]
    stories = [
        path
        for suffix in ("*.stories.ts", "*.stories.tsx")
        for path in web.joinpath("components").rglob(suffix)
    ]
    return len(unit) + len(stories)


def _seed_script_body() -> str:
    """`seed.sh` with its whole-line comments removed.

    The comments are where the script *describes* `POST /research`
    ("it never calls" it), so a scan that kept them would find the
    endpoint in the file that proves it is never called.
    """
    return "\n".join(
        line
        for line in _SEED_SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


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

    def test_the_recorded_file_count_has_not_fallen_behind_the_tree(self) -> None:
        """The other way that source of truth goes stale: by ageing.

        The check above catches a re-seed that edited the thresholds and
        skipped the note. This catches the note simply being left where
        it was while `web/` grew — the count of record moves only on a
        coverage re-seed, so some lag is by design, and a *band* is what
        separates lag from abandonment. The tests half of the figure
        cannot be checked this way (nothing here runs Vitest), but the
        files half is on disk, so half of the number stops being purely
        an agreement between two documents.
        """
        _, recorded = _last_vitest_reseed()
        present = _vitest_files()
        assert recorded <= present, (
            f"web/vitest.config.mts records a measurement over {recorded} "
            f"files; `web/` holds {present}. A note claiming more files than "
            "exist is a note taken on a different tree."
        )
        assert present - recorded <= _VITEST_FILE_BAND, (
            f"the Vitest count of record was measured over {recorded} files "
            f"and `web/` now holds {present}, which is more than the "
            f"{_VITEST_FILE_BAND} files this file allows a record to lag by. "
            "The number the README quotes has stopped describing the suite: "
            "re-seed the coverage thresholds, write the note with the new "
            "`N tests across M files`, and update the README sentence. This "
            "firing is not a defect — it is the occasional nudge the "
            "equality design pays for the rest of the time."
        )

    def test_the_reseed_note_is_the_thresholds_it_seeded(self) -> None:
        """The source of truth has to be able to go stale *visibly*.

        The check above makes the README agree with a comment. A comment
        is not authoritative on its own: a re-seed that edited the four
        `thresholds:` numbers and skipped the note would leave the
        README agreeing with a source that no longer describes the
        suite, and both checks would stay green.

        This is what binds the note to something executable. Every
        re-seed in this file's history has recorded the covered/total
        counts it measured, and the thresholds are seeded *at* those
        counts or a little under — three columns to the decimal, and
        `functions` with the headroom its note explains. So a threshold
        above the measurement its own note records is a note left
        behind by the numbers it is supposed to justify, and a threshold
        far below it is a floor nobody re-seeded.
        """
        measured = _last_vitest_measurement()
        seeded = _seeded_vitest_thresholds()
        stale = []
        for column, threshold in seeded.items():
            if threshold > measured[column] + 1e-9:
                stale.append(
                    f"{column}: gated at {threshold} but the last re-seed note "
                    f"measured {measured[column]:.2f}"
                )
            elif measured[column] - threshold > _THRESHOLD_HEADROOM:
                stale.append(
                    f"{column}: gated at {threshold}, {measured[column] - threshold:.2f} "
                    f"below the {measured[column]:.2f} the note measured"
                )
        assert not stale, (
            "web/vitest.config.mts's coverage thresholds and its last re-seed "
            "note disagree:\n  " + "\n  ".join(stale) + "\nThe note is the only "
            "source of truth for the web suite's size and coverage — the "
            "README quotes it and nothing runs Vitest from this tier — so a "
            "re-seed writes both or neither. Record the new counts in the "
            "same shape as the note above the thresholds, including the "
            "`N tests across M files` line the README is checked against."
        )


# ---------------------------------------------------------------------------
# R25 — the e2e tier is built, and gates
# ---------------------------------------------------------------------------


class TestTheE2eTier:
    def test_the_readme_count_is_the_marker_selected_count(self) -> None:
        match = _claim(
            r"\*\*([\w-]+) tests across (\w+) modules\*\*", _readme(), "README.md"
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
            r"\*\*([\w-]+) tests across (\w+) modules\*\*", _readme(), "README.md"
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


# ---------------------------------------------------------------------------
# R11 — the standalone storage defaults
# ---------------------------------------------------------------------------


class TestTheStandaloneDefaults:
    """Three defaults that existed only as Pydantic field values.

    `tests/test_config.py::TestDefaults::test_standalone_storage_defaults`
    is the other half of this and asserts the same three values as the
    config surface's own contract. The two are not a duplicate: that one
    says what the repository ships, this one says the README describes
    what the repository ships, and it reads the backends out of the
    sentence so there is no second copy of them here.

    The sentence's other half — that Sprint 1 behaviour stays
    *byte-identical* — was removed rather than mechanised. Nothing in
    this repository retains a Sprint 1 artifact to diff against and the
    outputs are model-generated, so byte-identity was never measurable
    and the claim could not be made true by any test. What replaced it
    is the configuration claim, which is checkable and is checked here.
    """

    def test_the_readme_names_the_three_backends_the_settings_ship(self) -> None:
        match = _claim(
            r"defaults to an ([\w-]+) job store, ([\w-]+) checkpoints and a "
            r"([\w-]+) paper cache",
            _readme(),
            "README.md",
        )
        defaults = _declared_defaults()
        wrong = []
        fields = ("job_store", "checkpoint_backend", "paper_cache")
        for word, field in zip(match.groups(), fields, strict=True):
            claimed = _BACKEND_WORDS.get(word)
            assert claimed is not None, (
                f"README.md calls the {field} default {word!r}, which "
                "`_BACKEND_WORDS` does not know. Add it there in the same "
                "commit rather than letting the check pass over a value it "
                "cannot read."
            )
            if defaults[field] != claimed:
                wrong.append(f"{field}: README says {claimed!r}, ships {defaults[field]!r}")
        assert not wrong, (
            "the standalone storage defaults have moved out from under the "
            "README:\n  " + "\n  ".join(wrong) + "\nThis sentence is what a "
            "reader trusts when they run the CLI with no Redis and no "
            "Postgres, and it went unread by any test until WO-C2."
        )

    def test_none_of_the_three_needs_a_service(self) -> None:
        """The point of the sentence, stated as the values it excludes.

        `memory`/`sqlite`/`disk` is not an arbitrary triple: it is the
        set of options that need no Redis and no Postgres. Naming the
        service-backed values here is what makes a default flipped to
        `redis` or `postgres` fail with the reason rather than with a
        diff.
        """
        defaults = _declared_defaults()
        needs_a_service = sorted(
            f"{field}={defaults[field]!r}"
            for field in ("job_store", "checkpoint_backend", "paper_cache")
            if defaults[field] in {"redis", "postgres"}
        )
        assert not needs_a_service, (
            f"these defaults now require a service the standalone path does "
            f"not start: {needs_a_service}. The README promises a checkout "
            "outside Compose runs the Sprint 1 storage path; changing a "
            "default to a service backend breaks that promise for every "
            "reader who follows the Python-only quickstart."
        )


# ---------------------------------------------------------------------------
# R14 — the screenshots cost nothing, and what that can mean
# ---------------------------------------------------------------------------


class TestTheScreenshotMechanism:
    """The mechanism, and — since WO-D2 — the images themselves.

    WO-C2 checked the mechanism and said plainly what it could not
    check: nothing bound a committed PNG to a run, so a hand-edited
    screenshot passed everything here. It judged the fix — capturing the
    images as Playwright snapshots — disproportionate. The owner asked
    for it anyway, so `web/e2e/readme.spec.ts` now captures all five
    through the same harness `visual.spec.ts` uses, with the snapshot
    path pointing at `docs/images/` so the baseline IS the file the
    README renders.

    **What this class can hold of that, and what it cannot.** The
    comparison itself is a browser-tier gate that runs on darwin only:
    a snapshot has to live where the README references it, that path has
    no room for the `{platform}` segment `visual.spec.ts` relies on, and
    Linux rasterises the same font differently — so the Linux `web-e2e`
    job skips it, exactly as it skips the visual sweep. That is stated
    in the spec, in the README and in the index rather than implied
    away.

    What runs in CI is below: the seed script still writes behind the
    API, the stack is still pinned to a key that cannot buy anything,
    and every image the README renders is now required to be one the
    spec captures — so adding a screenshot to the README without a
    capture for it goes red on Linux like everywhere else.
    """

    def test_the_seed_script_writes_behind_the_api(self) -> None:
        body = _seed_script_body()
        assert re.search(r"\bpsql\b", body) and re.search(r"\bredis-cli\b", body), (
            "web/e2e/fixtures/seed.sh no longer writes through psql and "
            "redis-cli, so the README's 'written directly into Postgres and "
            "Redis' describes something that is not there any more"
        )
        called = sorted(
            {
                match.group(0)
                for match in re.finditer(r"/research\b|-X\s+POST|--request\s+POST", body)
            }
        )
        assert not called, (
            f"web/e2e/fixtures/seed.sh now issues {called}. Safety property 4 "
            "in its own header — 'It never calls `POST /research`' — is the "
            "whole of the README's zero-spend screenshot claim: a fixture "
            "written *through* the API is a job, and a job is a model call."
        )

    def test_the_stack_is_pinned_to_the_key_the_readme_names(self) -> None:
        sentinel = _claim(
            r"captured from the seeded local Compose stack with "
            r"`ANTHROPIC_API_KEY=([a-z-]+)`",
            _readme(),
            "README.md",
        ).group(1)
        compose = _COMPOSE_E2E.read_text(encoding="utf-8")
        assert re.search(rf"ANTHROPIC_API_KEY:\s*{re.escape(sentinel)}\b", compose), (
            f"README.md says the screenshots come from a stack pinned to "
            f"`{sentinel}`; web/e2e/support/compose.e2e.yml pins something "
            "else. The sentinel is invalid on purpose — it is what makes "
            "'no model call was made' true rather than merely intended."
        )

    def test_every_screenshot_the_readme_shows_exists(self) -> None:
        referenced = sorted(set(re.findall(r"(docs/images/[\w.-]+\.png)", _readme())))
        assert referenced, "README.md references no screenshots at all"
        missing = [path for path in referenced if not (_ROOT / path).is_file()]
        assert not missing, (
            f"README.md renders images that are not in the tree: {missing}"
        )

    def test_every_screenshot_the_readme_shows_is_captured_by_the_spec(self) -> None:
        """The half of R14's binding that runs on every platform.

        The snapshot comparison is darwin-only for a reason the spec
        explains, which would leave a Linux CI run with no opinion at
        all about these files. This is the opinion it can have: the set
        of images `README.md` renders and the set `readme.spec.ts`
        captures are the same set. Add a screenshot to the README by
        hand and it fails; delete a shot from the table and leave the
        README rendering it and it fails.

        Read out of the spec's `file:` entries rather than out of a list
        kept here, for the reason every check in this module is written
        that way — a second copy of the inventory is a second thing to
        forget.
        """
        spec = _README_SHOTS.read_text(encoding="utf-8")
        captured = {f"docs/images/{name}.png" for name in re.findall(r'file: "([\w.-]+)"', spec)}
        assert captured, (
            f"{_README_SHOTS.relative_to(_ROOT)} declares no `file:` entries, so "
            "this check has nothing to compare against. If the capture suite "
            "has been rewritten, this pattern moves with it rather than being "
            "left matching nothing."
        )
        rendered = set(re.findall(r"(docs/images/[\w.-]+\.png)", _readme()))
        uncaptured = sorted(rendered - captured)
        orphaned = sorted(captured - rendered)
        assert not uncaptured, (
            f"README.md renders these images and {_README_SHOTS.name} does not "
            f"capture them: {uncaptured}. An image nothing captures is back to "
            "being an asset no run produced — which is the whole of what R14 "
            "was Partial for. Add a row to that file's `SHOTS` table and "
            "regenerate with `npm run e2e:readme:update` on macOS."
        )
        assert not orphaned, (
            f"{_README_SHOTS.name} captures images README.md no longer "
            f"renders: {orphaned}. Either the README dropped a screenshot and "
            "the table did not, or a file was renamed in one place only."
        )


# ---------------------------------------------------------------------------
# R15 — the flag set is enumerated, in both directions
# ---------------------------------------------------------------------------


class TestTheFlagSet:
    """"Every feature after Sprint 1 is behind an independent flag."

    Three separable assertions live in that sentence and two of them are
    mechanisable. **Independent** is: each flag in the table can be
    switched on by itself, which is exactly what an A/B against the
    Sprint 1 baseline requires. **Behind a flag** is, in the direction a
    reflection test can see: every `enable_*` field `Settings` declares
    is accounted for by the README, either as a workflow-behavior row in
    the table or by name in the prose around it.

    The direction that stays open is the forward one — a *feature*
    shipped with no flag adds no field, so no reflection over fields can
    see it. R15 is Partial for that reason and the index says so.
    """

    def test_the_readme_counts_every_enable_flag(self) -> None:
        claimed = _word_to_int(
            _claim(
                r"declares \*\*(\w+) `enable_\*` flags\*\*", _readme(), "README.md"
            ).group(1),
            "README.md",
        )
        flags = _enable_flags()
        assert claimed == len(flags), (
            f"README.md counts {claimed} `enable_*` flags; `Settings` declares "
            f"{len(flags)}: {sorted(flags)}. A flag the README does not count "
            "is a feature a reader cannot find the switch for."
        )

    def test_the_table_and_the_prose_together_are_every_flag(self) -> None:
        table, prose = _flag_section()
        documented = set(table) | set(prose)
        flags = set(_enable_flags())
        undocumented = sorted(flags - documented)
        phantom = sorted(documented - flags)
        assert not undocumented, (
            f"these `enable_*` flags are in `Settings` and nowhere in the "
            f"README's flag section: {undocumented}. This is the check that "
            "makes the section an enumeration rather than a sample — put a "
            "new workflow-behavior flag in the table, and anything else in "
            "the paragraph under it."
        )
        assert not phantom, (
            f"the README's flag section names flags `Settings` does not "
            f"declare: {phantom}"
        )

    def test_the_table_is_the_count_it_claims(self) -> None:
        table, prose = _flag_section()
        in_table = _word_to_int(
            _claim(
                r"the \*\*(\w+)\*\* of them in the table below are the Sprint 2-3 "
                r"workflow-behavior set",
                _readme(),
                "README.md",
            ).group(1),
            "README.md",
        )
        outside = _word_to_int(
            _claim(
                r"The other \*\*(\w+)\*\* `enable_\*` flags", _readme(), "README.md"
            ).group(1),
            "README.md",
        )
        assert (in_table, outside) == (len(set(table)), len(set(prose))), (
            f"README.md splits the flags {in_table} in the table and {outside} "
            f"outside it; the section itself lists {len(set(table))} and "
            f"{len(set(prose))}."
        )

    def test_every_flag_in_the_table_defaults_off(self) -> None:
        table, _ = _flag_section()
        flags = _enable_flags()
        on = sorted(flag for flag in set(table) if flags[flag])
        assert not on, (
            f"these workflow-behavior flags default on: {on}. The table's "
            "whole claim is that the shipped default is the Sprint 1 "
            "pipeline, so a default flipped to `True` makes every comparison "
            "against that baseline something else."
        )

    def test_the_flags_that_default_on_are_the_ones_the_readme_names(self) -> None:
        named = set(
            re.findall(
                r"`(enable_[a-z_]+)`",
                _claim(
                    r"default \*\*on\*\* \(([^)]*)\)", _readme(), "README.md"
                ).group(1),
            )
        )
        shipped = {flag for flag, default in _enable_flags().items() if default}
        assert named == shipped, (
            f"README.md says {sorted(named)} default on; `Settings` ships "
            f"{sorted(shipped)} on. A flag that quietly starts defaulting on "
            "is a feature nobody chose to run."
        )

    def test_every_flag_in_the_table_can_be_enabled_on_its_own(self) -> None:
        """What "independent" is asserted to mean, and where it stops.

        The Sprint 2-3 flags are independent in the strong sense — each
        constructs alone — because ADRs 0015 to 0020 each say so, and an
        A/B run that had to enable two flags to test one would not be an
        A/B of that one. The learning ladder is deliberately *not* like
        this: three of its four flags refuse to construct without the
        one below them, which is why they are outside the table and why
        the README says so instead of implying otherwise.
        """
        from pydantic import ValidationError

        from src.config import Settings

        table, _ = _flag_section()
        coupled = []
        for flag in sorted(set(table)):
            try:
                Settings(**{flag: True})  # type: ignore[arg-type]
            except ValidationError as error:
                coupled.append(f"{flag}: {str(error).splitlines()[1].strip()}")
        assert not coupled, (
            "these workflow-behavior flags cannot be enabled on their own, "
            "so the README's `independent flag` is no longer true of "
            "them:\n  " + "\n  ".join(coupled)
        )


# ---------------------------------------------------------------------------
# R28 — the nightly eval, told the same way by every document that tells it
# ---------------------------------------------------------------------------


class TestTheNightlyEvalState:
    """Three artifacts, one story — which is all this can be.

    The index's finding 3 was that `README.md` and `docs/eval.md`
    contradicted each other about the nightly eval and nothing noticed:
    one said the workflow was wired and failing every night, the other
    said it was disabled, and the workflow file carried a `cron:` that
    read like the first and behaved like the second. WO-B2 made both
    workflow files state their own disabled state in prose, which is the
    thing that made this checkable at all.

    What this does **not** assert is the state itself. `disabled_manually`
    lives in GitHub's settings for the repository and never appears in a
    checkout, so somebody could run `gh workflow enable` and every check
    here would stay green while all three documents became wrong
    together. What goes red is divergence: change the workflow file's
    header on the way to enabling it, or reword either document, and the
    other two have to move in the same commit.
    """

    def test_the_readme_says_the_workflow_is_disabled(self) -> None:
        workflow = _claim(
            r"nightly eval workflow is disabled at the repository\*\* "
            r"\(`disabled_manually`\)[^`]*`(\.github/workflows/[\w.-]+)`",
            _readme(),
            "README.md",
        ).group(1)
        assert (_ROOT / workflow).is_file(), (
            f"README.md's nightly paragraph names {workflow}, which is not in "
            "the tree"
        )

    def test_the_eval_doc_tells_the_same_story(self) -> None:
        text = _prose(_EVAL_DOC)
        assert "The workflow is disabled** (`disabled_manually`)" in text, (
            "docs/eval.md no longer says the nightly eval workflow is "
            "disabled. It and README.md described the workflow differently "
            "for long enough to become the assurance index's finding 3; if "
            "the state has changed, both documents and the workflow file's "
            "own header change together."
        )

    def test_the_architecture_doc_tells_the_same_story(self) -> None:
        """A25, and a correction to the index's account of why it survived.

        `docs/architecture.md`'s Evaluation bullet said the eval metrics
        "run nightly in CI with regression diffing" — flat, present
        tense, no qualifier — while `README.md`, `docs/eval.md` and both
        workflow files said the workflow was disabled. That is claim
        A25, the last one the index carried as **False**.

        The index's row said correcting it was "a one-line edit with the
        test already written". The edit was one line; the test was not
        written. This class held three artifacts and stopped there —
        `README.md`, `docs/eval.md` and the two workflow files — and
        nothing in the repository read `docs/architecture.md`'s nightly
        sentence at all, which is why the claim could sit false through
        WO-B1 and WO-C2 without a single test going red. A sentence no
        test reads is not "waiting on an edit"; it is unenforced. This
        is the fourth artifact joining the one story.

        Two assertions, because the sentence can rot in two directions.
        The qualifier can be deleted on the way back to the present
        tense, and the disabled state can be dropped while the qualifier
        stays — a document that says "designed to run nightly" and never
        says it does not is still letting a reader assume it does.
        """
        text = _architecture()
        window = 60
        unqualified = [
            text[max(0, match.start() - window) : match.end()]
            for match in re.finditer(r"runs? nightly in CI", text)
            if "designed to " not in text[max(0, match.start() - window) : match.start()]
        ]
        assert not unqualified, (
            "docs/architecture.md claims the eval runs nightly in CI without "
            f"saying it is designed to and does not: {unqualified}. The "
            "workflow is disabled at the repository, README.md and "
            "docs/eval.md both say so, and this document saying otherwise "
            "was the assurance index's claim A25 — false on main for the "
            "whole of Phase B and Phase C because no test read this file's "
            "nightly sentence."
        )
        assert "disabled at the repository** (`disabled_manually`)" in text, (
            "docs/architecture.md no longer records that the nightly eval "
            "workflow is disabled at the repository. The qualifier alone is "
            "not enough: 'designed to run nightly' with no statement of what "
            "actually happens leaves a reader to assume the schedule fires. "
            "If the workflow has been enabled, this document, README.md, "
            "docs/eval.md and the workflow file's own header change in one "
            "commit — that is what this class is for."
        )

    def test_both_nightly_workflows_say_they_are_disabled(self) -> None:
        """Both, because the standing constraint is about both.

        `planning/08-assurance/STATUS.md` carries `nightly-eval` and
        `nightly-lighthouse` under one line — both disabled, re-enabling
        either an owner decision. Only the eval one is described in
        `README.md`, so only that one has a document to contradict; the
        lighthouse workflow is held to saying what it is so that turning
        it on cannot be a silent edit.
        """
        silent = [
            str(path.relative_to(_ROOT))
            for path in (_EVAL_NIGHTLY, _LIGHTHOUSE_NIGHTLY)
            if "disabled_manually" not in path.read_text(encoding="utf-8")
        ]
        assert not silent, (
            f"these workflow files no longer record that they are disabled at "
            f"the repository: {silent}. Both nightlies are off under the "
            "campaign's standing constraint and re-enabling either is an "
            "owner decision — if one has been enabled, this test, README.md "
            "and docs/eval.md change in the same commit."
        )

    def test_the_cron_that_does_not_fire_says_so_beside_itself(self) -> None:
        """The line that made a naive test assert the opposite of the truth.

        A disabled workflow keeps its schedule in the file and GitHub
        ignores it, so `cron:` in these two files is a record of a chosen
        time rather than a statement about tonight. Deleting the
        paragraph that says so — while re-enabling, most likely — is the
        edit this catches.
        """
        for path in (_EVAL_NIGHTLY, _LIGHTHOUSE_NIGHTLY):
            text = path.read_text(encoding="utf-8")
            if "cron:" not in text:
                continue
            assert re.search(r"DOES NOT FIRE|does not fire", text), (
                f"{path.relative_to(_ROOT)} carries a `cron:` and no longer "
                "says whether it fires. It does not: the workflow is "
                "disabled at the repository, which the checkout cannot show, "
                "and that gap is exactly why the file has to say it in prose."
            )


# ---------------------------------------------------------------------------
# The citations themselves — a link that lands on nothing
# ---------------------------------------------------------------------------


def _heading_slugs(path: pathlib.Path) -> set[str]:
    """Every anchor GitHub will mint for one Markdown file's headings.

    GitHub's algorithm, and not an approximation of it: lower-case, drop
    everything that is not a word character, a space or a hyphen, then
    replace each remaining space with a hyphen **individually**. The last
    step is the one an approximation gets wrong — collapsing runs of
    whitespace first turns `S7 — The deployment gate` into
    `s7-the-deployment-gate`, where GitHub mints `s7--the-deployment-gate`
    because the em dash leaves two spaces behind. Two real anchors in
    `docs/architecture.md` are of exactly that shape, so a collapsing
    version of this function reports them as broken and this check would
    have arrived with two false failures.

    Fenced code is skipped: a `# comment` inside a shell block is not a
    heading, and several of these documents open with one.
    """
    slugs: set[str] = set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading is None:
            continue
        text = heading.group(1).strip().replace("`", "")
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"[^\w\s-]", "", text.lower())
        slugs.add(text.replace(" ", "-"))
    return slugs


class TestTheCrossDocumentAnchors:
    """A citation that lands on nothing, which is the index's own subject.

    `docs/assurance/README.md` says of its `file:line` column that "a
    citation that points at the wrong line is the same species of rot the
    rest of this page is about". A section link is that species exactly,
    and it had already happened: `docs/eval.md` renamed its status
    heading to *Status: disabled, and no green campaign yet*, WO-C2
    updated the two links inside `docs/eval.md` itself, and the two in
    `docs/demo.md` were left pointing at `#status-no-green-campaign-yet`
    — an anchor no document has minted since the rename. GitHub does not
    error on a dead anchor. It silently drops the reader at the top of
    the page, so the failure is invisible to everybody except the reader,
    who cannot tell a broken link from a badly written section.

    `tests/test_assurance_docs.py` already holds the assurance pack's
    *paths* to resolving. This is the other half of a link, over the
    top-level documents that carry claims: the file has to exist **and**
    the fragment has to name a heading in it.

    Deliberately not repository-wide. `docs/revamp/` and
    `planning/` are campaign archives — they cite headings in documents
    that have since been rewritten, on purpose, because an archive that
    is edited to keep up with the tree stops being an archive. The
    documents here are the live ones a reader is pointed at.
    """

    def _links(self) -> list[tuple[pathlib.Path, str, str]]:
        """Every `](target#anchor)` in the live documents.

        `target` is empty for a link into the citing document itself,
        which is why the resolution below is written against
        `path.parent / target` rather than against `target` alone.
        """
        paths = [_ROOT / "README.md", *sorted((_ROOT / "docs").glob("*.md"))]
        links = []
        for path in paths:
            for match in re.finditer(
                r"\]\(([^)\s]*?)#([\w-]+)\)", path.read_text(encoding="utf-8")
            ):
                links.append((path, match.group(1), match.group(2)))
        return links

    def test_the_documents_link_to_each_other_at_all(self) -> None:
        """The guard on the two checks below, which are vacuous with no links."""
        links = self._links()
        assert len(links) > 20, (
            f"only {len(links)} section links found across README.md and "
            "docs/*.md. The checks below assert that every one of them "
            "resolves, so a pattern that has stopped matching would make them "
            "pass over nothing."
        )

    def test_every_section_link_names_a_file_that_exists(self) -> None:
        missing = sorted(
            {
                f"{path.relative_to(_ROOT)} -> {target}#{anchor}"
                for path, target, anchor in self._links()
                if target and not (path.parent / target).resolve().is_file()
            }
        )
        assert not missing, f"section links whose file is not in the tree: {missing}"

    def test_every_section_link_lands_on_a_heading(self) -> None:
        dead = sorted(
            {
                f"{path.relative_to(_ROOT)} -> {target or path.name}#{anchor}"
                for path, target, anchor in self._links()
                if (path.parent / target).resolve().is_file()
                if anchor not in _heading_slugs((path.parent / target).resolve())
            }
        )
        assert not dead, (
            f"these section links point at anchors no heading mints: {dead}. "
            "GitHub does not error on a dead fragment — it drops the reader at "
            "the top of the page — so this rot is invisible to everyone except "
            "the reader. Rename the heading back, or fix the link; if the "
            "section genuinely went away, the sentence that cites it needs to "
            "change too."
        )
