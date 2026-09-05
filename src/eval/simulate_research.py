"""Scripted research tier — the research lane's free per-PR gate (ADR 0075).

`src/eval/runner.py` is the research lane's only campaign, and it costs
money: it drives the real workflow against real models and real arXiv,
and the first funded campaign is still gated on an owner decision. So
the lane that publishes this repository's headline numbers has had **no
gate that runs on a pull request at all**, while the learning lane has
had one since WO-W10 and it is the only gate here that has ever caught a
regression.

This module is that gate's research-lane twin. It replays every
`BENCHMARK_QUERIES` entry through the **real compiled research graph** —
the real router, the real state reducers, the real search / reader /
synthesizer / critic nodes — under `USE_MOCK_DATA=true` with the
disabled-key sentinel, writes the same durable per-record layout
`runner.py` writes, and asserts through `src/eval/scripted_tier_check.py`
that the campaign was complete and cost exactly `$0.0000`.

**The asymmetry that makes this module necessary, stated first because
it is the thing a reader must not have to rediscover.** Mock mode is not
an LLM stub. `USE_MOCK_DATA` swaps arXiv search for five fixture papers
(`src/agents/search.py`) and gives the tutor and the assessment judge
deterministic branches (`src/agents/tutor.py`, `src/agents/assessment.py`)
— which is why the *session* graph runs free on mock mode alone and
`simulate_learner`'s scripted tier needs nothing else. It does **not**
touch `src/llm.py`, and the research graph's planner, reader,
synthesizer and critic call `call_llm_json` under it exactly as they do
in production. `tests/e2e/conftest.py` says the same thing in the same
words, and cans the four agents itself.

So the research lane's scripted tier has to supply the words the
*model* would have said, where the learning lane's supplies the words
the *learner* would have said. That is the whole difference, and it is
the honest cost of the tier: **the report text in a scripted record is
the harness's, so this tier measures the pipeline around the model, not
the model's own grounding.** What it therefore does and does not catch
is written out in `docs/eval.md` rather than left implicit.

What it does catch, all of which are real regressions the repository has
no other free check for:

  - **The trajectory.** Every record records the node sequence the graph
    reported, and a run that skipped the reader, looped the synthesizer,
    or routed a revision to a node the router cannot dispatch fails a
    structural expectation. "The report is non-empty" is not a
    trajectory assertion (`tests/e2e/test_research_workflow.py`).
  - **The seams between nodes.** The plan reached search, the papers
    reached the reader, the analyses reached the synthesizer, the
    synthesizer's citations survived `_parse_citations`, the critic's
    verdict landed on the state.
  - **Groundedness, per claim.** Every record scores
    `measure_groundedness` over the report the graph actually assembled
    against the corpus the graph actually retrieved, and emits
    `paired_outcomes()` — the per-claim binary outcome
    `src/eval/stats.py`'s McNemar path has been waiting for a caller to
    hand it (ADR 0074's open follow-up). The identifiers in that report
    are the ones **search returned and the reader analysed**, not a
    fixed list: the scripted synthesizer is fed the graph's own papers
    off the stream, so a search that returns fewer papers, a reader that
    drops one, or a citation parser that rejects an entry moves the
    claim set.
  - **Zero spend, structurally.** Four independent layers, below.

**Zero spend is structural, not hoped for.** Four layers, and each one
alone would be a hope:

  1. **There is no second tier.** `simulate_learner` has a `--tier`
     flag with a funded setting to fall into; this module has neither.
     The funded research campaign is `runner.py` — a different module
     with a different CLI — so no flag on this one can start a paid run.
  2. It refuses to start when `USE_MOCK_DATA` is false, exactly as
     `simulate_learner._config_problem` does, because a scripted tier
     that advertises zero spend while the graph makes live calls is the
     one way to be wrong about money that costs money.
  3. The scripted surface replaces `call_llm_json` in each of the four
     agent modules *and* installs a tripwire on `src.llm.call_llm`
     itself, so any path this module did not anticipate — a new node, a
     judge, a supervisor branch — raises `ScriptedSurfaceBreach` instead
     of reaching Anthropic. A model call cannot happen; it is not that
     one is unlikely. `src.llm._get_client` and `anthropic.Anthropic`
     are on the same tripwire (`_spend_guard`), because the surface now
     also encloses `EpisodeHooks` code this module did not write, and
     the first thing code that means to spend does is build its own
     client rather than go through `call_llm`.
  4. Every row carries `cost_usd`, `judge_cost_usd`, `total_cost_usd`,
     `llm_calls` and `judge_llm_calls`, and
     `src/eval/scripted_tier_check.py --lane research` asserts every one
     of them is zero. A dollar figure can round to zero; a call count
     cannot.

The tier is also **offline**. `parse_pdf` is stubbed to the empty string
so the reader takes ADR 0004's abstract-only path: the mock corpus has
no local full text, and a per-PR gate that fetches five PDFs from
arxiv.org is neither free nor reliable. `quote_verbatim_rate` is
therefore `null` with reason `no_checkable_quotes` on every record, which
is the honest answer and is published as such.

**What the mock corpus does to the denominators**, because a rate over
three citations is not a rate. `search.MOCK_PAPERS` is five papers and
the same five for every query — `rank_papers_by_relevance` short-circuits
at `len(papers) <= top_k`, and `max_papers` is 10 — so a clean campaign
carries five citation claims per query and no quote claims at all. Over
the twenty benchmark queries that is 100 paired claims, and because the
corpus is fixed the *claim ids* repeat across queries: `claim_id` digests
the canonical identifier, so the same paper cited under two queries
carries the same id. The paired comparison therefore namespaces each
claim by its query (`<query_id>/<claim_id>`) — see
`regression_diff.claim_outcomes` — which is the unit a pairing wants
anyway: the same query's assertion about the same paper, scored twice.
Un-namespaced the campaign would collapse to five distinct claims.

**One extension point, `EpisodeHooks`, default `None`.** Other work
needs to watch this campaign happen — the research shadow is the first —
and the alternative to an agreed seam is a second author editing the
driver, which is how a harness ends up with two sets of hooks that fire
in almost the same place. `run_query(..., hooks=...)` is that seam and
the whole of it: an observer sees each episode open, each chunk off the
graph's own stream, and the finished record, on which it may attach a
`contracts` block and nothing else. It runs inside the spend guard, so
it is bound by layer 3 above exactly as a node is. `hooks=None` — the
CLI's setting — installs nothing and calls nothing. See "The episode
seam" below, and `docs/eval.md` for who owns which side of it.

Usage:
    USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \\
        python -m src.eval.simulate_research
    python -m src.eval.simulate_research --queries hallucination-mitigation
    python -m src.eval.simulate_research --output-dir outputs/eval/rs-a --resume

Exit codes are `runner.py`'s, unchanged:
    0 — every attempted query ran
    1 — configuration error
    2 — usage error (non-empty output directory without --resume)
    3 — completed, but at least one query errored
    4 — every attempted query errored
    130 — interrupted; partial results are on disk
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
import sys
import time
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NamedTuple, Protocol, cast

from dotenv import load_dotenv

from src.config import settings
from src.eval.benchmark_queries import (
    BENCHMARK_QUERIES,
    RESEARCH_DATASET_VERSION,
    BenchmarkQuery,
)
from src.eval.groundedness import (
    GroundednessResult,
    measure_groundedness,
    paired_outcomes,
)
from src.eval.metrics import GROUNDEDNESS_CHECK, measure_citation_accuracy
from src.eval.provenance import (
    PROVENANCE_KEY,
    RunProvenance,
    capture,
    provenance_markdown,
    seed_campaign,
)
from src.eval.runner import (
    EXIT_CONFIG,
    EXIT_USAGE,
    CampaignShape,
    EvalInterrupted,
    _benchmark_order,
    _check_output_dir,
    _close_workflow,
    _exit_code,
    _fmt,
    _fmt_cell_text,
    _install_interrupt_handler,
    _mean,
    load_records,
    persist_record,
    rebuild_summaries,
    research_record_id,
)
from src.graph.workflow import build_workflow
from src.observability import bind_run_id, get_logger, reset_run_id, start_cost_tracking

load_dotenv()

log = get_logger(__name__)

DEFAULT_OUTPUT_ROOT = Path("outputs/eval")

#: The one tier this module has. Deliberately distinct from both
#: `runner.RESEARCH_TIER` ("research") and the learning lane's
#: "scripted": `tier` is one of `regression_diff.COMPARABILITY_FIELDS`,
#: so a scripted row meeting a funded one exits 3 rather than diffing a
#: canned report against a real one. `mock_mode` would catch the same
#: thing a second time, which is the point of having both.
RESEARCH_SCRIPTED_TIER: Final[str] = "research-scripted"

#: Where the committed baseline lives, and the only place `make
#: research-baseline` writes. Committed so `regression_diff` has
#: something to pair against on a pull request, which is the whole
#: reason Phase 2 of this work order exists.
BASELINE_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "eval"
    / "research-scripted"
    / "baseline.jsonl"
)

#: How to regenerate the baseline, quoted in the staleness failure so a
#: reader is not sent hunting for it.
BASELINE_REGEN_COMMAND: Final[str] = "make research-scripted-baseline"

#: The pipeline the fixed research graph runs, in order. Spelled out
#: rather than read off the compiled graph, for the reason
#: `tests/e2e/test_research_workflow.py` gives: a trajectory expectation
#: that asks the graph what to expect agrees with any rewiring,
#: including a wrong one.
FIXED_PIPELINE: Final[tuple[str, ...]] = (
    "planner",
    "search",
    "reader",
    "synthesizer",
    "critic",
)

#: LangGraph's sentinel chunk key for a dynamic interrupt. Not a node.
_INTERRUPT_KEY: Final[str] = "__interrupt__"

#: Quality score the scripted critic returns. Above
#: `settings.min_quality_score` (0.75) so the supervisor shape, if it is
#: ever pointed at this tier, also stops — and far enough above it that
#: a default change does not silently turn one pass into three.
SCRIPTED_QUALITY_SCORE: Final[float] = 0.88

#: Relevance the scripted reader reports per paper. A number the reader
#: coerces with `float()`, so it has to be one.
SCRIPTED_RELEVANCE: Final[float] = 0.9


class ScriptedSurfaceBreach(RuntimeError):
    """A model call reached `src.llm` while the scripted surface was up.

    Raised by the tripwire rather than by a mock's assertion so it
    travels as an ordinary exception: `run_query` captures it on the
    record like any other node failure, the campaign keeps going, and
    the row it lands on names the node that tried to spend money.
    """


class EpisodeHookBreach(RuntimeError):
    """An `EpisodeHooks` implementation edited a record it may only read.

    `after_episode` is handed the campaign's own record so it can attach
    a `contracts` block. Everything else on that record is the harness's
    statement about the run — the trajectory, the costs, the provenance,
    the `error` field the gate reads — and a hook that rewrites any of
    it is rewriting the evidence. Raised by `_after_episode` *after* the
    record has been restored to what the harness wrote, so the row that
    reaches disk is the harness's own and carries this as its `error`.
    """


# ---------------------------------------------------------------------------
# The script
#
# Four responders, one per agent that calls `call_llm_json` on the fixed
# pipeline. Each returns the smallest shape that agent's parser accepts,
# for the same reason `tests/fixtures/e2e/research_llm_responses.json`
# does: the graph then runs its real nodes, its real router and its real
# reducers while `src/llm.py` is never reached and the cost accumulator
# never moves.
#
# The synthesizer is the one responder that is not a constant, and that
# is the design. It is handed the papers the *graph* retrieved, off the
# stream the driver is already reading, so the citations in a scripted
# report are the run's own corpus rather than a fixed list. A search
# that returns four papers instead of five, a reader that drops one, or
# a citation entry that `_parse_citations` rejects all move the claim
# set this tier measures — which is the difference between a groundedness
# number about the product and one about the fixture.
# ---------------------------------------------------------------------------


def _scripted_planner(query: BenchmarkQuery) -> dict[str, Any]:
    """The plan, derived from the benchmark query's declared topics.

    Derived rather than fixed so the campaign moves when the benchmark
    moves — and `RESEARCH_DATASET_VERSION` moves with it, so a
    comparison across a benchmark edit is refused rather than reported
    (ADR 0070).
    """
    topics = list(query["expected_topics"])
    return {
        "sub_questions": [f"What does the literature report about {t}?" for t in topics],
        "search_queries": topics,
    }


def _scripted_reader() -> dict[str, Any]:
    """One paper analysis, in the shape `_analyze_paper` unpacks.

    Content-free on purpose. `paper_id` and `title` are taken from the
    paper by the agent itself rather than from this response, so nothing
    here can misattribute an analysis, and the reader's own fan-out and
    per-paper error guard are what this tier is exercising.
    """
    return {
        "key_findings": [
            "The paper's abstract is the only source available to this analysis."
        ],
        "methodology": "Abstract-only reading; the scripted tier fetches no full text.",
        "results_summary": "Not reproduced — the scripted tier makes no model call.",
        "limitations": "Scripted analysis: this text is the harness's, not a model's.",
        "relevance": SCRIPTED_RELEVANCE,
    }


def _citation_year(paper_id: str) -> str:
    """Publication year, read off an arXiv identifier's `YYMM` prefix.

    `2311.09000` -> `2023`. Falls back to an empty string for anything
    that is not a new-style identifier, which `_parse_citations` accepts
    (only `title` is load-bearing there).
    """
    for token in paper_id.replace("/", " ").replace(":", " ").split():
        head, _, _ = token.partition(".")
        if len(head) == 4 and head.isdigit():
            return f"20{head[:2]}"
    return ""


def _scripted_synthesizer(papers: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """A report that cites exactly the papers the graph retrieved.

    Two surfaces carry the identifiers, because
    `measure_groundedness` checks both and a report that cited only one
    of them would leave half the check untested: an inline
    `arXiv:<id>` reference per paragraph in the body, and a complete
    `citations` entry per paper. Both dedupe onto the same `claim_id`
    (the digest is of the canonical identifier, not of the surface), so
    a five-paper corpus yields five claims, not ten.

    Deliberately quote-free. `extract_quotes` reads any six-word span
    inside double quotes as a claim, and with no full text to check it
    against every such claim would be undecidable — a column of
    exclusions that says nothing. The report uses no double quotes so
    `quote_verbatim_rate` reports `no_quotes`, which is the true reason.
    """
    citations: list[dict[str, Any]] = []
    paragraphs: list[str] = []
    for paper in papers:
        paper_id = str(paper.get("id") or "")
        title = str(paper.get("title") or "").strip()
        authors = [str(a) for a in (paper.get("authors") or [])]
        year = _citation_year(paper_id)
        surname = authors[0].split()[-1] if authors else "Anon"
        if not title:
            # `_parse_citations` drops an entry with no title, which
            # would silently shrink the claim set. Naming the paper by
            # its identifier keeps the entry, and keeps the fact that
            # the title was missing visible in the record.
            title = f"Untitled paper {paper_id}"
        citations.append(
            {
                "paper_id": paper_id,
                "title": title,
                "authors": authors,
                "year": year,
                "url": str(paper.get("url") or paper_id),
            }
        )
        paragraphs.append(
            f"## {title}\n\n"
            f"This paper was retrieved for the question above and read from its "
            f"abstract alone (arXiv:{_arxiv_tail(paper_id)}) [{surname}, {year}]."
        )
    body = "\n\n".join(paragraphs) or (
        "No papers were retrieved for this question, so this briefing makes no "
        "claim and cites nothing."
    )
    return {
        "draft_report": f"# Scripted briefing\n\n{body}\n",
        "citations": citations,
    }


def _arxiv_tail(paper_id: str) -> str:
    """The bare identifier from an arXiv abs URL, or the id unchanged.

    `http://arxiv.org/abs/2311.09000` -> `2311.09000`. Written here
    rather than reusing `groundedness.canonical_arxiv_id` because this
    side must not depend on the checker's normalisation: the scripted
    report is the *input* to that check, and deriving the input from the
    checker would make the two agree by construction.
    """
    tail = paper_id.rstrip("/").rsplit("/", 1)[-1]
    return tail or paper_id


def _scripted_critic() -> dict[str, Any]:
    """One approving critic pass, in the shape `critic_agent` coerces."""
    return {
        "scores": {
            "completeness": SCRIPTED_QUALITY_SCORE,
            "accuracy": SCRIPTED_QUALITY_SCORE,
            "coherence": SCRIPTED_QUALITY_SCORE,
            "depth": SCRIPTED_QUALITY_SCORE,
            "balance": SCRIPTED_QUALITY_SCORE,
        },
        "average_score": SCRIPTED_QUALITY_SCORE,
        "critique": "Scripted approval: this tier does not judge report quality.",
        "revision_needed": False,
        "revision_target": "",
    }


#: The callables whose source is the script. Digested below, so the
#: script versions itself the way `benchmark_queries` versions the
#: dataset — derived, not declared, because a hand-maintained version is
#: a constant somebody forgets to bump and a baseline compared across a
#: changed script is a measurement of the change.
_SCRIPT_SOURCES: Final[tuple[Callable[..., Any], ...]] = (
    _scripted_planner,
    _scripted_reader,
    _scripted_synthesizer,
    _scripted_critic,
    _citation_year,
    _arxiv_tail,
)

#: Declared fallback, used only when the source is unreadable (a frozen
#: or zipped install). A row that carries it says so, because the digest
#: it replaces is absent from the string.
SCRIPT_VERSION: Final[str] = "1.0.0"


def script_digest() -> str:
    """Content-derived version of the script, or `SCRIPT_VERSION`.

    Twelve hex characters of a SHA-256 over the responders' own source,
    so *any* edit to what the scripted model says — a template, a
    constant, a branch — moves the campaign's `dataset_version` and
    makes `regression_diff` refuse a comparison across it (exit 3)
    instead of reporting the script change as a product movement.

    Deliberately conservative in the direction of false positives: a
    whitespace-only edit bumps it too. Rebaselining this tier costs a
    few seconds of local compute (`make research-scripted-baseline`),
    and the alternative failure — a silently stale baseline — costs a
    wrong verdict.
    """
    try:
        payload = "\n".join(inspect.getsource(fn) for fn in _SCRIPT_SOURCES)
    except (OSError, TypeError):
        return SCRIPT_VERSION
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def scripted_dataset_version() -> str:
    """The benchmark fingerprint and the script digest, in one field.

    `dataset_version` is one of `regression_diff.COMPARABILITY_FIELDS`,
    and in this tier the *instrument* is two things rather than one: the
    twenty benchmark queries and the words the scripted model says about
    them. Both are content-derived and both belong in the field that
    decides whether two campaigns may be compared, so they travel
    together rather than one of them travelling silently.
    """
    return f"{RESEARCH_DATASET_VERSION}+script:{script_digest()}"


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


class ScriptedSurface:
    """The four canned responses, installed over the agents' own names.

    `call_llm_json` is imported into each agent's namespace at import
    time, so the patch has to land per module — patching
    `src.llm.call_llm_json` would do nothing at all, and a surface that
    silently did nothing is the failure mode this class exists to make
    impossible. `tests/e2e/conftest.py` learned the same thing.

    `calls` counts what the graph asked for. It is written onto every
    record as `scripted_llm_calls`, which answers two questions no other
    column can: whether the graph really ran (a campaign that made zero
    scripted calls did not), and what the funded lane would pay for on
    the same trajectory.
    """

    def __init__(self, query: BenchmarkQuery) -> None:
        self.query = query
        self.calls: dict[str, int] = dict.fromkeys(FIXED_PIPELINE, 0)
        #: The papers the graph retrieved, fed in by the driver off the
        #: `updates` stream before the synthesizer runs.
        self.papers: list[dict[str, Any]] = []

    # -- responders ---------------------------------------------------

    def planner(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls["planner"] += 1
        return _scripted_planner(self.query)

    def reader(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls["reader"] += 1
        return _scripted_reader()

    def synthesizer(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls["synthesizer"] += 1
        return _scripted_synthesizer(self.papers)

    def critic(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls["critic"] += 1
        return _scripted_critic()

    # -- driver hooks -------------------------------------------------

    def observe(self, node: str, update: Any) -> None:
        """Record what a finished node produced, for a later responder.

        Called from the driver's stream loop. LangGraph resumes the
        graph only when the consumer asks for the next chunk, so a
        chunk for `search` is in hand strictly before the synthesizer
        node runs — which is what lets the scripted report cite the
        run's own corpus without parsing a prompt.
        """
        if node == "search" and isinstance(update, dict):
            papers = update.get("papers")
            if isinstance(papers, list):
                self.papers = [p for p in papers if isinstance(p, dict)]

    @property
    def total_calls(self) -> int:
        """Every scripted response handed to the graph, all nodes."""
        return sum(self.calls.values())


def _tripwire(*_args: Any, **_kwargs: Any) -> Any:
    """Stand in for `src.llm.call_llm` and refuse to be called.

    The layer that makes zero spend structural rather than enumerated.
    The four patches above cover the four agents on the fixed pipeline;
    this one covers everything they do not — a new node, a judge, a
    supervisor branch, a retry helper — and it covers it by construction
    rather than by somebody remembering to extend a list.
    """
    raise ScriptedSurfaceBreach(
        "the scripted research tier reached src.llm.call_llm; the tier "
        "advertises zero spend and makes no model call. A node or a metric "
        "on this path is not covered by the scripted surface."
    )


def _client_tripwire(*_args: Any, **_kwargs: Any) -> Any:
    """Stand in for provider-client construction and refuse to be called.

    `_tripwire` covers the *call*; this covers the *client*, and they are
    not the same hole. `src.llm.call_llm` is the only path a graph node
    has, so patching it was enough while the only code inside the surface
    was the harness's own. `EpisodeHooks` changed that: a hook is code
    this module did not write, and the first thing code that wants to
    spend money does is build its own client — `anthropic.Anthropic(...)`
    straight from the SDK, or `src.llm._get_client()` to reuse the
    singleton — neither of which goes anywhere near `call_llm`.

    Both names are therefore patched, and both are needed: the SDK
    constructor covers a hook that imports `anthropic` itself, and
    `_get_client` covers the case where `src.llm._client` is already
    built and the constructor is never reached.

    Refusing construction rather than the request is the stronger line
    to hold. A client with a working key is one `.messages.create` away
    from a charge, and that call is inside the SDK where no patch of
    ours is watching.
    """
    raise ScriptedSurfaceBreach(
        "the scripted research tier tried to build a provider client; the "
        "tier advertises zero spend and constructs no client. Hook code "
        "runs inside this surface and may observe the campaign, not call "
        "a model."
    )


@contextlib.contextmanager
def _spend_guard() -> Iterator[None]:
    """The zero-spend half of the surface, on its own.

    Split out of `scripted_surface` so it can be wrapped around the
    `EpisodeHooks` calls that happen outside the graph run —
    `before_episode` runs before the graph is built and `after_episode`
    after the state is final, and a guarantee that lapses between
    episodes is not structural. Nothing is scripted here: a hook has no
    business receiving a canned planner response, only a locked till.
    """
    import anthropic

    import src.llm as llm_module

    guards: tuple[tuple[Any, str, Any], ...] = (
        (llm_module, "call_llm", _tripwire),
        (llm_module, "_get_client", _client_tripwire),
        (anthropic, "Anthropic", _client_tripwire),
    )
    with contextlib.ExitStack() as stack:
        for module, name, replacement in guards:
            original = getattr(module, name)
            setattr(module, name, replacement)
            stack.callback(setattr, module, name, original)
        yield


@contextlib.contextmanager
def scripted_surface(query: BenchmarkQuery) -> Iterator[ScriptedSurface]:
    """Install the script for one query, and take it down again.

    Plain `setattr` through an `ExitStack` rather than
    `unittest.mock.patch`: this is production code, it runs outside a
    test session, and the restore has to happen on the exception path
    too — a campaign whose second query ran against a surface the first
    query left behind would be measuring the harness.
    """
    import src.agents.critic as critic_module
    import src.agents.planner as planner_module
    import src.agents.reader as reader_module
    import src.agents.synthesizer as synthesizer_module

    surface = ScriptedSurface(query)
    patches: tuple[tuple[Any, str, Any], ...] = (
        (planner_module, "call_llm_json", surface.planner),
        (reader_module, "call_llm_json", surface.reader),
        (synthesizer_module, "call_llm_json", surface.synthesizer),
        (critic_module, "call_llm_json", surface.critic),
        # Abstract-only fallback (ADR 0004). The mock corpus has no
        # local full text and a per-PR gate must not fetch five PDFs
        # from arxiv.org; `tests/e2e/conftest.py` stubs the same call
        # for the same reason.
        (reader_module, "parse_pdf", lambda _url: ""),
    )
    with contextlib.ExitStack() as stack:
        stack.enter_context(_spend_guard())
        for module, name, replacement in patches:
            original = getattr(module, name)
            setattr(module, name, replacement)
            stack.callback(setattr, module, name, original)
        yield surface


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


class ScriptedOutcomes(NamedTuple):
    """What one scripted run structurally did, and what it failed to do.

    The research lane's counterpart of
    `simulate_learner.ScenarioOutcomes`. Everything here is observed
    rather than judged, and `expectation_failures` is the field the gate
    reads at zero tolerance — a scripted campaign is deterministic, so
    one unmet expectation is a product change, never variance.

    Attributes:
        trajectory: Nodes the graph reported, in order.
        trajectory_expected: `trajectory == FIXED_PIPELINE`.
        papers: Papers `search` put on the state.
        analyses: Analyses `reader` put on the state.
        citations: Citations that survived `_parse_citations`.
        report_chars: Length of the assembled report.
        iterations: Critic passes recorded.
        expectation_failures: One sentence per unmet expectation.
    """

    trajectory: list[str]
    trajectory_expected: bool
    papers: int
    analyses: int
    citations: int
    report_chars: int
    iterations: int
    expectation_failures: list[str]


def compute_outcomes(
    trajectory: Sequence[str], state: dict[str, Any]
) -> ScriptedOutcomes:
    """Read the structural expectations off a finished run.

    Each expectation names a defect it would catch, and none of them is
    a quality claim: the report's *content* is the harness's, so the
    only honest assertions are about the pipeline that assembled it.
    Groundedness is scored separately and gated separately, for exactly
    that reason.
    """
    visited = list(trajectory)
    papers = state.get("papers") or []
    analyses = state.get("paper_analyses") or []
    citations = state.get("citations") or []
    report = str(state.get("draft_report") or "")
    iterations = int(state.get("iteration") or 0)

    failures: list[str] = []
    if visited != list(FIXED_PIPELINE):
        failures.append(
            f"trajectory was {' -> '.join(visited) or '(empty)'}, expected "
            f"{' -> '.join(FIXED_PIPELINE)}"
        )
    if not papers:
        failures.append("search put no papers on the state")
    if len(analyses) != len(papers):
        failures.append(
            f"{len(analyses)} analysis/analyses for {len(papers)} paper(s) — "
            "the reader fan-out dropped one"
        )
    if not report.strip():
        failures.append("the synthesizer produced no report")
    if not citations:
        failures.append(
            "the report carries no citations — `_parse_citations` rejected "
            "every entry the scripted synthesizer offered"
        )
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict) or not str(citation.get("title") or "").strip():
            failures.append(f"citation {index} has no title")
    if iterations != 1:
        failures.append(
            f"the critic recorded {iterations} pass(es), expected exactly 1 — "
            "the scripted critic approves, so a second pass is a routing bug"
        )
    if state.get("revision_needed"):
        failures.append("the run finished with a revision still outstanding")

    return ScriptedOutcomes(
        trajectory=visited,
        trajectory_expected=visited == list(FIXED_PIPELINE),
        papers=len(papers),
        analyses=len(analyses),
        citations=len(citations),
        report_chars=len(report),
        iterations=iterations,
        expectation_failures=failures,
    )


# ---------------------------------------------------------------------------
# One record
# ---------------------------------------------------------------------------


def scripted_provenance() -> RunProvenance:
    """Provenance for one scripted-research record.

    `rubrics` is the deterministic groundedness check alone, because
    that is the only scorer this tier runs. A funded row carries four
    rubrics; the two therefore disagree on `rubric_versions` as well as
    on `tier` and `mock_mode`, and `regression_diff` refuses the
    comparison three times over.
    """
    return capture(
        tier=RESEARCH_SCRIPTED_TIER,
        dataset_version=scripted_dataset_version(),
        rubrics=(GROUNDEDNESS_CHECK,),
    )


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe snapshot — drops the non-serializable message list."""
    return {k: v for k, v in state.items() if k != "messages"}


