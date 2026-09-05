"""Makefile + demo-doc contracts (ADR 0052).

Three findings that live in files no Python test could otherwise
regress:

- **The test targets pin native thread counts.** Three vendored copies
  of `libomp.dylib` (torch, faiss, scikit-learn) plus torch's
  one-OpenMP-thread-per-core default means concurrent MiniLM encodes
  abort the interpreter in the OpenMP barrier. The real containment is
  `torch.set_num_threads(1)` in `src/tools/embeddings.py` — guarded by
  `test_embedding_device.py`, and the only one that covers a bare
  `pytest` or `uvicorn` — but the Makefile prefix catches faiss's and
  scikit-learn's copies at import time, so it has to stay put.
- **`make clean` deleted `.cache/checkpoints.sqlite`** — LangGraph's
  durable graph state, including any run paused at the HITL
  breakpoint. That is job state, not a cache, and a target named
  "clean" must not destroy it.
- **`docs/demo.md`'s account of what a mock run touches**, which has now
  been wrong in *both* directions and is the reason this class of check
  exists at all. ADR 0052 wrote the first version: the page claimed the
  mock-data run made no external calls beyond Anthropic, and it did make
  them — `MOCK_PAPERS` carries real `pdf_url`s and the reader fetched all
  five on a cold cache. This module then pinned that correction with
  `assert "five real PDF downloads" in _DEMO`. **ADR 0080 made the
  correction false and left the assertion holding it in place**: the
  reader's mock branch returns before `_gather_ranked_chunks`, the only
  caller of `parse_pdf`, so a mock run now fetches nothing. Measured
  under tripwires on `socket.connect`, `anthropic.Anthropic`,
  `src.llm._get_client`, `src.llm.call_llm` and `reader.parse_pdf`: a
  full run produced five analyses, 19 evidence claims and a briefing, and
  hit none of them. **A test can pin a sentence to a world that has
  moved.** What `TestDemoDocHonesty` asserts below is therefore the
  *shape* of the disclosure — that the page names the hosts and says
  which are contacted — plus the one claim that is re-derived from code
  rather than from prose: that the reader's mock branch precedes the
  fetch.

These are text assertions on purpose. Running `make clean` for real
would delete the developer's venv.

Mutation-checked: restoring `rm -rf .cache` under `clean` fails
`test_clean_keeps_the_graph_checkpoints`, dropping `$(TEST_ENV)` from a
test target fails `test_every_test_target_pins_native_threads`, and
moving the reader's `use_mock_data` branch below
`_gather_ranked_chunks` fails
`test_the_reader_mock_branch_precedes_the_pdf_fetch` — which is the leg
that would have caught ADR 0080 falsifying this page.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAKEFILE = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
_DEMO = (_REPO_ROOT / "docs" / "demo.md").read_text(encoding="utf-8")
_READER = (_REPO_ROOT / "src" / "agents" / "reader.py").read_text(encoding="utf-8")

#: The path `clean` must not touch — graph state, not a cache.
CHECKPOINT_PATH = ".cache/checkpoints.sqlite"


#: Every function in `src/agents/reader.py` that reaches `parse_pdf` by
#: calling `_gather_ranked_chunks`, mapped to whether it is on the
#: agent's own path. `_analyze_paper` is the per-paper fan-out the demo
#: page's claim is about. `_gather_context` is the pre-evidence-store
#: prompt builder, and it has no caller in `src/` — only
#: `tests/test_reader.py` — which `test_the_other_pdf_caller_is_not_on_a_path`
#: keeps true, because an unguarded second caller would put the fetch
#: back without touching the guarded one.
_READER_PDF_CALLERS: tuple[str, ...] = ("_analyze_paper", "_gather_context")


def _reader_fetch_order(function: str) -> tuple[int | None, int]:
    """Where the mock branch and the PDF path sit inside one function.

    A string search over the module answers the wrong question: the
    first occurrence of `_gather_ranked_chunks` is its own `def`, which
    sits above the branch, so a naive `find` reports the order
    backwards. And two functions call it. The claim is about one
    function's control flow, so it is read off that function's AST.

    Returns `(branch line or None, fetch line)`.
    """
    tree = ast.parse(_READER)
    node = next(
        (
            item
            for item in ast.walk(tree)
            if isinstance(item, ast.FunctionDef) and item.name == function
        ),
        None,
    )
    assert node is not None, (
        f"src/agents/reader.py no longer defines `{function}`. This check "
        "reads the PDF path off that function; a rename means re-reading "
        "the claim in docs/demo.md, not just renaming it here."
    )
    fetch = next(
        (
            child.lineno
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_gather_ranked_chunks"
        ),
        None,
    )
    assert fetch is not None, (
        f"src/agents/reader.py::{function} no longer calls "
        "`_gather_ranked_chunks`; this check reads the PDF path off that "
        "call site and cannot find it."
    )
    branch = next(
        (
            child.lineno
            for child in ast.walk(node)
            if isinstance(child, ast.If)
            and isinstance(child.test, ast.Attribute)
            and child.test.attr == "use_mock_data"
        ),
        None,
    )
    return branch, fetch


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
        """ADR 0052's original finding, kept.

        The page must not go back to asserting the *conclusion* without
        the enumeration below it. "No external API calls beyond
        Anthropic" was the sentence ADR 0052 removed, and it is wrong
        again today for the opposite reason — Anthropic is not contacted
        either.
        """
        assert "no external API calls beyond" not in _DEMO

    def test_every_host_is_named_and_answered(self) -> None:
        """The disclosure's shape, not one sentence of its wording.

        The predecessor of this check asserted the literal string
        `five real PDF downloads`, which ADR 0080 made false while the
        assertion went on holding it in the page. So what is pinned now
        is that all three hosts the run could reach are still named, and
        that the section says for each whether it is contacted — a
        claim that survives the answer changing, which is precisely
        what the old one did not.
        """
        for host in ("export.arxiv.org", "arxiv.org", "api.anthropic.com"):
            assert host in _DEMO, (
                f"docs/demo.md no longer names {host}. The page's job is to "
                "account for every host a run could reach; dropping one is "
                "how it stops being an account."
            )
        assert "Not contacted" in _DEMO, (
            "docs/demo.md names the hosts but no longer says which are "
            "contacted. The table is the disclosure."
        )

    def test_the_reader_mock_branch_precedes_the_pdf_fetch(self) -> None:
        """The one claim on that page re-derived from code, not prose.

        `docs/demo.md` says a mock run fetches no PDF. That is true only
        while the reader's `use_mock_data` branch returns *before*
        `_gather_ranked_chunks`, which is the only caller of
        `parse_pdf`. Reordering those two would silently make the page
        false again — which is exactly the failure this module has now
        seen twice — so the order is asserted rather than described.
        """
        branch, fetch = _reader_fetch_order("_analyze_paper")
        assert branch is not None, (
            "src/agents/reader.py::_analyze_paper calls "
            "`_gather_ranked_chunks` — the PDF path — with no "
            "`settings.use_mock_data` branch above it. docs/demo.md's whole "
            "offline claim rests on that branch (ADR 0080)."
        )
        assert branch < fetch, (
            "src/agents/reader.py::_analyze_paper's `use_mock_data` branch "
            f"is at line {branch}, AFTER the `_gather_ranked_chunks` call at "
            f"line {fetch} that reaches `parse_pdf`. A mock run would fetch "
            "five PDFs again and docs/demo.md's offline claim would be "
            "false. ADR 0052 documented that world; ADR 0080 ended it. Move "
            "the branch back or rewrite the page."
        )

    def test_the_other_pdf_caller_is_not_on_a_path(self) -> None:
        """The guarded caller is not the only way to reach `parse_pdf`.

        `_gather_context` calls `_gather_ranked_chunks` too and has no
        mock branch. It is safe only because nothing in `src/` calls it
        — it predates the evidence store and survives for
        `tests/test_reader.py`. Wiring it back onto the agent's path
        would restore the five downloads while leaving `_analyze_paper`'s
        branch untouched, so the check above would stay green while the
        page went false. That is the shape of defect this module keeps
        finding, so the second door is watched too.
        """
        _, fetch = _reader_fetch_order("_gather_context")
        assert fetch, "unreachable: _reader_fetch_order asserts this"
        callers = [
            path
            for path in (_REPO_ROOT / "src").rglob("*.py")
            if "_gather_context(" in path.read_text(encoding="utf-8")
            and path.name != "reader.py"
        ]
        assert not callers, (
            "`_gather_context` now has a caller in src/ "
            f"({[str(p.relative_to(_REPO_ROOT)) for p in callers]}), and it "
            "reaches `parse_pdf` with no `use_mock_data` branch. Either "
            "guard it the way `_analyze_paper` is guarded, or docs/demo.md's "
            "'not contacted' row for arxiv.org is no longer true."
        )

    def test_the_pdf_cache_is_still_explained_for_live_runs(self) -> None:
        """The cache did not stop existing; it stopped being on this path.

        `.cache/pdfs` and the absent `--no-pdf` switch are still real
        properties of a **live** run, and the page still has to explain
        them — the ADR 0052 finding was never that the cache was
        fictional, only that mock mode did not avoid it.
        """
        assert ".cache/pdfs" in _DEMO
        assert "no `--no-pdf` switch" in _DEMO
