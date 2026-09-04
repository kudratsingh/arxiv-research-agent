"""Run provenance for the eval harness — ADR 0070.

A score is only worth a confidence interval if it is attributable. Before
this module, no `summary.jsonl` row recorded which model judged it, which
rubric text produced the verdict, or which commit of the harness ran it,
so a regression diff could not tell a quality change from a configuration
change. Every campaign row now carries one nested `provenance` block that
answers those questions.

Three pieces, in the order they matter:

- **A pinned judge.** `judge_model()` reads `settings.eval_judge_model`,
  which is a model id in its own right rather than a fallback to
  `settings.anthropic_model`. Upgrading the product model therefore no
  longer moves the ruler the product is measured with.
- **Versioned rubrics.** A `Rubric` binds a judge prompt to a version
  string. `tests/test_eval_rubric_versions.py` locks each rubric's text
  by digest, so a prompt edit that does not bump the version fails a
  test rather than silently rebaselining a metric.
- **A captured block.** `capture()` snapshots the judge model, the
  product model, the rubric versions, the code commit (and whether the
  tree was dirty), the dataset fingerprint, the tier, the harness seed
  and whether mock data was in play.

What this deliberately does *not* claim: the Anthropic Messages API
exposes no sampling seed, so `seed` pins only the harness's own local
randomness. A campaign is not reproducible run-to-run, and recording the
seed says what was pinned rather than pretending the run was
deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, NamedTuple, TypedDict

from src.config import settings

#: Version of the provenance block itself, bumped when the row schema
#: changes shape. It is what lets a later reader know which fields to
#: expect from a row it did not write — the regression differ compares
#: campaigns that may be months apart, and "this row predates the field
#: you are looking for" is a different answer from "this run did not
#: record it". Additive field growth bumps the minor; a rename or a
#: removal (which ADR 0070 forbids) would bump the major.
HARNESS_VERSION: Final[str] = "1.0.0"

#: Repository root, three parents up from `src/eval/provenance.py`. Used
#: as the working directory for the git queries below so a campaign
#: launched from anywhere still describes *this* checkout.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Seconds a git query may take before the campaign gives up on it. A
#: campaign must not hang on a filesystem problem to record its own
#: metadata; an unresolved commit is reported as `"unknown"` instead.
_GIT_TIMEOUT_SEC: Final[float] = 5.0

#: What `code_commit` reports when neither git nor CI can name the
#: revision. Deliberately a value rather than an empty string: a row
#: that says `"unknown"` is telling the truth about what it does not
#: know, and an empty field reads as "nobody implemented this".
UNKNOWN_COMMIT: Final[str] = "unknown"


class Rubric(NamedTuple):
    """One judge prompt, bound to the version that names its text.

    Attributes:
        name: Stable identifier, matching the metric the rubric scores.
        version: Semantic version of the prompt text. Bumping it is the
            act that declares "scores before and after are not
            comparable".
        prompt: The system prompt handed to the judge, verbatim.
    """

    name: str
    version: str
    prompt: str

    @property
    def digest(self) -> str:
        """SHA-256 of the prompt text, hex, full length.

        Full length rather than truncated: this is the value a lock file
        compares against, and there is no display cost to pay for.
        """
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


def rubric_versions(rubrics: Sequence[Rubric]) -> dict[str, str]:
    """Project a rubric set onto the `{name: version}` map a row carries.

    Args:
        rubrics: The rubrics a campaign actually runs — not every rubric
            the harness defines, because a row should not claim a
            version for a judge it never called.

    Returns:
        Names mapped to versions, sorted by name so two rows written by
        the same harness compare byte-for-byte.
    """
    return {rubric.name: rubric.version for rubric in sorted(rubrics)}


def dataset_fingerprint(name: str, items: Sequence[Mapping[str, Any]]) -> str:
    """Content-derived version string for a benchmark dataset.

    Derived rather than declared, because a hand-maintained dataset
    version is a constant somebody forgets to bump — and a benchmark
    whose contents changed under a stable version is the same
    unattributable row this module exists to prevent. The digest moves
    the moment a query's text, topics or provenance changes.

    Args:
        name: Dataset name, e.g. `"research-benchmark"`.
        items: The dataset's records, each JSON-serialisable.

    Returns:
        `"<name>@<count>:<sha256[:12]>"` — readable at a glance in a
        summary table, and exact enough to join two campaigns on.
    """
    payload = json.dumps(
        [dict(item) for item in items], sort_keys=True, default=str, ensure_ascii=False
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{name}@{len(items)}:{digest}"


class CodeRevision(NamedTuple):
    """The checkout a campaign ran from.

    Attributes:
        commit: Full 40-character SHA, or `UNKNOWN_COMMIT`.
        dirty: True when the working tree carried uncommitted changes,
            False when it was clean, and `None` when we could not tell —
            which is the case when the revision came from a CI
            environment variable rather than from git itself. `None` is
            not `False`: "not checked" and "checked and clean" are
            different claims about a result's reproducibility.
    """

    commit: str
    dirty: bool | None


def _git(*args: str) -> str | None:
    """Run one git query in the repo root. `None` on any failure.

    Every failure mode collapses to `None` on purpose: git missing from
    the image, the checkout being a tarball with no `.git`, a hung
    filesystem. None of them is a reason to fail a campaign that has
    already been paid for, and each of them is honestly reported
    downstream as an unknown revision.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