# ---------------------------------------------------------------------------
# The episode seam
#
# One extension point, defaulting to nothing. It exists so that a second
# author who needs to observe this campaign — WO-W05's research shadow is
# the first — does not have to edit the driver to do it. The alternative
# is two authors editing `run_query` and `drive_query` for two different
# reasons, which is how a harness acquires a second set of hooks that
# fire in a slightly different place from the first.
#
# The bargain, stated once so neither side has to infer it:
#
#   - This module owns the file. A hooks implementation lives in the
#     consumer's own module and this one never imports it; `EpisodeHooks`
#     is a `Protocol`, so there is no base class to inherit and no import
#     edge in either direction.
#   - A hook observes. `after_episode` may attach `record["contracts"]`
#     and may change nothing else — enforced below, not requested in a
#     comment.
#   - A hook cannot spend. It runs inside `_spend_guard`, so a model call
#     or a provider client raises `ScriptedSurfaceBreach` and the episode
#     fails rather than the tier quietly stopping being free.
#   - `hooks=None` is the whole of today. No guard installed, no snapshot
#     taken, no call made — the default path does not execute one line of
#     this section.
#
# `docs/eval.md` says the same thing in prose, and says who owns which
# side of it.
# ---------------------------------------------------------------------------


class EpisodeHooks(Protocol):
    """What `run_query` will call, if it is given something to call.

    Structural, not nominal: an implementation satisfies this by having
    the three methods, and mypy checks that at the call site rather than
    at an inheritance the consumer would otherwise owe us.

    All three are optional in the weak sense that a no-op body is a
    legitimate implementation, and in no other sense — a hooks object
    missing one of them fails `--strict` at the point it is passed in,
    which is where the author can still do something about it.
    """

    def before_episode(self, query: BenchmarkQuery, repeat: int) -> Any:
        """Open an episode. Whatever this returns is the episode's `ctx`.

        Called once per record, before the graph is built, and handed
        back verbatim to the other two. The harness never inspects it —
        it is the hook's own scratch space, and `None` is a fine value
        for an implementation that needs none.
        """
        ...

    def on_stream_event(self, ctx: Any, mode: str, payload: Mapping[str, Any]) -> None:
        """Observe one chunk off the graph's own stream.

        `mode` is LangGraph's stream mode — `"updates"` (a mapping of
        node name to the update it produced) or `"values"` (the whole
        state after that step). The payload is the driver's, live and
        unshared: mutating it changes what the graph and the scripted
        synthesizer see next. Don't.
        """
        ...

    def after_episode(
        self, ctx: Any, record: dict[str, Any], final_state: Mapping[str, Any]
    ) -> None:
        """Close an episode, with the finished record in hand.

        The one place a hook may write. `record["contracts"]` is the one
        key it may write to, it must be a mapping, and the rest of the
        record is read-only — see `_after_episode` for what "read-only"
        is and is not able to mean here.
        """
        ...


