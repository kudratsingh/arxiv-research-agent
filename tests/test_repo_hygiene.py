"""Makefile + demo-doc contracts (ADR 0052).

Three findings that live in files no Python test could otherwise
regress:

- **`make test` popped macOS crash dialogs.** Three vendored copies of
  `libomp.dylib` (torch, faiss, scikit-learn) plus torch's
  one-OpenMP-thread-per-core default means a parallel pytest fleet
  tears down duplicate OpenMP runtimes concurrently, and that race has
  aborted the interpreter natively. The test targets pin the thread
  counts.
- **`make clean` deleted `.cache/checkpoints.sqlite`** — LangGraph's
  durable graph state, including any run paused at the HITL
  breakpoint. That is job state, not a cache, and a target named
  "clean" must not destroy it.
- **`docs/demo.md` claimed the mock-data run made no external calls
  beyond Anthropic.** It downloads five real arXiv PDFs on a cold
  cache: `MOCK_PAPERS` carries real `pdf_url`s.

These are text assertions on purpose. Running `make clean` for real
would delete the developer's venv.

Mutation-checked: restoring `rm -rf .cache` under `clean` fails
`test_clean_keeps_the_graph_checkpoints`, and dropping `$(TEST_ENV)`
from a test target fails `test_every_test_target_pins_native_threads`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAKEFILE = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
_DEMO = (_REPO_ROOT / "docs" / "demo.md").read_text(encoding="utf-8")

#: The path `clean` must not touch — graph state, not a cache.
CHECKPOINT_PATH = ".cache/checkpoints.sqlite"


def _recipe(target: str) -> str:
    """Return the tab-indented recipe body for `target`."""
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)",
        _MAKEFILE,
        re.MULTILINE,
    )
    assert match is not None, f"no recipe found for target {target!r}"
    return match.group(1)


class TestMakefileThreadHygiene:
    @pytest.mark.parametrize(
        "target", ["test-unit", "test-integration", "test-e2e", "test-all"]
    )
    def test_every_test_target_pins_native_threads(self, target: str) -> None:
        assert "$(TEST_ENV)" in _recipe(target)

    def test_test_env_pins_both_offenders(self) -> None:
        assert "OMP_NUM_THREADS=1" in _MAKEFILE
        assert "TOKENIZERS_PARALLELISM=false" in _MAKEFILE
        # The why has to travel with the value: a bare `OMP_NUM_THREADS=1`
        # reads as a performance tweak someone will helpfully remove.
        assert "ADR 0052" in _MAKEFILE


class TestCleanTargets:
    def test_clean_keeps_the_graph_checkpoints(self) -> None:
        recipe = _recipe("clean")
        assert ".cache/pdfs" in recipe
        assert CHECKPOINT_PATH not in recipe
        # The bare directory would take the checkpoint with it.
        assert not re.search(r"rm -rf[^\n]*\s\.cache(\s|$)", recipe)

    def test_clean_all_is_the_target_that_removes_them(self) -> None:
        assert re.search(r"rm -rf[^\n]*\s?\.cache(\s|$)", _recipe("clean-all"))
        assert "clean-all: clean" in _MAKEFILE

    def test_both_targets_are_phony(self) -> None:
        phony = _MAKEFILE.splitlines()[0]
        assert " clean " in phony
        assert " clean-all " in phony

    def test_help_text_names_the_difference(self) -> None:
        """An operator picks a target from `make help`, not from the
        recipe — the distinction has to be visible there."""
        help_recipe = _recipe("help")
        assert "checkpoints.sqlite" in help_recipe
        assert "clean-all" in help_recipe
        assert "unresumable" in help_recipe


class TestDemoDocHonesty:
    def test_the_no_external_calls_claim_is_gone(self) -> None:
        assert "no external API calls beyond" not in _DEMO

    def test_the_pdf_downloads_are_disclosed(self) -> None:
        assert "arxiv.org" in _DEMO
        assert "five real PDF downloads" in _DEMO

    def test_the_warm_cache_path_is_documented(self) -> None:
        """There is no `--no-pdf` switch to offer, so the honest
        offline recipe is the second run against a warm
        `.cache/pdfs`."""
        assert ".cache/pdfs" in _DEMO
        assert "no `--no-pdf` switch" in _DEMO