@lru_cache(maxsize=1)
def code_revision() -> CodeRevision:
    """Resolve the commit this campaign is running from.

    Order: git first, because it is the only source that can also answer
    whether the tree is dirty; then `GITHUB_SHA`, which is set in Actions
    and survives a checkout whose `.git` has been pruned; then
    `UNKNOWN_COMMIT`.

    Cached for the process: a campaign's revision cannot change under it,
    and the alternative is two subprocesses per record. Tests that need
    a different answer call `code_revision.cache_clear()`.
    """
    commit = _git("rev-parse", "HEAD")
    if commit:
        status = _git("status", "--porcelain")
        return CodeRevision(commit=commit, dirty=None if status is None else bool(status))
    from_ci = os.environ.get("GITHUB_SHA", "").strip()
    if from_ci:
        return CodeRevision(commit=from_ci, dirty=None)
    return CodeRevision(commit=UNKNOWN_COMMIT, dirty=None)


def judge_model() -> str:
    """The model every LLM-as-judge call must be issued against.

    Read at call time rather than bound at import so a campaign that
    overrides the setting gets the override, and so a test can install a
    different `Settings` on this module and observe the judge follow it.

    This is the whole point of ADR 0070's first deliverable: the judges
    used to pass no model at all, so `src/llm.py` fell through to
    `settings.anthropic_model` and a product-model upgrade silently
    changed the grader.
    """
    return settings.eval_judge_model


def seed_campaign(seed: int | None = None) -> int:
    """Pin the harness's own randomness and return the seed used.

    Bounded honestly: this seeds `random` and, when it is already
    imported, numpy — the two global generators anything under `src/`
    draws from. It does **not** make a campaign reproducible, because
    the Messages API exposes no sampling seed and the judges are
    sampled. Recording the seed says what was pinned; ADR 0070 says
    plainly what it does not buy.

    Args:
        seed: Explicit seed. `None` reads `settings.eval_seed`.

    Returns:
        The seed actually applied, for the provenance block.
    """
    resolved = settings.eval_seed if seed is None else seed
    random.seed(resolved)
    numpy = sys.modules.get("numpy")
    if numpy is not None:  # imported by torch on the embedding paths
        numpy.random.seed(resolved)
    return resolved