#: The only key `after_episode` may add to a record. Named rather than
#: inlined because it is the seam's entire write surface, and a reader
#: asking "what can a hook change?" should find one answer in one place.
HOOK_WRITABLE_KEY: Final[str] = "contracts"


def _before_episode(
    hooks: EpisodeHooks | None, query: BenchmarkQuery, repeat: int
) -> Any:
    """Open the episode on the hook, under the spend guard. `None` if no hook."""
    if hooks is None:
        return None
    with _spend_guard():
        return hooks.before_episode(query, repeat)


def _after_episode(
    hooks: EpisodeHooks | None,
    ctx: Any,
    record: dict[str, Any],
    final_state: Mapping[str, Any],
) -> None:
    """Close the episode on the hook, and hold it to `contracts` only.

    **How the restriction is enforced, and what that buys.** A shallow
    copy of the record is taken before the call and compared after, key
    by key, by *identity*. That catches, exactly:

      - any key added other than `contracts`;
      - any key removed, `contracts` included;
      - any key rebound — `record["error"] = None`, `record["costs"] =
        {...}` — even to a value that compares equal to the old one,
        which is why identity rather than `==`.

    **What it does not catch**, stated because a guarantee whose edges
    are unwritten gets read as covering everything: a mutation *inside*
    a value the record already holds. `record["costs"]["call_count"] =
    0`, `record["trajectory"].append("critic")` and
    `record["outcomes"]["expectation_failures"].clear()` all leave the
    top-level keys bound to the very same objects, so the comparison
    sees nothing and the restore below cannot undo them either. Closing
    that would mean deep-copying every record — the serialized graph
    state included — around a call that is a no-op in the default
    configuration, to defend against a hook that is in-tree, reviewed,
    and could equally well have edited this file.

    So the honest summary is: this stops a hook from *rewriting the
    record*, and it does not stop one determined to *corrupt* it. The
    guarantee that does not depend on the hook's cooperation is the
    other one — `_spend_guard` — because that one is about money.

    On a breach the record is restored to the snapshot (dropping
    `contracts` with everything else: the episode failed, so its
    contracts block is not evidence of anything) and `EpisodeHookBreach`
    is raised for `run_query` to record as the row's `error`.
    """
    if hooks is None:
        return
    before = dict(record)
    with _spend_guard():
        hooks.after_episode(ctx, record, final_state)

    added = record.keys() - before.keys() - {HOOK_WRITABLE_KEY}
    removed = before.keys() - record.keys()
    rebound = {
        key
        for key in (before.keys() & record.keys()) - {HOOK_WRITABLE_KEY}
        if record[key] is not before[key]
    }
    strays = sorted(added | removed | rebound)
    block = record.get(HOOK_WRITABLE_KEY)
    ill_typed = HOOK_WRITABLE_KEY in record and not isinstance(block, Mapping)

    if strays or ill_typed:
        record.clear()
        record.update(before)
        detail = (
            f"touched {', '.join(repr(key) for key in strays)}"
            if strays
            else f"set {HOOK_WRITABLE_KEY!r} to a {type(block).__name__}, not a mapping"
        )
        raise EpisodeHookBreach(
            f"after_episode {detail}; a hook may add "
            f"record[{HOOK_WRITABLE_KEY!r}] as a mapping and change nothing "
            "else. The record has been restored to what the harness wrote."
        )


