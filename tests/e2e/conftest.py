"""The e2e tier's shared harness.

Everything here exists to make one claim checkable: a run of this
repository's graphs, end to end, produces the trajectory we say it
produces and costs exactly nothing.

Three things are worth reading before writing a test in this directory.

**Mock mode is not an LLM stub.** `USE_MOCK_DATA` swaps the arXiv search
for five fixture papers (`src/agents/search.py`) and makes the tutor and
the assessment judge deterministic (`src/agents/tutor.py`,
`src/agents/assessment.py`). It does *not* touch `src/llm.py`, and the
research graph's planner, reader, synthesizer and critic call
`call_llm_json` under it exactly as they do in production. So the
session graph runs free on mock mode alone — which is what
`src/eval/simulate_learner.py` relies on — while the research graph
needs its four agents canned as well. `research_llm_surface` does that,
and `docs/testing.md` says so in the tier's section rather than leaving
the asymmetry to be rediscovered.

**Settings are read per module, not per process.** `src/config.py`
builds one `settings` singleton and every module binds its own name to
it at import. Overriding it means rebinding it on each module on the
path; a module left out keeps the shipped default, which is a silent
behaviour split rather than an error. `install_settings` takes the list
so the list is written once.

**The environment cannot carry the override in.** `tests/conftest.py`
scrubs every variable `Settings` reads and rebuilds the singleton before
collection, so `USE_MOCK_DATA=true` in the shell — including the pin the
`test-e2e` target sets — never reaches a test. That pin is a statement
of intent and a second belt on the API key, not the mechanism; the
mechanism is `install_settings` below.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings, settings
from src.observability.costs import RunCosts, start_cost_tracking

#: Checked-in inputs for this tier. Canned agent output and one session
#: script — not recorded cassettes; see the files' own `_readme` keys.
E2E_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "e2e"

#: Modules that bind `src.config.settings` and sit on a path this tier
#: drives. The union, not the per-test minimum: over-patching a module a
#: given test never reaches is free, while under-patching one produces a
#: run that is half overridden and half shipped-default, which is the
#: failure mode `tests/test_guided_session_graph.py` documents (leaving
#: `src.learning.memory` out of its list opened a live TLS connection on
#: every run).
SETTINGS_CONSUMERS: tuple[str, ...] = (
    "src.agents.assessment",
    "src.agents.critic",
    "src.agents.planner",
    "src.agents.reader",
    "src.agents.search",
    "src.agents.synthesizer",
    "src.agents.tutor",
    "src.api.app",
    "src.api.routes",
    "src.api.runner",
    "src.graph.workflow",
    "src.learning.memory",
)

#: Overrides every e2e test wants regardless of which graph it drives.
#: `use_mock_data` for the offline fixtures; tracing off so no exporter
#: is constructed; Semantic Scholar off because it is a second network
#: edge with nothing to say about the graph's wiring.
BASE_OVERRIDES: dict[str, Any] = {
    "use_mock_data": True,
    "enable_tracing": False,
    "enable_semantic_scholar": False,
}


@pytest.fixture
def e2e_fixtures() -> Callable[[str], dict[str, Any]]:
    """Load a JSON fixture from `tests/fixtures/e2e/` by file stem."""

    def _load(stem: str) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(
            (E2E_FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8")
        )
        return payload

    return _load


@pytest.fixture
def install_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., Settings]:
    """Rebind a modified `settings` across every module on the path.

    Returns the callable so a test can name only what it changes; the
    shipped default stands for everything else, which is the property
    that makes these tests fail when a default moves out from under
    them rather than silently pinning a stale one.
    """

    def _install(
        *, modules: Sequence[str] = SETTINGS_CONSUMERS, **overrides: Any
    ) -> Settings:
        merged = {**BASE_OVERRIDES, **overrides}
        patched = settings.model_copy(update=merged)
        assert isinstance(patched, Settings)
        for module in modules:
            monkeypatch.setattr(f"{module}.settings", patched)
        return patched

    return _install


@pytest.fixture
def research_llm_surface(
    monkeypatch: pytest.MonkeyPatch, e2e_fixtures: Callable[[str], dict[str, Any]]
) -> Callable[..., None]:
    """Can the research graph's four model calls and its two network edges.

    `call_llm_json` is imported into each agent's own namespace, so the
    patch lands per module — patching `src.llm.call_llm_json` would do
    nothing. With it in place `src.observability.costs.record_llm_call`
    is never reached, which is why the accumulator can be asserted at
    exactly zero rather than approximately.

    `critic` takes a *sequence* of responses so a test can script the
    revision loop: the Nth critic pass gets the Nth entry, and the last
    entry repeats once the script runs out. That is what lets one test
    assert the loop is bounded without reaching into `route_after_critique`.
    """
    responses = e2e_fixtures("research_llm_responses")

    def _install(*, critic: Sequence[dict[str, Any]] | None = None) -> None:
        critic_script = list(critic or [responses["critic_approves"]])

        def _fixed(payload: dict[str, Any]) -> Callable[..., dict[str, Any]]:
            def _call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                return dict(payload)

            return _call

        calls = {"critic": 0}

        def _critic(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            index = min(calls["critic"], len(critic_script) - 1)
            calls["critic"] += 1
            return dict(critic_script[index])

        monkeypatch.setattr(
            "src.agents.planner.call_llm_json", _fixed(responses["planner"])
        )
        monkeypatch.setattr(
            "src.agents.reader.call_llm_json", _fixed(responses["reader"])
        )
        monkeypatch.setattr(
            "src.agents.synthesizer.call_llm_json", _fixed(responses["synthesizer"])
        )
        monkeypatch.setattr("src.agents.critic.call_llm_json", _critic)
        # Abstract fallback (ADR 0004): no PDF fetch, so no chunking and
        # no chunk-ranking model load.
        monkeypatch.setattr("src.agents.reader.parse_pdf", lambda url: "")
        # Identity ranking: the five mock papers already fit under
        # `max_papers`, but pinning it keeps the tier independent of
        # whether a MiniLM checkpoint happens to be cached on the host.
        monkeypatch.setattr(
            "src.agents.search.rank_papers_by_relevance",
            lambda query, papers, top_k: list(papers)[:top_k],
        )

    return _install


@pytest.fixture(autouse=True)
def zero_spend_ledger() -> Iterator[RunCosts]:
    """Bind a cost accumulator to the test and prove it never moved.

    Autouse because WO-A15 makes the zero-cost assertion a deliverable
    rather than a habit: a test added to this directory gets the check
    whether or not its author remembers to write one.

    Two numbers, because they fail differently. A dollar total can round
    to zero from spend that really happened; a call count cannot. This is
    the pair `src/eval/scripted_tier_check.py` settled on for the same
    reason, and the tier reuses it rather than inventing a second answer.

    Scope is worth being exact about. The accumulator is a `ContextVar`,
    so this sees every call the *test's own* context makes — the two
    graph-level tests drive the graph inline, so for them this is the
    whole run. `run_job` binds its own accumulator per job, so an HTTP
    test's spend lands on the job row instead and is asserted there, on
    `cost_usd` and `llm_calls`. This fixture is then the backstop that
    catches spend by the test around the job rather than the proof about
    the job, and the HTTP tests say which is which at the assertion.
    """
    costs = start_cost_tracking()
    yield costs
    assert costs.total_cost_usd == 0.0, (
        f"e2e test spent ${costs.total_cost_usd:.4f} in its own context; "
        "the tier is zero-spend by construction"
    )
    assert costs.call_count == 0, (
        f"e2e test made {costs.call_count} model call(s); a dollar total "
        "can round to zero, a call count cannot"
    )


@pytest.fixture
def usd() -> Callable[[float | None], str]:
    """Render a cost the way every report in this repository renders it.

    Tests assert against `"$0.0000"` rather than against `0.0` so the
    string a user is shown is the thing under test — `job.cost_usd` is
    formatted at this precision in all three exporters and in the eval
    summaries, and a bare float comparison would pass a value that
    prints as a non-zero figure.

    A fixture rather than an importable helper: the root `conftest.py`
    already notes that importing from a conftest rests on a sys.path
    entry pytest happens to insert, and a tier whose whole job is to be
    trustworthy should not rest on that.
    """

    def _format(amount: float | None) -> str:
        return f"${(amount or 0.0):.4f}"

    return _format