class RunProvenance(TypedDict):
    """What produced one summary row.

    Every field answers a question a regression diff has to ask before
    it may treat two rows as comparable. A row missing any of them
    cannot participate in a comparison, which is why
    `scripted_tier_check` asserts their presence.
    """

    harness_version: str
    judge_model: str
    product_model: str
    rubric_versions: dict[str, str]
    code_commit: str
    code_dirty: bool | None
    dataset_version: str
    tier: str
    seed: int
    mock_mode: bool
    captured_at: str


#: Provenance fields that must be present *and* non-empty. `str` fields
#: whose value carries no information (`""`) are as unattributable as a
#: missing key, so the check treats them the same.
PROVENANCE_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "harness_version",
    "judge_model",
    "product_model",
    "code_commit",
    "dataset_version",
    "tier",
    "captured_at",
)

#: Provenance fields that must be present but may legitimately be falsy:
#: seed 0 is a seed, `mock_mode=False` is the answer a funded campaign
#: gives, and `code_dirty=None` means "could not tell" rather than
#: "unset". Presence is the assertion; the value is data.
PROVENANCE_PRESENT_FIELDS: Final[tuple[str, ...]] = (
    "seed",
    "mock_mode",
    "code_dirty",
)

#: The mapping field, checked on its own terms: a non-empty dict whose
#: keys and values are all non-empty strings.
PROVENANCE_MAPPING_FIELD: Final[str] = "rubric_versions"

#: Where the block rides on a summary row. One nested key rather than
#: eleven flat ones: ADR 0070 forbids renaming or removing an existing
#: row field, and a single additive key is also the smallest thing a
#: downstream work order has to be briefed on.
PROVENANCE_KEY: Final[str] = "provenance"


def capture(
    *,
    tier: str,
    dataset_version: str,
    rubrics: Sequence[Rubric],
    seed: int | None = None,
) -> RunProvenance:
    """Snapshot everything that decides whether two rows are comparable.

    Called once per record, at the moment the record is created rather
    than when the summary is rendered: `rebuild_summaries` re-derives
    `summary.jsonl` from the durable per-record JSON, possibly days
    later on a `--resume`, and a block captured at render time would
    describe the rebuild instead of the run.

    Args:
        tier: The campaign tier that produced the row — `"research"` for
            the research lane, `"scripted"` / `"funded"` for the learning
            lane, matching that lane's own `tier` column.
        dataset_version: `dataset_fingerprint()` of the benchmark the
            row was scored against.
        rubrics: The rubrics this campaign actually runs.
        seed: The seed already applied by `seed_campaign()`. `None`
            reads the configured seed without re-seeding, so calling
            `capture` cannot perturb a campaign's randomness.

    Returns:
        A `RunProvenance` ready to be written onto the record.
    """
    revision = code_revision()
    return RunProvenance(
        harness_version=HARNESS_VERSION,
        judge_model=judge_model(),
        product_model=settings.anthropic_model,
        rubric_versions=rubric_versions(rubrics),
        code_commit=revision.commit,
        code_dirty=revision.dirty,
        dataset_version=dataset_version,
        tier=tier,
        seed=settings.eval_seed if seed is None else seed,
        mock_mode=settings.use_mock_data,
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def check_provenance(block: Any) -> list[str]:
    """Return every reason `block` is not a usable provenance block.

    Returns problems rather than raising, and *all* of them rather than
    the first, so one CI log says everything that is wrong with a row.
    An empty list means the row can carry its own attribution.

    Args:
        block: The row's `provenance` value, of whatever type it is —
            a row written by an older harness has none at all.

    Returns:
        Human-readable problems, empty when the block is complete.
    """
    if not isinstance(block, dict):
        return [
            f"provenance is {type(block).__name__}, not an object — the row "
            "cannot say what produced it"
        ]

    problems: list[str] = []
    for field in PROVENANCE_REQUIRED_FIELDS:
        value = block.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"provenance.{field} is {value!r}, expected a non-empty string")
    for field in PROVENANCE_PRESENT_FIELDS:
        if field not in block:
            problems.append(f"provenance.{field} is missing")

    versions = block.get(PROVENANCE_MAPPING_FIELD)
    if not isinstance(versions, dict) or not versions:
        problems.append(
            f"provenance.{PROVENANCE_MAPPING_FIELD} is {versions!r}, expected a "
            "non-empty {name: version} object"
        )
    elif any(
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(version, str)
        or not version.strip()
        for name, version in versions.items()
    ):
        problems.append(
            f"provenance.{PROVENANCE_MAPPING_FIELD} has an empty or non-string "
            "rubric name or version"
        )
    return problems