def drive_query(
    query: BenchmarkQuery,
    run_id: str,
    surface: ScriptedSurface,
    *,
    hooks: EpisodeHooks | None = None,
    ctx: Any = None,
) -> tuple[list[str], dict[str, Any]]:
    """Run the compiled graph to completion, recording its trajectory.

    `stream` rather than `invoke` for two reasons, and both are
    load-bearing. The trajectory comes out of the run itself instead of
    being reconstructed afterwards — the assertion this tier exists for.
    And the loop is where the scripted synthesizer learns which papers
    the graph retrieved, which is what keeps its citations the product's
    rather than the fixture's.

    It is also the only place an observer can see the run happen rather
    than read about it afterwards, which is why `on_stream_event` fires
    here. A hook is handed each chunk before this driver has touched it,
    and it is not given a copy: see `EpisodeHooks.on_stream_event`.

    Args:
        query: The benchmark query to drive.
        run_id: This episode's run id, used as the graph's thread id.
        surface: The installed script, told which papers search found.
        hooks: Optional observer. `None` is the default and makes this
            function byte-for-byte the one that ran before the seam
            existed — the loop below tests it once per chunk and does
            nothing.
        ctx: Whatever `before_episode` returned, passed straight back.

    Returns:
        The nodes the graph reported, in order, and its final state.
    """
    visited: list[str] = []
    final: dict[str, Any] = {}
    app: Any = None
    try:
        app = build_workflow(enable_hitl=False)
        config = {"configurable": {"thread_id": run_id}}
        for mode, payload in app.stream(
            dict(_initial_state(query["query"], run_id)),
            config=config,
            stream_mode=["updates", "values"],
        ):
            if hooks is not None and isinstance(payload, Mapping):
                hooks.on_stream_event(ctx, str(mode), payload)
            if mode == "values":
                final = dict(payload)
                continue
            if not isinstance(payload, dict):
                continue
            for node, update in payload.items():
                if node == _INTERRUPT_KEY:
                    continue
                visited.append(str(node))
                surface.observe(str(node), update)
    finally:
        _close_workflow(app)
    return visited, final


