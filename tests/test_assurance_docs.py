"""The assurance pack's cross-references have to resolve.

A crosswalk full of dead paths is worse than no crosswalk: it reads as evidence
and is not. `docs/assurance/` cites over three hundred artifacts across the
framework mapping, the data-provenance record, the system card and the claim →
enforcement index, and every one of them is a path somebody could rename in an
unrelated PR. This module is what goes red when they do.

It also pins three properties the work order treats as acceptance criteria
rather than as nice-to-haves, because each is the kind of thing that quietly
degrades into decoration:

* the mapping's **out-of-reach** column is non-empty (NIST AI 600-1 MS-1.1-009
  sanctions recording risks that cannot be measured quantitatively — so an
  empty column is a mapping nobody checked, not a clean bill of health);
* the claim index still lists claims that **nothing enforces**, and claims that
  are **false**, rather than having been tidied into all-green;
* no `@@SHA@@` placeholder survived the commit that filled them in.

Scope, stated so the guarantee is not read for more than it is: this checks
that cited paths *exist*, not that the artifact at the path says what the row
claims it says. Only a human review does that.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSURANCE = REPO_ROOT / "docs" / "assurance"
GATE_A3 = REPO_ROOT / "planning" / "08-assurance" / "evidence" / "gate-a3"

#: Pages whose links and backticked paths are checked.
PAGES = sorted(ASSURANCE.glob("*.md")) + [GATE_A3 / "README.md"]

#: A backticked token that looks like a repository path: at least one `/`, and
#: an extension of two to four lowercase letters. Deliberately narrow — the
#: pages are full of things that superficially resemble paths and are not
#: (`research-benchmark@20:1d15ae81`, `arxiv:1706.03762`, `learn.session.*`),
#: and a checker that guesses produces false failures nobody trusts.
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_PATHLIKE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]*\.[a-z]{2,4}$")
_DIRLIKE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*/[A-Za-z0-9_.-][A-Za-z0-9_./-]*/$")
_LINE_SUFFIX = re.compile(r":(\d+)(?:[,-](\d+))?$")
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

#: Root-level files have no `/` to identify them by, so they are allowlisted
#: rather than guessed at. A token without a `/` that is not on this list is
#: skipped, which is the conservative direction: a missed check, never a
#: spurious failure.
ROOT_FILES = frozenset(
    {
        "pyproject.toml",
        "Makefile",
        "README.md",
        "docker-compose.yml",
        "requirements-lock.txt",
        "requirements-runtime-lock.txt",
    }
)


def _strip_decorations(token: str) -> str:
    """Drop a `::test_name` selector and a `#fragment` from a cited path."""
    token = token.split("::", 1)[0]
    return token.split("#", 1)[0]


def _cited_paths(page: Path) -> list[tuple[str, Path, int | None]]:
    """Every repository path a page cites, as (as-written, resolved, line-no)."""
    text = page.read_text(encoding="utf-8")
    found: list[tuple[str, Path, int | None]] = []

    # Link targets are resolved relative to the page; bare backticked paths are
    # resolved relative to the repository root. A markdown link whose *label* is
    # also a backticked path would otherwise be measured against the wrong base
    # and fail spuriously, so links are consumed first and their labels with
    # them — the target is checked below either way.
    for raw in _BACKTICKED.findall(_MD_LINK.sub(" ", text)):
        token = _strip_decorations(raw.strip())
        if not token:
            continue
        line_no: int | None = None
        match = _LINE_SUFFIX.search(token)
        if match is not None:
            # A range cites its last line; that is the one that has to exist.
            line_no = int(match.group(2) or match.group(1))
            token = token[: match.start()]
        if _DIRLIKE.match(token):
            found.append((raw, REPO_ROOT / token.rstrip("/"), None))
        elif _PATHLIKE.match(token) or token in ROOT_FILES:
            found.append((raw, REPO_ROOT / token, line_no))

    for target in _MD_LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        found.append((target, (page.parent / _strip_decorations(target)).resolve(), None))

    return found


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
class TestEveryCitedArtifactResolves:
    def test_the_page_exists_and_cites_something(self, page: Path) -> None:
        assert page.is_file(), f"{page} is missing"
        assert _cited_paths(page), f"{page.name} cites no repository paths at all"

    def test_every_cited_path_resolves(self, page: Path) -> None:
        missing = [
            f"{written!r} -> {resolved.relative_to(REPO_ROOT)}"
            for written, resolved, _ in _cited_paths(page)
            if not resolved.exists()
        ]
        assert not missing, (
            f"{page.name} cites paths that do not exist:\n  " + "\n  ".join(missing)
        )

    def test_every_cited_line_number_is_inside_its_file(self, page: Path) -> None:
        """A `file.py:900` citation against a 400-line file is a stale row.

        Cheaper than it looks and worth doing: line citations are the first
        thing to rot when a file is edited, and a row pointing past the end of
        its own artifact is provably wrong rather than merely suspicious.
        """
        overruns = []
        for written, resolved, line_no in _cited_paths(page):
            if line_no is None or not resolved.is_file():
                continue
            length = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
            if line_no > length:
                overruns.append(f"{written!r} cites line {line_no}; the file has {length}")
        assert not overruns, f"{page.name} cites lines past end of file:\n  " + "\n  ".join(
            overruns
        )

    def test_no_sha_placeholder_survived(self, page: Path) -> None:
        text = page.read_text(encoding="utf-8")
        assert "@@SHA" not in text, (
            f"{page.name} still carries an unfilled @@SHA@@ placeholder — the "
            "'reviewed at' commit is what makes a row checkable"
        )


class TestTheHonestColumnsStayNonEmpty:
    """The gaps are the deliverable. A green mapping would mean nobody looked."""

    def test_the_mapping_records_something_out_of_reach(self) -> None:
        text = (ASSURANCE / "framework-mapping.md").read_text(encoding="utf-8")
        # Once for the legend, then at least one real row.
        assert text.count("**Out-of-reach**") >= 2, (
            "the framework mapping has no out-of-reach rows; NIST MS-1.1-009 "
            "exists precisely so unmeasurable risk is recorded rather than omitted"
        )

    def test_the_mapping_carries_the_risks_it_cannot_measure(self) -> None:
        text = (ASSURANCE / "framework-mapping.md").read_text(encoding="utf-8")
        assert "## 6. What is out of reach, and why" in text

    def test_the_claim_index_still_lists_unenforced_claims(self) -> None:
        text = (ASSURANCE / "README.md").read_text(encoding="utf-8")
        assert "Not enforced" in text, (
            "the claim index lists no unenforced claim; either every claim in "
            "this repository is now gated, or the honest list was tidied away"
        )

    def test_the_claim_index_still_names_the_claims_that_are_false(self) -> None:
        text = (ASSURANCE / "README.md").read_text(encoding="utf-8")
        assert "| **False** |" in text

    def test_the_system_card_says_judge_calibration_is_unmeasured(self) -> None:
        """The single statement the work order requires to be explicit."""
        text = (ASSURANCE / "system-card.md").read_text(encoding="utf-8").lower()
        assert "judge–human calibration is unmeasured" in text


class TestTheEvidencePackIsSelfDescribing:
    def test_the_sbom_is_committed_and_is_cyclonedx(self) -> None:
        import json

        sbom = json.loads((GATE_A3 / "sbom.cyclonedx.json").read_text(encoding="utf-8"))
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["components"], "an SBOM with no components is not an SBOM"
        # The date is the point: `02-STANDARDS.md` §4.4 wants a dated artifact,
        # and this one dates itself rather than relying on a filename.
        assert sbom["metadata"]["timestamp"]

    def test_the_raw_captures_the_summary_reads_are_all_present(self) -> None:
        raw = GATE_A3 / "raw"
        required = {
            "provenance.txt",
            "pytest-not-e2e.txt",
            "pytest-e2e.txt",
            "pytest-property.txt",
            "pytest-fault.txt",
            "pytest-security.txt",
            "pytest-contract.txt",
            "coverage-total.txt",
            "mypy.txt",
            "ruff.txt",
            "safety-suite.txt",
            "scripted-tier-check.txt",
            "pip-audit.txt",
        }
        missing = sorted(name for name in required if not (raw / name).is_file())
        assert not missing, f"the pack's summary reads raw captures that are absent: {missing}"

    def test_the_system_card_quotes_the_pack_rather_than_remembered_numbers(self) -> None:
        """The card's figures must be the runner's, verbatim.

        This is where a hand-typed number does the most damage: a system card
        is read as measurement. So the card's tier tallies and its coverage
        figure are checked against `raw/`, and a suite that grows without the
        card being regenerated goes red instead of quietly misreporting itself.

        Deliberately excluded: the `-m "not e2e"` tally itself. This test runs
        *inside* that selection, so its own pass or fail moves the number it
        would be comparing — a check that can never converge is not a check.
        The tiers below are all deselected when this module runs, so their
        counts are stable, and coverage is unaffected because nothing here
        executes `src/`.
        """
        card = (ASSURANCE / "system-card.md").read_text(encoding="utf-8")
        mismatches = []
        for tier in ("e2e", "property", "fault", "security", "contract"):
            raw = (GATE_A3 / "raw" / f"pytest-{tier}.txt").read_text(encoding="utf-8")
            tally = re.search(r"(\d+ passed(?:, \d+ skipped)?)", raw)
            assert tally is not None, f"no pytest tally in raw/pytest-{tier}.txt"
            if tally.group(1) not in card:
                mismatches.append(f"-m {tier}: raw says {tally.group(1)!r}")

        coverage = re.search(
            r"Total coverage: ([\d.]+)%",
            (GATE_A3 / "raw" / "pytest-not-e2e.txt").read_text(encoding="utf-8"),
        )
        assert coverage is not None, "no coverage total in the raw capture"
        if f"{coverage.group(1)}%" not in card:
            mismatches.append(f"coverage: raw says {coverage.group(1)}%")

        assert not mismatches, (
            "the system card disagrees with the evidence pack:\n  "
            + "\n  ".join(mismatches)
            + "\nRe-run collect.sh and update the card from raw/, never from memory."
        )

    def test_the_pack_records_the_commit_it_describes(self) -> None:
        provenance = (GATE_A3 / "raw" / "provenance.txt").read_text(encoding="utf-8")
        assert re.search(r"^commit=[0-9a-f]{40}$", provenance, re.MULTILINE), (
            "the evidence pack does not name the commit it measured, which "
            "makes every number in it unverifiable"
        )