#: Fields rendered in a campaign summary's provenance table, in order.
#: `rubric_versions` is rendered separately because it is a mapping.
_MARKDOWN_FIELDS: Final[tuple[str, ...]] = (
    "harness_version",
    "judge_model",
    "product_model",
    "code_commit",
    "code_dirty",
    "dataset_version",
    "tier",
    "seed",
    "mock_mode",
)


def provenance_markdown(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Render a campaign's provenance as markdown lines.

    Reads the block off every row rather than off the first, and says so
    when the rows disagree. Disagreement is not hypothetical: `--resume`
    re-enters a campaign that may have been started under a different
    judge model or a different commit, and a summary that quoted only
    the first row would silently present a mixed campaign as a uniform
    one. A mixed campaign is still a legitimate artifact — it just may
    not be averaged as though one instrument produced it.

    Args:
        rows: The campaign's summary rows.

    Returns:
        Markdown lines, or an empty list when no row carries a block.
    """
    blocks = [
        row[PROVENANCE_KEY]
        for row in rows
        if isinstance(row.get(PROVENANCE_KEY), dict) and row[PROVENANCE_KEY]
    ]
    if not blocks:
        return []

    lines = [
        "",
        "## Provenance",
        "",
        "What produced these rows. A score that cannot name its judge, its "
        "rubric versions and its commit cannot be compared against another "
        "run (ADR 0070).",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for field in _MARKDOWN_FIELDS:
        values = sorted({str(block.get(field)) for block in blocks})
        rendered = values[0] if len(values) == 1 else " ⚠ MIXED: " + ", ".join(values)
        lines.append(f"| `{field}` | {rendered} |")

    version_sets = sorted(
        {
            ", ".join(
                f"{name}@{version}"
                for name, version in sorted(dict(block.get("rubric_versions") or {}).items())
            )
            for block in blocks
        }
    )
    rendered_versions = (
        version_sets[0] if len(version_sets) == 1 else " ⚠ MIXED: " + " / ".join(version_sets)
    )
    lines.append(f"| `rubric_versions` | {rendered_versions or '(none)'} |")

    missing = len(rows) - len(blocks)
    if missing:
        lines += [
            "",
            f"**{missing} of {len(rows)} row(s) carry no provenance block** and "
            "cannot be attributed. The usual cause is a resumed campaign whose "
            "earlier records predate ADR 0070.",
        ]
    if any("MIXED" in line for line in lines):
        lines += [
            "",
            "**This campaign was not produced by one configuration.** The rows "
            "above disagree on at least one field, so their aggregate is a mean "
            "over two instruments rather than one measurement.",
        ]
    return lines


__all__ = [
    "HARNESS_VERSION",
    "PROVENANCE_KEY",
    "PROVENANCE_MAPPING_FIELD",
    "PROVENANCE_PRESENT_FIELDS",
    "PROVENANCE_REQUIRED_FIELDS",
    "REPO_ROOT",
    "UNKNOWN_COMMIT",
    "CodeRevision",
    "Rubric",
    "RunProvenance",
    "capture",
    "check_provenance",
    "code_revision",
    "dataset_fingerprint",
    "judge_model",
    "provenance_markdown",
    "rubric_versions",
    "seed_campaign",
]