def _initial_state(query: str, run_id: str) -> dict[str, Any]:
    """Fresh research state for one scripted invocation.

    `runner._initial_state` is not reused: it is typed as
    `ResearchState` and this module hands the graph a plain dict, and
    duplicating eight lines is cheaper than widening a signature in a
    module two campaigns share. The field list is pinned by
    `tests/test_simulate_research.py` against `initial_research_state`.
    """
    from src.graph.state import initial_research_state

    return dict(initial_research_state(query, run_id))


def score_groundedness(state: dict[str, Any]) -> GroundednessResult:
    """Score the assembled report against the corpus the run retrieved.

    No `full_texts`: the scripted tier fetches no PDFs, so every quote
    claim would be undecidable and `quote_verbatim_rate` honestly
    reports `no_quotes`. The identifier half is the half this tier can
    measure, and it is the half the gate reads (ADR 0074).
    """
    return measure_groundedness(
        str(state.get("draft_report") or ""),
        list(state.get("papers") or []),
        list(state.get("citations") or []),
    )


def run_query(
    query: BenchmarkQuery, *, repeat: int = 1, hooks: EpisodeHooks | None = None
) -> dict[str, Any]:
    """Drive and score one benchmark query. Never raises for a failure.

    Errors are captured on the record so the campaign keeps making
    progress (ADR 0008). `EvalInterrupted` is the one exception that
    leaves, carrying the partial record. A hook that raises — including
    one the spend guard or the record contract stopped — is an error like
    any other: it lands on `record["error"]`, the campaign continues, and
    `scripted_tier_check` refuses the campaign because a row errored.
    That is deliberate. An observer must not be able to fail an episode
    silently, and it must not be able to abort a campaign either.

    Args:
        query: The benchmark query to run.
        repeat: 1-based repeat index. Repeats buy nothing here — the
            tier is deterministic — and the CLI says so rather than
            refusing, because a repeated run is a legitimate way to
            *check* that it is.
        hooks: Optional episode observer (see `EpisodeHooks`). `None`,
            the default, is exactly the behaviour this function had
            before the seam existed: nothing is installed and nothing is
            called.

    Returns:
        The full per-query record.

    Raises:
        EvalInterrupted: On Ctrl-C / SIGTERM, carrying the partial record.
    """
    run_id = uuid.uuid4().hex[:16]
    token = bind_run_id(run_id)
    costs = start_cost_tracking()
    start = time.monotonic()

    record: dict[str, Any] = {
        "record_id": research_record_id(query["query_id"], repeat),
        "run_id": run_id,
        "query_id": query["query_id"],
        "repeat": repeat,
        "query": query["query"],
        "domain": query["domain"],
        "tier": RESEARCH_SCRIPTED_TIER,
        "elapsed_sec": 0.0,
        "scoring_sec": None,
        "costs": costs.as_dict(),
        "judge_costs": None,
        "scripted_calls": {},
        "state": None,
        "trajectory": [],
        "outcomes": None,
        "groundedness": None,
        "metrics": None,
        "metrics_error": None,
        "error": None,
        # Captured at record creation, not at summary-render time:
        # `rebuild_summaries` re-derives `summary.jsonl` from these
        # durable records, and a block written then would describe the
        # rebuild rather than the run (ADR 0070).
        PROVENANCE_KEY: scripted_provenance(),
    }

    # The runner's own event names, reused rather than minted. These
    # are eval query lifecycle events and `tier` is on the line, so a
    # log reader can separate the scripted campaign from the funded one
    # without a second vocabulary to learn — and
    # `src/observability/logging.py`, which owns the closed event set,
    # needs no edit for a campaign that says nothing new.
    log.info(
        "eval_query_started",
        extra={
            "query_id": query["query_id"],
            "domain": query["domain"],
            "tier": RESEARCH_SCRIPTED_TIER,
        },
    )
    try:
        try:
            ctx = _before_episode(hooks, query, repeat)
            with scripted_surface(query) as surface:
                trajectory, final_state = drive_query(
                    query, run_id, surface, hooks=hooks, ctx=ctx
                )
        except Exception as exc:
            record["elapsed_sec"] = time.monotonic() - start
            record["costs"] = costs.as_dict()
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc()
            log.exception(
                "eval_query_failed",
                extra={
                    "query_id": query["query_id"],
                    "tier": RESEARCH_SCRIPTED_TIER,
                },
            )
            return record

        record["elapsed_sec"] = time.monotonic() - start
        record["costs"] = costs.as_dict()
        record["scripted_calls"] = dict(surface.calls)
        record["trajectory"] = trajectory
        record["state"] = _serialize_state(final_state)

        outcomes = compute_outcomes(trajectory, final_state)
        record["outcomes"] = outcomes._asdict()

        scoring_start = time.monotonic()
        try:
            result = score_groundedness(final_state)
            record["groundedness"] = result
            record["metrics"] = {
                "citation_accuracy": dict(
                    measure_citation_accuracy(
                        str(final_state.get("draft_report") or ""),
                        list(final_state.get("citations") or []),
                    )
                )
            }
        except Exception as exc:  # noqa: BLE001 — scoring must not cost the run
            record["metrics_error"] = f"{type(exc).__name__}: {exc}"
            log.exception(
                "eval_metric_failed",
                extra={
                    "query_id": query["query_id"],
                    "metric": "groundedness",
                },
            )
        record["scoring_sec"] = time.monotonic() - scoring_start
        # Harness spend is zero by construction here, but the column is
        # written rather than omitted: `scripted_tier_check` asserts on
        # its presence, and an absent column reads as "not measured".
        record["judge_costs"] = {"total_cost_usd": 0.0, "call_count": 0}

        # Last, with the record finished: the block a hook may attach
        # describes a completed episode, and a hook that fails one has
        # not cost the campaign anything already measured. Caught rather
        # than allowed to leave, for the same reason the drive path
        # catches — an observer may fail its own episode and may not
        # abort the campaign (ADR 0008). The row carries the failure, so
        # the gate refuses the campaign and nothing failed quietly.
        try:
            _after_episode(hooks, ctx, record, final_state)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc()
            log.exception(
                "eval_query_failed",
                extra={
                    "query_id": query["query_id"],
                    "tier": RESEARCH_SCRIPTED_TIER,
                },
            )
            return record

        log.info(
            "eval_query_completed",
            extra={
                "query_id": query["query_id"],
                "tier": RESEARCH_SCRIPTED_TIER,
                "elapsed_sec": round(record["elapsed_sec"], 2),
                "expectation_failures": len(outcomes.expectation_failures),
                "cost_usd": record["costs"]["total_cost_usd"],
            },
        )
        return record
    except KeyboardInterrupt as exc:
        record["error"] = f"Interrupted: {type(exc).__name__}"
        record["costs"] = costs.as_dict()
        if not record["elapsed_sec"]:
            record["elapsed_sec"] = time.monotonic() - start
        raise EvalInterrupted(record) from exc
    finally:
        reset_run_id(token)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _outcome(record: dict[str, Any], field: str) -> Any:
    """One field off the record's outcomes block, or `None`."""
    outcomes = record.get("outcomes")
    return outcomes.get(field) if isinstance(outcomes, dict) else None


def _metric_field(result: Any, metric: str, field: str) -> Any:
    """One field off a `Metric` inside a groundedness result."""
    if not isinstance(result, dict):
        return None
    block = result.get(metric)
    return block.get(field) if isinstance(block, dict) else None


def summary_line(record: dict[str, Any]) -> dict[str, Any]:
    """Project one record onto its `summary.jsonl` row.

    Deliberately a superset of the research lane's own row where the
    fields mean the same thing (`query_id`, `citation_resolution_rate`,
    `citations_checked`, `cost_usd`, `llm_calls`), so a reader who knows
    one summary knows this one, and `regression_diff`'s research-lane
    vocabulary carries over. It does **not** carry the three judged
    metrics: this tier runs no judge, and a permanently-null column is
    noise rather than a measurement (the rule ADR 0074 applied to
    `quote_verbatim_rate`).

    `paired_outcomes` is the new field and the reason Phase 2 of this
    work order exists — `{claim_id: grounded}` for every claim the check
    decided, which `regression_diff.claim_outcomes` namespaces by query
    and hands to McNemar.
    """
    costs = record.get("costs") or {}
    judge_costs = record.get("judge_costs") or {}
    result = record.get("groundedness")
    metrics = record.get("metrics") or {}
    accuracy = metrics.get("citation_accuracy") if isinstance(metrics, dict) else None
    workflow_cost = costs.get("total_cost_usd")
    judge_cost = judge_costs.get("total_cost_usd")
    outcomes = record.get("outcomes")
    # `result` arrives as a plain dict when the record was read back off
    # disk — `GroundednessResult` is a `TypedDict`, so the cast is a
    # statement about the shape rather than a conversion, and
    # `paired_outcomes` reads exactly one key of it.
    claims = (
        paired_outcomes(cast("GroundednessResult", result))
        if isinstance(result, dict)
        else {}
    )

    return {
        "record_id": record.get("record_id") or record["query_id"],
        "query_id": record["query_id"],
        "repeat": record.get("repeat", 1),
        "tier": record.get("tier"),
        "elapsed_sec": record.get("elapsed_sec"),
        "scoring_sec": record.get("scoring_sec"),
        "error": record.get("error"),
        "metrics_error": record.get("metrics_error"),
        # -- the gated metrics ---------------------------------------
        "citation_resolution_rate": _metric_field(
            result, "citation_resolution_rate", "value"
        ),
        "citations_checked": _metric_field(
            result, "citation_resolution_rate", "denominator"
        ),
        "citation_resolution_reason": _metric_field(
            result, "citation_resolution_rate", "reason"
        ),
        "claims_decided": None if result is None else len(claims),
        "expectation_failures": (
            None
            if not isinstance(outcomes, dict)
            else len(outcomes.get("expectation_failures") or [])
        ),
        "iterations": _outcome(record, "iterations"),
        # Zero by construction, asserted anyway. See the module
        # docstring's fourth layer.
        "llm_calls": costs.get("call_count"),
        "cost_usd": workflow_cost,
        "judge_cost_usd": judge_cost,
        "judge_llm_calls": judge_costs.get("call_count"),
        "total_cost_usd": (
            None
            if workflow_cost is None and judge_cost is None
            else round((workflow_cost or 0.0) + (judge_cost or 0.0), 6)
        ),
        # -- diagnostics ---------------------------------------------
        "citation_accuracy": (
            accuracy.get("score") if isinstance(accuracy, dict) else None
        ),
        "unsupported_claims": _metric_field(
            result, "unsupported_claim_count", "numerator"
        ),
        "quote_verbatim_reason": _metric_field(result, "quote_verbatim_rate", "reason"),
        "papers": _outcome(record, "papers"),
        "analyses": _outcome(record, "analyses"),
        "citations": _outcome(record, "citations"),
        "report_chars": _outcome(record, "report_chars"),
        "trajectory": _outcome(record, "trajectory"),
        "trajectory_expected": _outcome(record, "trajectory_expected"),
        # What the funded lane would have paid for on this trajectory —
        # and, read the other way, proof the graph ran at all.
        "scripted_llm_calls": sum((record.get("scripted_calls") or {}).values()),
        "paired_outcomes": claims,
        PROVENANCE_KEY: record.get(PROVENANCE_KEY) or {},
    }


def _campaign_cost(rows: Sequence[dict[str, Any]]) -> float:
    """Total dollars across a campaign's rows, nulls read as zero."""
    return sum(float(row.get("total_cost_usd") or 0.0) for row in rows)


def summary_markdown(records: list[dict[str, Any]], run_id: str) -> str:
    """Render `summary.md` for a scripted-research campaign."""
    rows = [summary_line(record) for record in records]
    errored = [row for row in rows if row["error"]]
    unmet = [row for row in rows if row["expectation_failures"]]

    lines = [
        f"# Scripted research campaign — {run_id}",
        "",
        f"- Queries: {len(rows)} ({len(errored)} errored)",
        f"- Total cost: ${_campaign_cost(rows):.4f}",
        f"- Scripted model responses: {sum(int(r['scripted_llm_calls'] or 0) for r in rows)}",
        f"- Queries with unmet structural expectations: {len(unmet)}",
        "",
        "The report text in every record below is the harness's, not a "
        "model's: mock mode does not stub `src/llm.py`, so this tier "
        "scripts the four research agents' responses itself. What is "
        "measured is the pipeline that assembled the report and the "
        "identifiers it cites — not the model's grounding. See "
        "`docs/eval.md`.",
        "",
        "| Query | Traj. | Papers | Cites | Cit.Res. | n | Claims | Unmet | $ | s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['record_id']}` "
            f"| {'ok' if row['trajectory_expected'] else 'BROKEN'} "
            f"| {_fmt(row['papers'])} "
            f"| {_fmt(row['citations'])} "
            f"| {_fmt(row['citation_resolution_rate'])} "
            f"| {_fmt(row['citations_checked'])} "
            f"| {_fmt(row['claims_decided'])} "
            f"| {_fmt(row['expectation_failures'])} "
            f"| {(row['total_cost_usd'] or 0.0):.4f} "
            f"| {(row['elapsed_sec'] or 0.0):.2f} |"
        )

    lines += [
        "",
        "## Aggregates",
        "",
        f"- Mean `citation_resolution_rate`: {_mean(rows, 'citation_resolution_rate')}",
        f"- Mean citations checked per query: {_mean(rows, 'citations_checked')}",
        f"- Total claims decided: {sum(int(r['claims_decided'] or 0) for r in rows)}",
    ]

    if errored:
        lines += ["", "## Errors", "", "| Query | Error |", "|---|---|"]
        lines += [
            f"| `{row['record_id']}` | {_fmt_cell_text(row['error'])} |"
            for row in errored
        ]

    if unmet:
        lines += ["", "## Unmet structural expectations", ""]
        for record in records:
            failures = _outcome(record, "expectation_failures") or []
            for failure in failures:
                lines.append(f"- `{record.get('record_id')}`: {failure}")

    lines += provenance_markdown(rows)
    return "\n".join(lines) + "\n"


#: The scripted-research campaign's durable layout. Records live under
#: `queries/` and sort in benchmark order, the same shape `runner.py`
#: writes, so one reader and one set of tools serve both.
SCRIPTED_RESEARCH_CAMPAIGN = CampaignShape(
    records_dirname="queries",
    id_field="record_id",
    summary_line=summary_line,
    summary_markdown=summary_markdown,
    order_key=_benchmark_order,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _select_queries(query_ids: list[str] | None) -> list[BenchmarkQuery]:
    """Filter `BENCHMARK_QUERIES` by explicit ids, preserving order."""
    if not query_ids:
        return list(BENCHMARK_QUERIES)
    lookup = {q["query_id"]: q for q in BENCHMARK_QUERIES}
    unknown = [qid for qid in query_ids if qid not in lookup]
    if unknown:
        raise SystemExit(f"Unknown query IDs: {', '.join(unknown)}")
    return [lookup[qid] for qid in query_ids]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the research benchmark against the compiled research "
            "graph with a scripted model surface. Zero spend."
        )
    )
    parser.add_argument(
        "--queries",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=None,
        help="Comma-separated benchmark query IDs. Default: all.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: outputs/eval/rs-<utc-timestamp>/",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Re-enter an interrupted campaign: skip queries whose "
            "queries/<id>.json already exists in --output-dir. Required to "
            "write into a non-empty output directory at all."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help=(
            "Runs per query. This tier is deterministic — the model is a "
            "script and the corpus is fixed — so repeats buy no precision; "
            "they are a way to check that determinism, not to improve an "
            "estimate. Default: 1."
        ),
    )
    return parser.parse_args(argv)


def config_problem(args: argparse.Namespace) -> str | None:
    """Refuse to start a campaign whose environment contradicts the tier.

    Two refusals, and the first is the one that costs money. A scripted
    tier under `USE_MOCK_DATA=false` would drive the graph against live
    arXiv while claiming to be free — and although the surface's
    tripwire would stop any *model* call, search would still leave the
    machine, so the run would neither be offline nor be measuring what
    the tier says it measures. `simulate_learner` refuses the same way
    for the same reason.
    """
    if args.repeats < 1:
        return "Error: --repeats must be at least 1."
    if not settings.use_mock_data:
        return (
            "Error: the scripted research tier claims zero spend and no "
            "network, but USE_MOCK_DATA is false, so the search node would "
            "query arxiv.org. Run with USE_MOCK_DATA=true "
            "ANTHROPIC_API_KEY=local-preview-disabled, or use "
            "`python -m src.eval.runner` for the funded campaign."
        )
    return None


def _print_result(record: dict[str, Any]) -> None:
    """One-line per-query stdout report."""
    row = summary_line(record)
    if record.get("error"):
        print(f"  ERROR: {record['error']}")
        return
    print(
        "  "
        + " ".join(
            [
                f"traj={'ok' if row['trajectory_expected'] else 'BROKEN'}",
                f"papers={_fmt(row['papers'])}",
                f"cites={_fmt(row['citations'])}",
                f"cres={_fmt(row['citation_resolution_rate'])}",
                f"n={_fmt(row['citations_checked'])}",
                f"claims={_fmt(row['claims_decided'])}",
                f"scripted_calls={_fmt(row['scripted_llm_calls'])}",
                f"in {(record.get('elapsed_sec') or 0.0):.2f}s",
                f"${(row['total_cost_usd'] or 0.0):.4f}",
            ]
        )
    )
    for failure in _outcome(record, "expectation_failures") or []:
        print(f"  UNMET: {failure}")
    if record.get("metrics_error"):
        print(f"  PARTIAL SCORE: {record['metrics_error']}")


def main(argv: list[str] | None = None) -> int:
    """Run a scripted research campaign. Returns a `runner.py` exit code."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    problem = config_problem(args)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_CONFIG

    selected = _select_queries(args.queries)

    # Pinned before the first query so every record's `seed` names the
    # generator state the campaign ran under. Nothing in this tier is
    # sampled, so unlike the funded lanes the seed here really does
    # describe a reproducible run — which is a property of the tier, not
    # of the field, and ADR 0070's caveat still stands for the others.
    seed_campaign()

    run_id = "rs-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)

    usage_problem = _check_output_dir(output_dir, resume=args.resume)
    if usage_problem:
        print(usage_problem, file=sys.stderr)
        return EXIT_USAGE

    already_done = (
        load_records(output_dir, shape=SCRIPTED_RESEARCH_CAMPAIGN)
        if args.resume
        else {}
    )
    pending = [
        (query, repeat)
        for repeat in range(1, args.repeats + 1)
        for query in selected
        if research_record_id(query["query_id"], repeat) not in already_done
    ]
    skipped = (len(selected) * args.repeats) - len(pending)

    print(
        f"Scripted research campaign {run_id}: {len(pending)} run(s) "
        f"-> {output_dir}" + (f" (resuming, {skipped} already done)" if skipped else "")
    )

    attempted = 0
    errored = 0
    unmet_expectations = 0
    interrupted = False
    restore_handler = _install_interrupt_handler()
    try:
        for index, (query, repeat) in enumerate(pending, 1):
            print(
                f"[{index}/{len(pending)}] "
                f"{research_record_id(query['query_id'], repeat)}: {query['query']}"
            )
            record = run_query(query, repeat=repeat)
            attempted += 1
            if record.get("error"):
                errored += 1
            if _outcome(record, "expectation_failures"):
                unmet_expectations += 1
            persist_record(output_dir, record, shape=SCRIPTED_RESEARCH_CAMPAIGN)
            _print_result(record)
    except KeyboardInterrupt as exc:
        interrupted = True
        print("\nInterrupted — flushing partial results.")
        partial = getattr(exc, "record", None)
        if isinstance(partial, dict):
            attempted += 1
            errored += 1
            persist_record(output_dir, partial, shape=SCRIPTED_RESEARCH_CAMPAIGN)
    finally:
        restore_handler()
        if output_dir.exists():
            records = rebuild_summaries(
                output_dir, run_id, shape=SCRIPTED_RESEARCH_CAMPAIGN
            )
            rows = [summary_line(record) for record in records]
            print(f"\nWrote {len(records)} record(s) to {output_dir}")
            print(f"Summary: {output_dir / 'summary.md'}")
            print(
                f"{attempted - errored}/{attempted} succeeded, {errored} errored"
                + (
                    f", {unmet_expectations} with unmet expectations"
                    if unmet_expectations
                    else ""
                )
                + (f", {skipped} reused" if skipped else "")
                + f", total ${_campaign_cost(rows):.4f}"
            )

    return _exit_code(
        attempted=attempted,
        errored=errored,
        interrupted=interrupted,
        budget_stopped=False,
    )


__all__ = [
    "BASELINE_PATH",
    "BASELINE_REGEN_COMMAND",
    "FIXED_PIPELINE",
    "HOOK_WRITABLE_KEY",
    "RESEARCH_SCRIPTED_TIER",
    "SCRIPTED_RESEARCH_CAMPAIGN",
    "EpisodeHookBreach",
    "EpisodeHooks",
    "ScriptedOutcomes",
    "ScriptedSurface",
    "ScriptedSurfaceBreach",
    "compute_outcomes",
    "config_problem",
    "main",
    "run_query",
    "script_digest",
    "scripted_dataset_version",
    "scripted_provenance",
    "scripted_surface",
    "summary_line",
    "summary_markdown",
]


if __name__ == "__main__":
    sys.exit(main())
