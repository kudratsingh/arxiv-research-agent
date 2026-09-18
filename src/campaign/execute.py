"""Run a planned campaign: the loop W07 declared and did not build.

[`15-stage0-qualification-report.md`](../../docs/agent-engineering/15-stage0-qualification-report.md)
§7.2 named this module's absence as the one remaining code item before a
funded baseline could be requested: `src/campaign/` planned, locked,
declared arms, compiled the matrix, opened the ledger and sealed one
episode's `RunManifest` — and never ran one. Nothing wrote
`completion.json`, so `read_outcomes`, `reconcile` and `summarize` had
only ever seen receipts a test hand-wrote, and `budget_stop_reached` had
no production caller.

This is that loop, and it is deliberately thin. It owns the *order* of
things and nothing else:

1. seal the episode's manifest into its own directory (W05/W03), which
   is where a metered provider without approval fails closed;
2. open W08's durable trajectory, whose first event is `run.admitted`
   carrying the manifest digest — so the ledger cannot begin before the
   configuration is frozen;
3. drive the policy through an injected `EpisodeRunner`;
4. record the run onto the trajectory, score it with a scorer, write the
   episode's artifacts, and write `completion.json` **last**;
5. reconcile the ledger and check the campaign cap between episodes.

Four things are injected rather than reached for, and each has a reason
the planner already wrote down:

- **the graph probe and the runner**, because `build_workflow` reads the
  process-global settings singleton (`planner.py`'s `GraphProbe` note).
  A campaign that ran four arms in one process has to install each arm's
  settings across every module that bound `src.config.settings`, and
  `GraphEpisodeRunner` is the only thing here that does so;
- **the scorer**, because a judge is a model call and this work order
  spends nothing. `deterministic_scorer` computes only the free checks
  and `execute_campaign` refuses to run a campaign that budgets judge
  calls without an explicit scorer, rather than silently scoring less
  than the protocol declared;
- **the approval backend and the credential probe**, so "a metered
  provider is refused before the credential is read" stays a property of
  the call graph.

**Nothing here decides money.** The campaign cap is the manifest's, the
per-episode cap is the manifest's, and `budget_stop_reached` compares
observed spend against a string this module never edits. Raising a cap
is a different campaign id and `resume_campaign` refuses it.

See [ADR 0088](../../docs/decisions/0088-campaign-execution-loop.md).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field

from src.campaign.approval import (
    LocalApprovalRecordBackend,
    NoCredentialProbe,
    SettingsCredentialProbe,
)
from src.campaign.arms import ArmId, arm_settings
from src.campaign.episode import (
    SealedCampaignEpisode,
    assert_not_overwriting,
    episode_directory,
    episode_is_complete,
    seal_campaign_episode,
)
from src.campaign.errors import CampaignError
from src.campaign.ledger import (
    DenominatorLedger,
    EpisodeOutcome,
    EpisodeScoreReceipt,
    LedgerStatus,
    read_outcomes,
    reconcile,
)
from src.campaign.manifest import write_json
from src.campaign.matrix import PlannedEpisode
from src.campaign.planner import (
    CampaignPlan,
    GraphProbe,
    budget_stop_reached,
    load_campaign,
    rebuild_plan,
    resume_episode,
    write_ledger,
)
from src.campaign.summary import CampaignSummary, summarize
from src.config import Settings
from src.contracts.kernel import MoneyUsd, Rfc3339Utc, StrictContractModel
from src.contracts.research_binding import GraphShape, utc_timestamp
from src.contracts.run_manifest import (
    AttemptReceipt,
    CompletionReceipt,
    CompletionStatus,
    ManifestFileStore,
    PolicyExecutionSnapshot,
    RunManifestError,
    RunManifestV1,
    RunReason,
)
from src.contracts.task_spec import TaskSpecV1
from src.observability import get_logger

log = get_logger(__name__)

#: Every module that binds `src.config.settings` on a path the research
#: graph drives. Settings are read *per module*, so a module left out of
#: this list keeps the shipped default and the campaign runs a half
#: overridden arm — which is a silent wrong answer rather than an error.
#: `tests/e2e/conftest.py` documents the same failure and keeps the same
#: kind of list; this one is the research graph's, plus the supervisor
#: and the verifier that only arms C and D reach, plus the provider
#: gateway itself.
#:
#: `src.llm` joined the list in W21. It was absent before, and W20's
#: rehearsal had to report the asymmetry that left behind: the admission
#: probe read the campaign's `Settings` while the gateway read the
#: process-global singleton, so a campaign run under a `model_copy`ed
#: `Settings` carrying a different key or model was admitted against one
#: credential and would have billed against another. Both doors read the
#: same object now. Nothing changes at defaults, where one `.env` sits
#: behind both, and the sentinel refusal stays structural: `_get_client`
#: still raises on `local-preview-disabled` whichever `Settings` the
#: name is bound to.
SETTINGS_CONSUMERS: Final[tuple[str, ...]] = (
    "src.agents.critic",
    "src.agents.planner",
    "src.agents.query_refiner",
    "src.agents.reader",
    "src.agents.search",
    "src.agents.supervisor",
    "src.agents.synthesizer",
    "src.agents.verifier",
    "src.graph.workflow",
    "src.llm",
    "src.policies.orchestration",
)

#: The gateway module, and the name holding its memoised client. Listed
#: apart from `SETTINGS_CONSUMERS` because rebinding `settings` there is
#: necessary but not sufficient: `src.llm` reads the model per call but
#: the credential exactly once, at client construction. An episode that
#: inherited a client built from the process-global key would keep
#: dialling with it however the `settings` name is bound, so
#: `bound_settings` drops the memo on the way in and restores the
#: caller's on the way out.
GATEWAY_MODULE: Final[str] = "src.llm"
GATEWAY_CLIENT_ATTR: Final[str] = "_client"

#: The files one finished episode directory holds beside RFC 09 §5.3's
#: sealed manifest pair. `completion.json` is written last and nothing
#: else keys on it, which is what makes an interrupted episode pending
#: rather than half-complete.
PROJECTION_FILENAME: Final[str] = "policy-runtime-projection.json"
PROJECTION_SIDECAR: Final[str] = "policy-runtime-projection.sha256"
TRAJECTORY_FILENAME: Final[str] = "trajectory.jsonl"
TRAJECTORY_REF_FILENAME: Final[str] = "trajectory-ref.json"
VERIFICATION_FILENAME: Final[str] = "verification.jsonl"
ARTIFACT_INDEX_PATH: Final[str] = "artifacts/index.json"
ATTEMPTS_DIRNAME: Final[str] = "attempts"
RECORD_FILENAME: Final[str] = "episode-record.json"
SCORES_FILENAME: Final[str] = "scores.json"
COMPLETION_FILENAME: Final[str] = "completion.json"

#: The pre-scoring snapshot of what the policy actually produced (EL-05).
#: Written **before** the scorer runs and read by it, so a re-judge later
#: sees byte-identical inputs; read again on resume, so an episode that
#: was paid for and not scored is scored from this file rather than by
#: running the graph a second time.
EPISODE_STATE_FILENAME: Final[str] = "episode-state.json"

#: The campaign root's derived summary. Rewritten on every pass, like
#: the ledger, because it is a view of the receipts on disk.
SUMMARY_FILENAME: Final[str] = "campaign-summary.json"

#: The primary outcome this campaign measures at zero cost. 07 §7's D1
#: names claim support as the first optimization target, and ADR 0074's
#: groundedness check answers it without a judge — so a Stage-0 campaign
#: has a real primary metric rather than an absent one.
PRIMARY_METRIC: Final[str] = "supported_claim_precision"

#: Why the loop stopped before running every pending episode.
#:
#: The first three are the loop's own arithmetic — nothing pending, the
#: aggregate cap reached, the operator's slice finished. The last three
#: are 16 §5's stop rules, which until LE-S were prose in the packet with
#: no implementation: they are about the *instrument* changing under a
#: running campaign rather than about money, and each of them makes the
#: episodes before and after it two different measurements.
StopReason = Literal[
    "completed",
    "campaign_cap_reached",
    "episode_limit_reached",
    "judge_failure_rate",
    "provider_drift",
    "source_drift",
]

#: 16 §5's `judge-failure-rate` rule, in two halves because a rate has no
#: meaning over three episodes. Early: three of the first ten scored
#: episodes losing *any* judged metric is already a broken instrument.
#: Late: more than a tenth of everything scored so far.
#:
#: "Any judged metric", not the primary score, is EL-24's rewording and
#: it is the strictly earlier signal — the primary metric here is
#: deterministic (`supported_claim_precision`), so a judge outage moves
#: no primary score at all and a rule worded on it would never fire.
JUDGE_FAILURE_EARLY_WINDOW: Final[int] = 10
JUDGE_FAILURE_EARLY_TRIGGER: Final[int] = 3
JUDGE_FAILURE_RATE_TRIGGER: Final[float] = 0.10

#: The byte ceiling for one `episode-state.json`. Two mebibytes, a
#: quarter of `MAX_ARTIFACT_BYTES`: the state file is written once per
#: episode and a 300-episode campaign keeps all of them, so the bound
#: that matters is the campaign's disk rather than one file's. A snapshot
#: that does not fit is *reduced* — see `EpisodeStatePolicy` — never
#: truncated mid-JSON and never refused, because an unwritable snapshot
#: must not cost the campaign an episode it already paid for.
MAX_EPISODE_STATE_BYTES: Final[int] = 2 * 1024 * 1024

#: State keys that never reach the snapshot. `messages` is the LangGraph
#: message list — unserializable, unbounded, and a verbatim copy of every
#: prompt and completion the run made. The other three are defensive: no
#: node writes them today, and a node that starts writing full document
#: text should not silently enlarge every episode directory by a
#: megabyte of PDF.
EXCLUDED_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {"messages", "full_texts", "paper_texts", "prior_context"}
)


# ---------------------------------------------------------------------------
# What a runner returns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeRun:
    """What one episode's policy execution produced.

    A dataclass rather than a contract model because `state` is the
    graph's own dictionary — arbitrary, large, and not something this
    package should freeze a schema over. Everything the *ledger* needs is
    a scalar beside it.

    Attributes:
        status: The terminal status the completion receipt will carry.
        reason: The reason code, required for every non-success.
        visited: Node names in execution order, for the trajectory.
        state: The policy's final state. Read for the report, the
            citations and the evidence, and never persisted whole.
        workflow_cost_usd: Spend attributable to the policy under test.
        model_calls: Model calls the policy made. Zero is the claim this
            work order's tests assert on every episode.
        elapsed_seconds: Wall clock for the policy, judges excluded.
        detail: Bounded diagnostic text for the episode record. Never a
            traceback in the manifest (RFC 09 §11.2).
        iterations: One entry per node update that carried a routing
            decision, in execution order. The final state keeps only the
            *last* critic score and the *last* revision target, so a
            two-pass episode and a one-pass episode are indistinguishable
            on it; these are the passes themselves, read off the graph's
            own `updates` stream as it went by (EL-05).
        reader_fallbacks: The abstract-only tally and its reasons. Not on
            the state either — the reader keeps it in a `ContextVar` and
            reports it only to the log stream — so the runner observes
            the reader's own lines for the duration of the episode.
    """

    status: CompletionStatus
    reason: RunReason | None
    visited: tuple[str, ...]
    state: Mapping[str, Any]
    workflow_cost_usd: MoneyUsd = "0.000000"
    model_calls: int = 0
    elapsed_seconds: float = 0.0
    detail: str | None = None
    iterations: tuple[Mapping[str, Any], ...] = ()
    reader_fallbacks: Mapping[str, Any] = field(default_factory=dict)

    @property
    def report(self) -> str:
        """The candidate report, or the empty string when none was made."""
        return str(self.state.get("draft_report") or "")


class EpisodeRunner(Protocol):
    """Whatever actually runs one episode's policy.

    Injected rather than imported so the loop can be driven by the real
    compiled graph, by a fault injector, or by a recorded fixture without
    the loop knowing which. The `config` it receives is already the
    *arm's* settings: resolving the arm is the loop's job, because the
    arm has to agree with the sealed manifest and a runner that chose its
    own settings could disagree with the graph the manifest recorded.
    """

    def prepare_episode(
        self, config: Settings, *, objective: str
    ) -> PolicyExecutionSnapshot | None:
        """Resolve adaptive execution metadata before the manifest seal."""
        ...

    def __call__(
        self,
        config: Settings,
        *,
        episode: PlannedEpisode,
        objective: str,
        run_id: str,
        on_node: Callable[[str], None],
        on_tier: Callable[[PolicyExecutionSnapshot], None] | None = None,
    ) -> EpisodeRun: ...


@dataclass(frozen=True)
class EpisodeScores:
    """One episode's scores, and the single bit the denominator needs.

    `receipt` is the ledger's `EpisodeScoreReceipt` and is written to
    `scores.json` verbatim — the ledger validates that file strictly, so
    the numbers live in the episode record beside it rather than inside
    it.
    """

    receipt: EpisodeScoreReceipt
    primary_metric: str
    primary_score: float | None
    detail: Mapping[str, Any]
    judge_cost_usd: MoneyUsd = "0.000000"
    judge_model_calls: int = 0


class EpisodeScorer(Protocol):
    """Scores one finished episode. May be a judge; here it is not."""

    def __call__(self, episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores: ...


class StateAwareScorer(Protocol):
    """A scorer that wants the persisted snapshot rather than live state.

    The distinction is not cosmetic. `run.state` is the graph's own
    dictionary, in memory, with `messages` still on it; the snapshot is
    the JSON that was written to `episode-state.json` and read back from
    disk. A judge fed the first cannot be re-run later against the same
    inputs, because the second is all that survives the process — so a
    scorer that declares this method is handed the file's own parse and
    a `rejudge` pass weeks later reads exactly what the first pass read.

    Declared as a separate protocol rather than a second parameter on
    `EpisodeScorer` so that every existing scorer — the deterministic
    one, the mock-judge one, the scripted ones in the test suite — keeps
    its signature and needs no change.
    """

    def score_persisted(
        self,
        episode: PlannedEpisode,
        run: EpisodeRun,
        state: Mapping[str, Any],
    ) -> EpisodeScores: ...


# ---------------------------------------------------------------------------
# The default scorer: deterministic, free, and honest about being partial
# ---------------------------------------------------------------------------


def deterministic_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
    """Score an episode with the checks that cost nothing.

    Two of `src/eval/metrics.py`'s five scorers are deterministic and one
    more — ADR 0074's groundedness check — is deterministic and is the
    one 07 §7's D1 actually asks about. The primary outcome here is
    therefore *supported-claim precision*: of the claims the report made,
    the fraction the cited sources support.

    A run that produced no report, or a report with no checkable claims,
    has **no** primary metric. That is recorded as a null metric with a
    reason, which keeps the episode in the denominator and out of the
    numerator — invariant 11's whole point. It is not an error and it is
    not a zero.

    The three LLM-as-judge rubrics are not run and are not approximated.
    `execute_campaign` refuses to use this scorer for a campaign that
    budgeted judge calls, so a protocol that declared judges cannot be
    quietly scored without them.

    Args:
        episode: The slot being scored.
        run: What the policy produced.

    Returns:
        The scores, including the ledger's one bit.
    """
    from src.eval.groundedness import measure_groundedness, paired_outcomes
    from src.eval.metrics import measure_citation_resolution

    report = run.report
    detail: dict[str, Any] = {
        "judges_run": False,
        "judge_rubrics_skipped": ["completeness", "faithfulness", "retrieval_recall"],
    }
    if not report.strip():
        return _null_scores(episode, run, detail, "no report was produced")

    papers = list(run.state.get("papers") or [])
    citations = list(run.state.get("citations") or [])
    evidence = list(run.state.get("evidence") or [])
    detail["citation_resolution_rate"] = dict(
        measure_citation_resolution(report, papers, citations)
    )
    outcomes = paired_outcomes(
        measure_groundedness(report, papers, citations, evidence=evidence)
    )
    detail["claim_count"] = len(outcomes)
    detail["supported_claim_count"] = sum(1 for grounded in outcomes.values() if grounded)
    if not outcomes:
        return _null_scores(
            episode, run, detail, "the report made no claim the check could decide"
        )
    score = detail["supported_claim_count"] / len(outcomes)
    return EpisodeScores(
        receipt=EpisodeScoreReceipt(run_id=episode.run_id, primary_metric_available=True),
        primary_metric=PRIMARY_METRIC,
        primary_score=score,
        detail=detail,
    )


def _null_scores(
    episode: PlannedEpisode, run: EpisodeRun, detail: dict[str, Any], why: str
) -> EpisodeScores:
    """A scored-but-null episode: counted, never a success."""
    del run
    return EpisodeScores(
        receipt=EpisodeScoreReceipt(
            run_id=episode.run_id, primary_metric_available=False, null_reason=why
        ),
        primary_metric=PRIMARY_METRIC,
        primary_score=None,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# The default runner: the real compiled graph, under the arm's settings
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def bound_settings(config: Settings) -> Iterator[None]:
    """Install one configuration across every module the graph reads.

    `from src.config import settings` binds a *name* per module, so there
    is no single place to swap. The list is restored in reverse on the
    way out, including when the body raises, so one arm's settings can
    never leak into the next episode's manifest.

    The gateway's memoised client is dropped for the same reason and
    restored the same way (`GATEWAY_CLIENT_ATTR`): a client built before
    the body was entered was built from somebody else's credential, and
    a rebound `settings` name does not reach inside one.
    """
    modules = [importlib.import_module(name) for name in SETTINGS_CONSUMERS]
    saved = [module.settings for module in modules]
    gateway = importlib.import_module(GATEWAY_MODULE)
    saved_client = getattr(gateway, GATEWAY_CLIENT_ATTR)
    for module in modules:
        module.settings = config  # type: ignore[attr-defined]
    setattr(gateway, GATEWAY_CLIENT_ATTR, None)
    try:
        yield
    finally:
        setattr(gateway, GATEWAY_CLIENT_ATTR, saved_client)
        for module, previous in zip(modules, saved, strict=True):
            module.settings = previous  # type: ignore[attr-defined]


@contextlib.contextmanager
def compiled_graph(config: Settings) -> Iterator[Any]:
    """Compile the real research graph under `config` and release it.

    The checkpointer is closed on the way out for the reason
    `src/eval/runner.py:_close_workflow` gives: one compiled graph per
    episode leaks a connection per episode otherwise, which is inert
    against SQLite at benchmark size and a real drain against Postgres.
    """
    from src.graph.workflow import build_workflow

    with bound_settings(config):
        app = build_workflow(enable_hitl=False)
    try:
        yield app
    finally:
        stack = getattr(app, "_checkpointer_exit_stack", None)
        if stack is not None:
            try:
                stack.close()
            except Exception:  # noqa: BLE001 — teardown must not mask the result
                # `src/eval/runner.py:_close_workflow`'s event, reused
                # rather than duplicated under a campaign-shaped name:
                # it is the same failure, in the same evaluation lane,
                # with the same remedy, and the log contract's registry
                # is a closed set for exactly that reason.
                log.exception("eval_checkpointer_close_failed")


def arm_graph_probe(config: Settings) -> GraphProbe:
    """A `GraphProbe` that compiles this checkout's real graph per arm.

    Memoised per arm: the planner asks once per declared arm and the
    executor asks once per episode, and compiling the same shape 240
    times would pay for nothing. The probe is what turns an `unverified`
    arm declaration into `available` or `capability_missing`, and it is a
    function rather than a call inside the planner because
    `build_workflow` reads the process-global settings singleton.

    `read_deployment_shape`, not `read_graph_shape`: an arm whose
    compute controller is on compiles several shapes and picks between
    them per run (ADR 0085), so what that arm can do is a property of
    the set rather than of whichever member is primary. For every
    controller-off arm the two functions return the same object, so
    A-D's declarations and digests are unchanged (ADR 0091).
    """
    from src.contracts.research_binding import read_deployment_shape

    cache: dict[ArmId, GraphShape] = {}

    def probe(arm_id: ArmId) -> GraphShape:
        if arm_id not in cache:
            with compiled_graph(arm_settings(config, arm_id)) as app:
                cache[arm_id] = read_deployment_shape(app)
        return cache[arm_id]

    return probe


def _tier_workflow(
    config: Settings, app: Any, objective: str
) -> tuple[Any, PolicyExecutionSnapshot | None]:
    """The graph this episode runs, when the arm has a compute router.

    `app` unchanged for every arm whose `compute_controller` is off,
    which is A-D: no alternate shapes are compiled there, the accessor
    returns `None`, and this function is a string comparison and an
    attribute read. That is what keeps this addition invisible to the
    arms ADR 0088's loop already ran.

    Arm E is the arm that needs it (ADR 0091). Its identity *is* the
    router — a deterministic controller selecting among T0, T1 and T2 —
    and a campaign that sealed an arm-E manifest and then ran whichever
    graph happened to be primary would be recording a policy the episode
    did not execute. `src/api/runner.py::_select_tier_workflow` makes
    the same choice on the API path; this is the campaign lane's copy of
    that one decision, kept here rather than shared because the API
    version also binds the tier ContextVar and opens a shadow, neither
    of which a campaign episode has.

    The decision is made from the objective alone, exactly as the API
    path makes it: `decide_tier` is pure and total, so an episode always
    gets a tier and never fails for want of one.
    """
    if config.compute_controller != "deterministic":
        return app, None
    from src.graph.workflow import compute_tier_graphs
    from src.policies.compute import (
        BRANCH_TIER,
        MAX_DECIDABLE_TIER,
        decide_tier,
        extract_features,
    )

    graphs = compute_tier_graphs(app)
    if graphs is None:
        return app, None
    ceiling = BRANCH_TIER if config.orchestration == "on" else MAX_DECIDABLE_TIER
    decision = decide_tier(extract_features(objective), max_tier=ceiling)
    selected = graphs.get(decision.tier, app)
    from src.contracts.research_binding import read_graph_shape

    shape = read_graph_shape(selected)
    execution = PolicyExecutionSnapshot(
        compute_tier=decision.tier,
        eligible_tiers=decision.eligible,
        decision_rule_ids=decision.reasons,
        feature_snapshot_ref=decision.features.digest(),
        tier_budget_ref=(
            f"tier-budget:{decision.tier}"
            f":verifications={decision.limits.max_verifications}"
            f":repairs={decision.limits.max_repairs}"
        ),
        graph_digest=shape.digest,
        shape_nodes=tuple(sorted(shape.nodes)),
    )
    return selected, execution


#: The node updates that carry a *decision* rather than a result, and the
#: keys on each that record it. Read off the graph's `updates` stream
#: because the final state keeps only the last value of each: a run whose
#: critic scored 0.4 and then 0.9 is indistinguishable on the final state
#: from one that scored 0.9 first time, and "how many passes did it take"
#: is exactly what 07 §7's iteration analysis asks.
_DECISION_KEYS: Final[Mapping[str, tuple[str, ...]]] = {
    "critic": ("quality_score", "revision_needed", "revision_target", "iteration"),
    "supervisor": ("next_action", "loop_iterations", "stop_reason"),
    "verify": ("verification_verdict", "verification_reason"),
    "repair": ("repair_action", "repair_count"),
}


def _routing_decision(node: str, update: Any) -> Mapping[str, Any] | None:
    """One node update, reduced to the decision it made, or `None`.

    Deliberately lossy: the critique text, the analyses and the papers
    all reach the snapshot from the final state, and copying them again
    per pass would multiply an episode directory by its iteration count.
    What is *not* recoverable from the final state is the sequence, so
    the sequence is what this keeps.
    """
    keys = _DECISION_KEYS.get(node)
    if keys is None or not isinstance(update, Mapping):
        return None
    decision: dict[str, Any] = {"node": node}
    for key in keys:
        if key in update:
            decision[key] = update[key]
    if len(decision) == 1:
        return None
    # The critique is the one free-text field worth keeping per pass —
    # it is *why* the run went round again — and it is bounded here
    # rather than at the state writer, because the bound has to hold
    # however many passes a run makes.
    critique = str(update.get("critique") or "").strip()
    if node == "critic" and critique:
        decision["critique"] = critique[:1000]
    return decision


class _ReaderFallbackObserver:
    """Collect the reader's abstract-only tally for one episode.

    EL-05 asks for the tally and its reasons in the snapshot, and there
    is no other place to read them from. The reader keeps the tally in a
    `ContextVar` bound inside its own worker threads, empties it when the
    node returns, and reports it to exactly one place: the
    `reader_completed` / `reader_paper_abstract_only` log lines. It is
    not on `ResearchState` and it is not on the trajectory — ADR 0097's
    degradation record carries the *code* (`reader_paper_abstract_only`)
    but not which stage produced no chunks, and "the PDF link was dead"
    and "the ranker returned nothing" are different findings.

    So this is a log-stream reader, attached to the reader's own logger
    for the duration of one episode and detached in `finally`. It adds no
    event name and changes no line; it only observes.

    **It is correct at concurrency 1**, which is the only concurrency the
    campaign loop offers and the one 16 §3.4 recommends for the funded
    baseline. Two episodes running in one process would interleave their
    reader lines into whichever observers were attached, and the fix at
    that point is a `ContextVar` on the reader rather than a second
    handler here.
    """

    #: The reader's logger. Named rather than derived so that moving the
    #: reader's module renames this in one place and the test that
    #: asserts the tally fails loudly rather than silently collecting
    #: nothing.
    LOGGER_NAME: Final[str] = "src.agents.reader"

    def __init__(self) -> None:
        self._papers: list[dict[str, str]] = []
        self._handler = _CollectingHandler(self._papers)

    def __enter__(self) -> _ReaderFallbackObserver:
        logging.getLogger(self.LOGGER_NAME).addHandler(self._handler)
        return self

    def __exit__(self, *exc_info: object) -> Literal[False]:
        logging.getLogger(self.LOGGER_NAME).removeHandler(self._handler)
        return False

    def summary(self) -> dict[str, Any]:
        """The tally, its reasons and the papers behind them."""
        by_reason: dict[str, int] = {}
        for entry in self._papers:
            reason = entry["reason"]
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return {
            "abstract_only_count": len(self._papers),
            "reasons": dict(sorted(by_reason.items())),
            "papers": list(self._papers),
        }


class _CollectingHandler(logging.Handler):
    """Append one record per abstract-only paper to a caller's list.

    A `logging.Handler` rather than a filter, because a filter that
    collected would be a handler pretending not to be one. `emit` cannot
    raise: a logging handler that throws takes the line down with it, and
    a snapshot detail is never worth an episode.
    """

    def __init__(self, sink: list[dict[str, str]]) -> None:
        super().__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() != "reader_paper_abstract_only":
            return
        try:
            self._sink.append(
                {
                    "paper_id": str(getattr(record, "paper_id", "") or ""),
                    "reason": str(getattr(record, "reason", "") or "unknown"),
                }
            )
        except Exception:  # noqa: BLE001 — an observer never fails a run
            self.handleError(record)


class GraphEpisodeRunner:
    """Drive one episode through the compiled research graph.

    The whole runner is four steps — install the arm's settings, compile,
    stream, classify the outcome — and the only interesting one is the
    last. A graph that raises is an `errored` episode with a mapped
    reason code; a graph that finishes with no report is
    `no_report_produced`, which is the failure `src/eval/runner.py`
    already refuses to score as a perfect run; a graph that spends past
    the episode's workflow cap is `budget_stopped` and stays in the
    denominator. Only a report earns `succeeded`.
    """

    def __init__(self, *, workflow_cost_usd_max: MoneyUsd = "0.000000") -> None:
        """
        Args:
            workflow_cost_usd_max: The episode's approved workflow cap.
                Bound as the run's *effective* cap for the duration of
                the episode (EL-17), so `src.llm._check_cost_budget`
                refuses the next call once this episode has reached it
                rather than the deployment-wide `max_cost_usd`. The
                after-the-fact comparison below is kept as the coarser
                second stop, for the spend that never went through the
                gateway.

                The honest bound is unchanged in kind and much smaller
                in size: enforcement is still pre-*call* rather than
                pre-reservation, so an episode can overshoot by whatever
                the calls already in flight cost — at most one reader
                fan-out, since that is the only place this graph issues
                calls in parallel. 16 §3.4 states the campaign-scale
                version of the same bound.
        """
        self._cap = Decimal(workflow_cost_usd_max)

    def prepare_episode(
        self, config: Settings, *, objective: str
    ) -> PolicyExecutionSnapshot | None:
        """Resolve an adaptive tier before the immutable manifest seal."""
        if config.compute_controller != "deterministic":
            return None
        with compiled_graph(config) as app, bound_settings(config):
            _selected, execution = _tier_workflow(config, app, objective)
        return execution

    def __call__(
        self,
        config: Settings,
        *,
        episode: PlannedEpisode,
        objective: str,
        run_id: str,
        on_node: Callable[[str], None],
        on_tier: Callable[[PolicyExecutionSnapshot], None] | None = None,
    ) -> EpisodeRun:
        """Run one episode to a terminal outcome, raising nothing.

        Every exit is an `EpisodeRun`, including an interrupt and an
        unhandled exception, because an episode that failed still owes
        the ledger its status and its spend. `on_node` fires once per
        visited node and `on_tier` at most once, before streaming starts.

        Three things happen around the stream that did not before
        (EL-05, EL-17):

        - the episode's workflow cap is bound as the *effective* cap, so
          the stop happens between calls instead of after the graph;
        - every `updates` payload is read for a routing decision, which
          is how the critic's per-pass score survives into the snapshot
          the final state overwrote;
        - the reader's own log lines are observed, which is the only
          place the abstract-only tally exists.

        All three are released in `finally`, including on the failure
        paths, so nothing here can leak into the next episode.
        """
        from src.graph.state import initial_research_state
        from src.observability.costs import (
            CostBudgetExceeded,
            bind_effective_cost_cap,
            reset_effective_cost_cap,
            start_cost_tracking,
        )

        costs = start_cost_tracking()
        started = time.monotonic()
        visited: list[str] = []
        final: dict[str, Any] = {}
        iterations: list[Mapping[str, Any]] = []
        fallbacks = _ReaderFallbackObserver()
        cap_token = (
            bind_effective_cost_cap(float(self._cap)) if self._cap > 0 else None
        )
        try:
            with compiled_graph(config) as app, bound_settings(config), fallbacks:
                workflow, execution = _tier_workflow(config, app, objective)
                if execution is not None and on_tier is not None:
                    on_tier(execution)
                stream = workflow.stream(
                    initial_research_state(objective, run_id),
                    stream_mode=["updates", "values"],
                )
                for mode, payload in stream:
                    if mode == "values":
                        final = dict(payload)
                        continue
                    for node in payload:
                        if node == "__interrupt__":
                            continue
                        visited.append(node)
                        decision = _routing_decision(node, payload[node])
                        if decision is not None:
                            iterations.append(decision)
                        on_node(node)
        except KeyboardInterrupt:
            # The operator cut in. The episode is cancelled, not failed,
            # and the spend that already happened is still written down.
            return self._outcome(
                CompletionStatus.CANCELLED,
                RunReason.OPERATOR_INTERRUPT,
                visited,
                final,
                costs,
                started,
                detail="operator interrupt",
                iterations=iterations,
                fallbacks=fallbacks.summary(),
            )
        except CostBudgetExceeded as exc:
            # EL-17. The gateway refused the next call because this
            # episode had reached *its* cap, which is a budget stop and
            # not a failure: the partial report the run had already
            # produced is kept (ADR 0051's reason for carrying one on the
            # exception at all), the episode stays in the denominator,
            # and the campaign continues.
            #
            # `final` is the last `values` payload the stream emitted, so
            # a run that got as far as the synthesizer keeps its draft
            # even when the exception carried none.
            if exc.partial_report and not str(final.get("draft_report") or "").strip():
                final["draft_report"] = exc.partial_report
            return self._outcome(
                CompletionStatus.BUDGET_STOPPED,
                RunReason.EPISODE_BUDGET_EXHAUSTED,
                visited,
                final,
                costs,
                started,
                detail=(
                    f"episode cap reached mid-graph: spent {exc.spent_usd:.6f} "
                    f"against {exc.cap_usd:.6f}"
                ),
                iterations=iterations,
                fallbacks=fallbacks.summary(),
            )
        except Exception as exc:  # noqa: BLE001 — an episode failure is data
            # `log.exception`, so the traceback is on the record even
            # though it never reaches the manifest (RFC 09 §11.2 keeps
            # raw tracebacks out of the control plane). The episode
            # record carries a 500-character detail; this is the only
            # place the whole stack survives, and one failed episode out
            # of 240 is otherwise only debuggable by re-running it.
            log.exception(
                "campaign_episode_failed",
                extra={
                    "case_id": episode.case_id,
                    "arm_id": episode.arm_id,
                    "repeat_index": episode.repeat_index,
                    "error_type": type(exc).__name__,
                },
            )
            return self._outcome(
                CompletionStatus.FAILED,
                _reason_for(exc),
                visited,
                final,
                costs,
                started,
                detail=f"{type(exc).__name__}: {exc}"[:500],
                iterations=iterations,
                fallbacks=fallbacks.summary(),
            )
        finally:
            # Released whichever way the body left, and released here
            # rather than in each branch: a cap that survived one
            # episode's exception would silently govern the next one,
            # which is the failure mode the ContextVar exists to prevent.
            if cap_token is not None:
                reset_effective_cost_cap(cap_token)

        spent = Decimal(str(round(float(costs.total_cost_usd), 6)))
        if self._cap > 0 and spent > self._cap:
            return self._outcome(
                CompletionStatus.BUDGET_STOPPED,
                RunReason.EPISODE_BUDGET_EXHAUSTED,
                visited,
                final,
                costs,
                started,
                detail=f"spent {spent} against a cap of {self._cap}",
                iterations=iterations,
                fallbacks=fallbacks.summary(),
            )
        if not str(final.get("draft_report") or "").strip():
            return self._outcome(
                CompletionStatus.FAILED,
                RunReason.NO_REPORT_PRODUCED,
                visited,
                final,
                costs,
                started,
                detail=f"stop_reason={final.get('stop_reason') or 'unknown'}",
                iterations=iterations,
                fallbacks=fallbacks.summary(),
            )
        return self._outcome(
            CompletionStatus.SUCCEEDED,
            None,
            visited,
            final,
            costs,
            started,
            iterations=iterations,
            fallbacks=fallbacks.summary(),
        )

    @staticmethod
    def _outcome(
        status: CompletionStatus,
        reason: RunReason | None,
        visited: Sequence[str],
        final: Mapping[str, Any],
        costs: Any,
        started: float,
        *,
        detail: str | None = None,
        iterations: Sequence[Mapping[str, Any]] = (),
        fallbacks: Mapping[str, Any] | None = None,
    ) -> EpisodeRun:
        return EpisodeRun(
            status=status,
            reason=reason,
            visited=tuple(visited),
            state=dict(final),
            workflow_cost_usd=f"{Decimal(str(round(float(costs.total_cost_usd), 6))):.6f}",
            model_calls=int(costs.call_count),
            elapsed_seconds=time.monotonic() - started,
            detail=detail,
            iterations=tuple(iterations),
            reader_fallbacks=dict(fallbacks or {}),
        )


def _reason_for(exc: BaseException) -> RunReason:
    """Map a raised exception onto RFC 09 §11.2's reason vocabulary.

    Deliberately coarse. A wrong-but-plausible code would be worse than
    `unknown`: the error taxonomy in a campaign report is read as
    evidence about *where* runs break, and this loop only sees the
    exception type, not the stage. The bounded detail string beside it
    carries the type name for whoever reads the record.
    """
    from src.observability.costs import CostBudgetExceeded

    if isinstance(exc, TimeoutError):
        return RunReason.TIMEOUT
    if isinstance(exc, MemoryError | SystemError):
        return RunReason.INFRASTRUCTURE_LOST
    # EL-17. `GraphEpisodeRunner.__call__` catches this one itself, so
    # that the *status* is `budget_stopped` rather than `failed`. The
    # mapping is here as well for the wrapped case: a node that catches
    # the gateway's refusal and re-raises it inside its own error type
    # reaches the generic handler, and `unknown` would file a budget stop
    # under the error taxonomy.
    if isinstance(exc, CostBudgetExceeded):
        return RunReason.EPISODE_BUDGET_EXHAUSTED
    return RunReason.UNKNOWN


# ---------------------------------------------------------------------------
# The episode's state, persisted before anything scores it (EL-05)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeStatePolicy:
    """What `episode-state.json` keeps, and how large it may be.

    The campaign's retention setting rather than the deployment's: an
    evaluation episode and a product run want opposite answers, and the
    graph has no idea which it is in. `execute_campaign` takes one of
    these and the CLI exposes it, so an operator who is about to spend
    money on judged episodes can state — before the run, in the command
    that started it — whether the judges' source text is being kept.

    Attributes:
        retain_reader_chunks: Keep the reader's ranked chunks verbatim.
            On by default because they are what D-3 Option A's
            faithfulness judge reads, and a campaign that discarded them
            cannot be re-judged against the text the report was written
            from — only against the abstracts, which is a different
            measurement wearing the same name. Turning it off keeps the
            chunk's digest, section, paper and score, so the record still
            says a chunk existed and what it was about.
        max_bytes: The per-episode ceiling. Exceeding it reduces the
            snapshot rather than refusing it.
    """

    retain_reader_chunks: bool = True
    max_bytes: int = MAX_EPISODE_STATE_BYTES


#: How far a snapshot was reduced to fit `max_bytes` and pass the ADR 0096
#: screen. Levels, not flags, because the reductions are ordered by what
#: an analysis loses: chunk text first (the judge can fall back to
#: abstracts, with a recorded reason), then the free text around it, then
#: everything but identity and counts.
STATE_RETENTION_LEVELS: Final[tuple[str, ...]] = (
    "full",
    "chunk-text-dropped",
    "free-text-dropped",
    "identity-and-counts-only",
)


def build_episode_state(
    *,
    campaign_id: str,
    episode: PlannedEpisode,
    objective: str,
    run: EpisodeRun,
    sealed_at: str,
    snapshot_at: str,
    corpus_mode: str,
    live_access_allowed: bool,
    source_snapshot_ref: str | None,
    policy: EpisodeStatePolicy,
    level: int = 0,
) -> dict[str, Any]:
    """Build the snapshot an episode is scored from, at one reduction level.

    `EpisodeRun.state` is the graph's own dictionary and ADR 0088's
    docstring says it is "never persisted whole" — which was true, and
    was the reason four of W08's bridge emitters (`source_discovered`,
    `evidence_extracted`, `claim_created`, `plan_created`) had no callers
    and the trajectory carried node *names* and nothing else. A judge run
    a week later had nothing to read, and a judge run now had only what
    happened to still be in memory.

    What is kept is everything a rubric or a later analysis reads: the
    planner's decomposition, the papers and their identifiers, the
    citations the report made, the reader's analyses and ranked chunks,
    the critic's score and routing decision *per pass*, the abstract-only
    tally, and the retrieval window with the ids it returned.

    What is excluded is `messages` — unserializable, unbounded and a
    verbatim copy of every prompt — and any full document text, which
    belongs in the artifact store on its digest and not in 300 copies of
    a JSON file.

    Args:
        campaign_id: The campaign this episode belongs to.
        episode: The slot.
        objective: The query the policy was given.
        run: What the policy produced.
        sealed_at: The manifest's `created_at` — the instant immediately
            before the policy started, and therefore the earliest
            retrieval this episode could have made.
        snapshot_at: Now, which bounds the retrieval from above.
        corpus_mode: The campaign's declared mode, as the sealed
            manifest resolved it.
        live_access_allowed: Whether the manifest permitted live access.
        source_snapshot_ref: The pinned source snapshot, when there is
            one. `None` under a live corpus, which is the point of
            recording it.
        policy: The retention policy.
        level: Index into `STATE_RETENTION_LEVELS`.

    Returns:
        A JSON-safe mapping.
    """
    state = run.state
    keep_chunk_text = policy.retain_reader_chunks and level < 1
    keep_free_text = level < 2
    papers = [dict(paper) for paper in _as_sequence(state.get("papers"))]
    snapshot: dict[str, Any] = {
        "schema_kind": "campaign-episode-state",
        "schema_version": "1.0.0",
        "campaign_id": campaign_id,
        "episode_key": episode.episode_key,
        "run_id": episode.run_id,
        "case_id": episode.case_id,
        "arm_id": episode.arm_id,
        "repeat_index": episode.repeat_index,
        "objective": objective,
        "snapshot_at": snapshot_at,
        "outcome": {
            "status": run.status.value,
            "reason": run.reason.value if run.reason is not None else None,
            "node_route": list(run.visited),
            "workflow_cost_usd": run.workflow_cost_usd,
            "model_calls": run.model_calls,
            "elapsed_seconds": round(run.elapsed_seconds, 6),
            "detail": run.detail,
            # The graph's own word for why it stopped, which is not the
            # campaign's and not the ledger's: a supervisor that ran out
            # of iterations and a synthesizer that returned nothing both
            # reach the loop as one status.
            "stop_reason": str(state.get("stop_reason") or ""),
            "iteration_count": int(state.get("iteration") or 0),
            "loop_iterations": int(state.get("loop_iterations") or 0),
        },
        "retrieval": {
            "corpus_mode": corpus_mode,
            "live_access_allowed": live_access_allowed,
            "source_snapshot_ref": source_snapshot_ref,
            # A window, not an instant, and deliberately so: no search
            # tool in this tree timestamps its own results, so the
            # honest record is the pair of instants the retrieval
            # provably happened between. A live-corpus analysis that
            # needs to know what arXiv held when this episode ran has
            # both ends of the interval and the ids that came back.
            "window_opened_at": sealed_at,
            "window_closed_at": snapshot_at,
            "retrieved_ids": [str(paper.get("id") or "") for paper in papers],
            "retrieved_count": len(papers),
        },
        "plan": {
            "sub_questions": _as_strings(state.get("sub_questions")),
            "search_queries": _as_strings(state.get("search_queries")),
            "tried_search_queries": _as_strings(state.get("tried_search_queries")),
        },
        "iterations": [dict(item) for item in run.iterations] if keep_free_text else [],
        "reader": {
            "abstract_only": dict(run.reader_fallbacks),
            "chunks": _ranked_chunks(state, keep_text=keep_chunk_text),
            "chunk_text_retained": keep_chunk_text,
        },
        "verification": {
            "verified": bool(state.get("verified") or False),
            "verdict": str(state.get("verification_verdict") or ""),
            "reason": str(state.get("verification_reason") or ""),
            "repair_count": int(state.get("repair_count") or 0),
            "repair_action": str(state.get("repair_action") or ""),
        },
        "retention": {
            "level": level,
            "level_name": STATE_RETENTION_LEVELS[level],
            "excluded_keys": sorted(EXCLUDED_STATE_KEYS),
            "chunk_text_retained": keep_chunk_text,
            "max_bytes": policy.max_bytes,
        },
    }
    if level >= 3:
        snapshot["papers"] = [{"id": str(paper.get("id") or "")} for paper in papers]
        snapshot["citations"] = []
        snapshot["paper_analyses"] = []
        snapshot["evidence"] = []
        snapshot["report"] = {"chars": len(run.report), "digest": _digest(run.report)}
        snapshot["reader"]["chunks"] = {}
        return snapshot

    snapshot["papers"] = [_paper(paper, keep_abstract=keep_free_text) for paper in papers]
    snapshot["citations"] = [
        dict(citation) for citation in _as_sequence(state.get("citations"))
    ]
    snapshot["paper_analyses"] = (
        [dict(item) for item in _as_sequence(state.get("paper_analyses"))]
        if keep_free_text
        else [
            {"paper_id": str(item.get("paper_id") or ""), "relevance": item.get("relevance")}
            for item in _as_sequence(state.get("paper_analyses"))
        ]
    )
    snapshot["evidence"] = [
        _evidence(item, keep_text=keep_chunk_text)
        for item in _as_sequence(state.get("evidence"))
    ]
    # The report itself is already an artifact on the trajectory, stored
    # on its digest. The snapshot carries the same digest and the same
    # length, so a scorer reading this file can prove it is scoring the
    # text the trajectory recorded without a second copy of it — and
    # `deterministic_scorer` reads the text off `EpisodeRun`, which is
    # in memory in both the first pass and a recovery.
    snapshot["report"] = {
        "chars": len(run.report),
        "digest": _digest(run.report),
        "text": run.report if keep_free_text else "",
    }
    return snapshot


def _as_sequence(value: Any) -> list[Mapping[str, Any]]:
    """A state field as a list of mappings, whatever it actually is.

    The graph's state is a `TypedDict` that every consumer reads through
    `.get` with a default, so a field can legitimately be absent, `None`
    or — after a node returned something malformed that a coercion let
    through — not a list at all. A snapshot must not be the thing that
    raises on it.
    """
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _as_strings(value: Any) -> list[str]:
    """A state field as a list of strings, under the same tolerance."""
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if isinstance(item, str | int | float)]


def _paper(paper: Mapping[str, Any], *, keep_abstract: bool) -> dict[str, Any]:
    """One retrieved paper, in the fields an analysis or a judge reads.

    `published` is read and recorded as `None` when absent, which it
    always is today: `src/graph/state.py::PaperMetadata` carries no
    publication date, and the only year in the whole state is the one the
    synthesizer's model wrote onto each `Citation`. Recording the absence
    is the point — a metric that indexes by `(author, year)` is reading a
    model-authored field, and this is where that becomes visible.
    """
    abstract = str(paper.get("abstract") or "")
    return {
        "id": str(paper.get("id") or ""),
        "title": str(paper.get("title") or ""),
        "authors": [str(author) for author in paper.get("authors") or []],
        "abstract": abstract if keep_abstract else "",
        "abstract_chars": len(abstract),
        "url": str(paper.get("url") or ""),
        "pdf_url": str(paper.get("pdf_url") or ""),
        "published": paper.get("published"),
    }


def _evidence(claim: Mapping[str, Any], *, keep_text: bool) -> dict[str, Any]:
    """One evidence claim, with its ranked chunk kept or reduced to a digest."""
    source = str(claim.get("source_text") or "")
    return {
        "claim": str(claim.get("claim") or ""),
        "paper_id": str(claim.get("paper_id") or ""),
        "section": str(claim.get("section") or ""),
        "relevance_score": claim.get("relevance_score"),
        "supports_question": str(claim.get("supports_question") or ""),
        "source_text": source if keep_text else "",
        "source_text_chars": len(source),
        "source_text_digest": _digest(source),
    }


def _ranked_chunks(state: Mapping[str, Any], *, keep_text: bool) -> dict[str, Any]:
    """The reader's ranked chunks, grouped by the paper they came from.

    D-3 Option A asks the faithfulness judge to read "abstract + the
    reader's ranked chunks for cited papers", and this is the per-paper
    index that makes that a lookup rather than a scan. The chunks
    themselves are `state["evidence"]` — `EvidenceClaim.source_text` is
    documented as "the ranked chunk verbatim" — so nothing is copied
    from a second source and nothing is re-ranked here.

    Empty under an arm whose evidence store is off, which is a fact about
    the arm: the judge falls back to abstracts and records that it did
    (EL-09), rather than silently scoring a different thing.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in _as_sequence(state.get("evidence")):
        paper_id = str(claim.get("paper_id") or "")
        source = str(claim.get("source_text") or "")
        grouped.setdefault(paper_id, []).append(
            {
                "section": str(claim.get("section") or ""),
                "relevance_score": claim.get("relevance_score"),
                "text": source if keep_text else "",
                "chars": len(source),
                "digest": _digest(source),
            }
        )
    return {key: grouped[key] for key in sorted(grouped)}


def _digest(text: str) -> str:
    """`sha256:<hex>` over one string, in the artifact store's spelling."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_episode_state(
    target: Path,
    *,
    campaign_id: str,
    episode: PlannedEpisode,
    objective: str,
    run: EpisodeRun,
    sealed_at: str,
    corpus_mode: str,
    live_access_allowed: bool,
    source_snapshot_ref: str | None,
    policy: EpisodeStatePolicy,
) -> Mapping[str, Any]:
    """Write the snapshot, reducing it until it fits and passes the screen.

    **Never raises.** EL-03's whole point is that nothing between the
    policy finishing and `completion.json` being written may strand an
    episode that has already been paid for, and a snapshot is the first
    thing in that window. A body that will not fit is reduced; a body the
    ADR 0096 screen refuses is reduced; a snapshot that cannot be written
    at all leaves a stub saying so, and the episode still completes.

    The screen is `src/contracts/artifact_store.py`'s, reached through
    its module-private `_screen_text` rather than reimplemented. Reaching
    for a private name is the lesser evil here: the alternative is a
    second copy of the signed-URL, credential and private-reasoning
    patterns, and two copies of a refusal rule drift. ADR 0096 narrowed
    the screen to *structural* markers precisely so that a retrieved
    paper's abstract stops being refused for its subject matter, which is
    what makes it safe to run a corpus snapshot through it at all.

    Returns:
        The snapshot as it was written, parsed back from the file. The
        caller hands this to a `StateAwareScorer`, so the judge reads the
        bytes on disk and a re-judge later reads the same ones.
    """
    from src.contracts.artifact_store import ArtifactRefused, _screen_text

    snapshot_at = utc_timestamp()
    refusal: str | None = None
    for level in range(len(STATE_RETENTION_LEVELS)):
        try:
            snapshot = build_episode_state(
                campaign_id=campaign_id,
                episode=episode,
                objective=objective,
                run=run,
                sealed_at=sealed_at,
                snapshot_at=snapshot_at,
                corpus_mode=corpus_mode,
                live_access_allowed=live_access_allowed,
                source_snapshot_ref=source_snapshot_ref,
                policy=policy,
                level=level,
            )
            body = json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n"
        except Exception as exc:  # noqa: BLE001 — a snapshot never fails an episode
            refusal = f"{type(exc).__name__}: {exc}"[:200]
            continue
        if len(body.encode("utf-8")) > policy.max_bytes:
            refusal = f"snapshot exceeds {policy.max_bytes} bytes at level {level}"
            continue
        try:
            _screen_text(body)
        except ArtifactRefused as exc:
            refusal = exc.detail[:200]
            continue
        snapshot["retention"]["screen"] = "passed"
        snapshot["retention"]["reduced_because"] = refusal
        body = json.dumps(snapshot, indent=2, sort_keys=True, default=str) + "\n"
        _write_text(target / EPISODE_STATE_FILENAME, body)
        log.info(
            "campaign_episode_state_written",
            extra={
                "campaign_id": campaign_id,
                "case_id": episode.case_id,
                "arm_id": episode.arm_id,
                "repeat_index": episode.repeat_index,
                "retention_level": level,
                "bytes": len(body.encode("utf-8")),
            },
        )
        parsed = json.loads(body)
        assert isinstance(parsed, dict)
        return parsed
    return _write_state_stub(target, campaign_id=campaign_id, episode=episode, why=refusal)


def _write_state_stub(
    target: Path, *, campaign_id: str, episode: PlannedEpisode, why: str | None
) -> Mapping[str, Any]:
    """Record that no snapshot could be written, and why.

    The last resort, and it is a *record* rather than an absence: a
    missing `episode-state.json` and a refused one are different
    findings, and only one of them is a bug in this module.
    """
    stub: dict[str, Any] = {
        "schema_kind": "campaign-episode-state",
        "schema_version": "1.0.0",
        "campaign_id": campaign_id,
        "episode_key": episode.episode_key,
        "run_id": episode.run_id,
        "case_id": episode.case_id,
        "arm_id": episode.arm_id,
        "repeat_index": episode.repeat_index,
        "retention": {
            "level": len(STATE_RETENTION_LEVELS),
            "level_name": "stub",
            "screen": "refused",
            "reduced_because": why or "unknown",
        },
    }
    body = json.dumps(stub, indent=2, sort_keys=True) + "\n"
    with contextlib.suppress(OSError):
        _write_text(target / EPISODE_STATE_FILENAME, body)
    log.warning(
        "campaign_episode_state_written",
        extra={
            "campaign_id": campaign_id,
            "case_id": episode.case_id,
            "arm_id": episode.arm_id,
            "repeat_index": episode.repeat_index,
            "retention_level": len(STATE_RETENTION_LEVELS),
            "bytes": len(body.encode("utf-8")),
        },
    )
    return stub


def read_episode_state(target: Path) -> Mapping[str, Any] | None:
    """The persisted snapshot for one episode directory, or `None`.

    `None` for both "no file" and "unreadable file": a caller here is
    deciding whether it can score without re-running a graph, and a
    corrupt snapshot answers that question the same way a missing one
    does.
    """
    path = target / EPISODE_STATE_FILENAME
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# What one executed episode produced
# ---------------------------------------------------------------------------


class TrajectoryRef(StrictContractModel):
    """Where the durable trajectory lives, and what it hashed to.

    The episode directory keeps its own `trajectory.jsonl` because RFC 09
    §5.3's layout says so, and this ref names W08's durable sink
    (`outputs/trajectories/runs/<run_id>/`) so the two copies can be
    checked against each other rather than diverging silently.
    """

    run_id: str
    durable: bool
    sink_root: str
    run_directory: str
    events_file: str
    head_event_hash: str | None = None
    event_count: Annotated[int, Field(ge=0)] = 0


class EpisodeRecord(StrictContractModel):
    """One episode's row: identity, outcome, cost, scores, digests.

    The campaign's answer to `src/eval/runner.py`'s per-query record, and
    deliberately the same *shape* of object: one JSON file per episode,
    carrying everything an analysis needs without reopening the manifest
    or the trajectory. What it adds is the two digests that make the row
    provable — the sealed manifest's and the compiled task's.
    """

    schema_kind: Literal["campaign-episode-record"] = "campaign-episode-record"
    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: str
    episode_key: str
    replicate_group_id: str
    run_id: str
    attempt_id: str
    case_id: str
    arm_id: ArmId
    repeat_index: Annotated[int, Field(ge=0)]
    design_index: Annotated[int, Field(ge=0)]
    order_in_block: Annotated[int, Field(ge=0)]
    manifest_digest: str
    task_spec_id: str
    task_full_digest: str
    projection_digest: str
    status: CompletionStatus
    reason: RunReason | None = None
    ledger_status: LedgerStatus
    node_route: tuple[str, ...]
    model_calls: Annotated[int, Field(ge=0)]
    workflow_cost_usd: MoneyUsd
    judge_cost_usd: MoneyUsd
    judge_model_calls: Annotated[int, Field(ge=0)]
    elapsed_seconds: float
    primary_metric: str
    primary_score: float | None = None
    primary_metric_available: bool
    scores: Mapping[str, Any]
    trajectory: TrajectoryRef
    detail: str | None = None
    completed_at: Rfc3339Utc


@dataclass(frozen=True)
class ExecutedEpisode:
    """One finished slot, as the loop hands it back.

    The three fields after `directory` are what the between-episode stop
    rules read (EL-15). They are carried on this object rather than
    re-derived from the written record because they come off the *sealed
    manifest*, which is the only place a campaign can see the instrument
    it actually ran against — a record says what the episode produced,
    not which model produced it.
    """

    episode: PlannedEpisode
    record: EpisodeRecord
    outcome: EpisodeOutcome
    directory: Path
    provider_fingerprint: Mapping[str, Any] = field(default_factory=dict)
    corpus_mode: str = ""
    source_snapshot_ref: str | None = None
    judge_metric_failures: tuple[str, ...] = ()
    judges_run: bool = False


def provider_fingerprint(manifest: RunManifestV1) -> dict[str, Any]:
    """The instrument one episode ran against, as its manifest sealed it.

    16 §5's `provider-drift` rule stops a campaign when "model id, API
    version or price table changes mid-campaign", because episodes before
    and after measure two instruments. This is that tuple, read from the
    manifest rather than from live settings: the manifest is immutable
    and is what the episode was admitted against, so a fingerprint taken
    from it cannot disagree with the run it describes.

    **The SDK version is the dependency lock's digest, not a version
    string.** No field on `RunManifestV1` carries a library version —
    `providers.llm.api_protocol_version` is the *wire* protocol
    (`anthropic-messages-2023-06-01`) and is a constant — so the closest
    thing the manifest holds to "the SDK changed under this campaign" is
    `environment.dependency_lock_ref`, which is a digest over
    `requirements-lock.txt` and therefore over the pinned `anthropic`
    version. It is a superset: an unrelated dependency bump moves it too.
    That is the conservative direction for a stop rule — it stops a
    campaign whose environment moved at all — and it is recorded here so
    nobody reads the check as narrower than it is.
    """
    payload = manifest.payload
    return {
        "provider": payload.providers.llm.provider,
        "api_protocol_version": payload.providers.llm.api_protocol_version,
        "routes": {key: value for key, value in sorted(payload.providers.llm.routes.items())},
        "prices_last_verified": payload.providers.pricing.prices_last_verified,
        "price_table_digest": payload.providers.pricing.table_ref.digest,
        "dependency_lock_digest": payload.environment.dependency_lock_ref.digest,
    }


class CampaignRunReport(StrictContractModel):
    """What one execution pass did, and what is still owed.

    `stop_reason` is the operator's answer to "why did this stop": a
    campaign that ran out of pending episodes and a campaign that hit its
    cap look identical in the ledger's *counts* and are entirely
    different findings (07 §9: "stopping is an experiment outcome").
    """

    campaign_id: str
    directory: str
    attempted: Annotated[int, Field(ge=0)]
    completed: Annotated[int, Field(ge=0)]
    skipped_already_complete: Annotated[int, Field(ge=0)]
    pending_after: Annotated[int, Field(ge=0)]
    stop_reason: StopReason
    #: What the stop rule saw, when one of 16 §5's three fired. `None`
    #: for the loop's own three reasons, whose names are already their
    #: whole explanation. A drifted model id is not — an operator has to
    #: be told *which* id moved, or the campaign is unresumable without
    #: re-deriving it.
    stop_detail: str | None = None
    campaign_cost_usd_max: MoneyUsd
    observed_cost_usd: MoneyUsd
    model_calls: Annotated[int, Field(ge=0)]
    judge_model_calls: Annotated[int, Field(ge=0)] = 0
    elapsed_seconds: float
    counts: Mapping[str, int]
    summary: CampaignSummary


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def execute_campaign(
    config: Settings,
    *,
    root: Path,
    plan: CampaignPlan,
    approval_backend: LocalApprovalRecordBackend | None = None,
    graph_probe: GraphProbe | None = None,
    runner: EpisodeRunner | None = None,
    scorer: EpisodeScorer | None = None,
    credential_probe: Any = None,
    sink_root: Path | str | None = None,
    max_episodes: int | None = None,
    state_policy: EpisodeStatePolicy | None = None,
) -> CampaignRunReport:
    """Run every pending episode of a materialized campaign, in order.

    Resume is not a mode: the loop always skips episodes that already
    hold a terminal `completion.json`, so a second call after an
    interrupted first one *is* the resume, under the same lock and the
    same cap because the campaign id is derived from both.

    Args:
        config: The campaign's base settings. Each episode runs under
            `arm_settings(config, arm)`.
        root: Directory holding campaign roots.
        plan: The rebuilt plan for a campaign already on disk.
        approval_backend: Where the external approval record is read.
            Defaults to an empty backend, which admits nothing
            chargeable — the correct default, since an empty backend is
            what a checkout without an owner's record actually has.
        graph_probe: One compiled `GraphShape` per arm. Defaults to
            compiling this checkout's real graph.
        runner: What executes an episode. Defaults to the real graph.
        scorer: What scores one. Defaults to the deterministic, free
            checks; a campaign that budgeted judge calls must pass its
            own, because this one does not make them.
        credential_probe: Called by the admission controller *after* the
            approval verifies. Defaults to a probe that raises on a
            zero-cost campaign (it must never be reached) and to the
            settings probe on a chargeable one.
        sink_root: Root of W08's durable trajectory sink. Defaults to
            `config.contract_event_sink_root`.
        max_episodes: Stop after this many attempts. For an operator
            running a slice, and for a test that needs to interrupt a
            campaign at a known point.
        state_policy: What `episode-state.json` keeps and how large it
            may be. Defaults to keeping the reader's ranked chunks,
            because a judged campaign that discarded them cannot be
            re-judged against the text its reports were written from.

    Returns:
        The pass report, with the reconciled ledger's counts.

    Raises:
        CampaignError: The campaign is not materialized, the approval
            does not cover it, a judge-budgeted campaign has no scorer,
            or an episode cannot seal, resume or be written.
    """
    started = time.monotonic()
    payload = plan.manifest.payload
    directory = root / payload.campaign_id
    if not (directory / "campaign-manifest.json").is_file():
        raise CampaignError(
            f"campaign {payload.campaign_id} is not materialized; plan it first"
        )
    protocol = payload.protocol
    backend = approval_backend if approval_backend is not None else LocalApprovalRecordBackend()

    # Before episode one, not during it: a 240-episode campaign should
    # not discover on the first seal that its approval covers nothing.
    # The receipt it returns is also the freshest one a *resume* can
    # present, which RFC 09 §10.2 requires before credentials or side
    # effects become available again.
    from src.campaign.planner import preflight_approval

    campaign_receipt = preflight_approval(plan, backend)

    if scorer is None and protocol.episode_budget.judge_model_calls_max > 0:
        raise CampaignError(
            "this campaign budgets judge model calls and the default scorer "
            "makes none; pass a scorer rather than scoring less than the "
            "protocol declared"
        )
    score = scorer if scorer is not None else deterministic_scorer
    probe = graph_probe if graph_probe is not None else arm_graph_probe(config)
    execute = (
        runner
        if runner is not None
        else GraphEpisodeRunner(
            workflow_cost_usd_max=protocol.episode_budget.workflow_cost_usd_max
        )
    )
    probe_credential = credential_probe
    if probe_credential is None:
        probe_credential = (
            SettingsCredentialProbe(config) if protocol.chargeable else NoCredentialProbe()
        )
    resolved_sink = (
        Path(sink_root)
        if sink_root is not None
        else Path(str(getattr(config, "contract_event_sink_root", "outputs/trajectories")))
    )

    cap = protocol.campaign_budget.total_cost_usd_max
    retention = state_policy if state_policy is not None else EpisodeStatePolicy()
    outcomes: list[EpisodeOutcome] = list(read_outcomes(directory, plan.ledger))
    runnable = plan.runnable
    pending = [item for item in runnable if not episode_is_complete(directory, item)]
    executed: list[ExecutedEpisode] = []
    stop_reason: StopReason = "completed"
    stop_detail: str | None = None
    rules = _StopRules(campaign_id=payload.campaign_id, corpus_mode=protocol.corpus_mode)
    model_calls = 0
    judge_model_calls = 0

    for index, episode in enumerate(pending):
        if budget_stop_reached(_fold(plan.ledger, outcomes), cap):
            # 16 §5: stop between episodes, publish the partial result
            # with its denominators, and never raise the cap to continue.
            stop_reason = "campaign_cap_reached"
            log.warning(
                "campaign_budget_stop",
                extra={"campaign_id": payload.campaign_id, "cap_usd": cap},
            )
            break
        if max_episodes is not None and index >= max_episodes:
            stop_reason = "episode_limit_reached"
            break
        finished = _run_one_episode(
            config,
            root=root,
            directory=directory,
            plan=plan,
            episode=episode,
            graph=probe(episode.arm_id),
            approval_backend=backend,
            credential_probe=probe_credential,
            runner=execute,
            scorer=score,
            sink_root=resolved_sink,
            approval_receipt=campaign_receipt,
            state_policy=retention,
        )
        executed.append(finished)
        outcomes.append(finished.outcome)
        model_calls += finished.record.model_calls
        judge_model_calls += finished.record.judge_model_calls
        # After the episode is on disk, never before it: a stop rule that
        # fired mid-episode would discard work that was already paid for,
        # and 16 §5's whole shape is "stop *between* episodes, keep the
        # completed ones, publish the partial result with its
        # denominators".
        triggered = rules.observe(finished)
        if triggered is not None:
            stop_reason, stop_detail = triggered
            log.warning(
                "campaign_stop_rule_triggered",
                extra={
                    "campaign_id": payload.campaign_id,
                    "rule": stop_reason,
                    "detail": stop_detail,
                },
            )
            break

    reconciled = _fold(plan.ledger, outcomes)
    write_ledger(directory, reconciled)
    summary = summarize(plan.manifest, reconciled)
    write_json(directory / SUMMARY_FILENAME, summary.model_dump(mode="json"))
    counts = {
        status.value: reconciled.report.counts.get(status.value, 0)
        for status in LedgerStatus
    }
    return CampaignRunReport(
        campaign_id=payload.campaign_id,
        directory=str(directory),
        attempted=len(executed),
        completed=sum(
            1
            for item in executed
            if item.outcome.ledger_status is LedgerStatus.COMPLETED
        ),
        skipped_already_complete=len(runnable) - len(pending),
        pending_after=sum(
            1 for item in runnable if not episode_is_complete(directory, item)
        ),
        stop_reason=stop_reason,
        stop_detail=stop_detail,
        campaign_cost_usd_max=cap,
        observed_cost_usd=summary.costs.total_usd,
        model_calls=model_calls,
        judge_model_calls=judge_model_calls,
        elapsed_seconds=time.monotonic() - started,
        counts=counts,
        summary=summary,
    )


def run_campaign(
    config: Settings,
    *,
    root: Path,
    campaign_id: str,
    **kwargs: Any,
) -> CampaignRunReport:
    """Load a materialized campaign from disk and run its pending episodes.

    The CLI's whole `run` verb. Loading rather than re-planning is what
    makes a resume land on the identical matrix: the manifest's arms,
    case order, repeats and seed are what `rebuild_plan` re-derives the
    episode keys from, so a resumed pass writes into the directories the
    first pass opened.
    """
    directory = root / campaign_id
    if not directory.is_dir():
        raise CampaignError(f"no campaign directory for {campaign_id}")
    manifest, specs = load_campaign(directory)
    return execute_campaign(config, root=root, plan=rebuild_plan(manifest, specs), **kwargs)


def _fold(ledger: DenominatorLedger, outcomes: Sequence[EpisodeOutcome]) -> DenominatorLedger:
    return reconcile(ledger, outcomes, reconciled_at=utc_timestamp())


class _StopRules:
    """16 §5's three non-monetary stop rules, checked between episodes.

    Until LE-S these were a table in the approval packet: `provider-drift`
    and `judge-failure-rate` had no implementation anywhere in the tree,
    and `source-drift` was enforced only at seal time — which catches a
    campaign that *starts* on the wrong corpus and not one that changes
    under a running campaign, which is the case the rule is about.

    Each rule is stateful across episodes and each stops the campaign the
    same way the cap does: between episodes, with everything already
    completed kept and counted. Nothing here raises; a triggered rule is
    a `CampaignRunReport.stop_reason`, because 07 §9 is explicit that
    stopping is an experiment outcome rather than an error.
    """

    def __init__(self, *, campaign_id: str, corpus_mode: str) -> None:
        self._campaign_id = campaign_id
        self._declared_corpus_mode = corpus_mode
        self._first_fingerprint: Mapping[str, Any] | None = None
        self._first_source: tuple[str, str | None] | None = None
        self._judged = 0
        self._judge_failures = 0

    def observe(self, finished: ExecutedEpisode) -> tuple[StopReason, str] | None:
        """Fold one finished episode in; return a stop reason if one fires."""
        drift = self._provider_drift(finished)
        if drift is not None:
            return ("provider_drift", drift)
        source = self._source_drift(finished)
        if source is not None:
            return ("source_drift", source)
        return self._judge_failure_rate(finished)

    def _provider_drift(self, finished: ExecutedEpisode) -> str | None:
        """Compare this episode's instrument with the campaign's first."""
        current = finished.provider_fingerprint
        if not current:
            return None
        if self._first_fingerprint is None:
            self._first_fingerprint = current
            return None
        moved = [
            f"{key}: {self._first_fingerprint.get(key)!r} -> {current.get(key)!r}"
            for key in sorted(set(self._first_fingerprint) | set(current))
            if self._first_fingerprint.get(key) != current.get(key)
        ]
        if not moved:
            return None
        return (
            "the provider this campaign measures against moved after the "
            f"first episode ({'; '.join(moved)}). Episodes before and after "
            "measure two instruments; resume as a new campaign against a new "
            "lock."
        )

    def _source_drift(self, finished: ExecutedEpisode) -> str | None:
        """Compare this episode's resolved corpus with the declared one.

        EL-24 generalized the packet's wording, which pinned the rule to
        `snapshot`: the rule is that the resolved mode equals the
        *declared* mode, whichever that is, so a live campaign is covered
        by the same sentence rather than by its inverse.

        Two comparisons, because the packet's row names two failures.

        The first restates `episode.py::_assert_corpus_mode` — live
        resolves live, everything else does not — as a between-episodes
        check. It is deliberately a *belt*: the seal already refuses a
        mismatch, so this can only fire if a later seal stops refusing,
        and a campaign that discovered that on episode 40 should stop
        rather than aggregate 39 controlled episodes with one live one.
        Note the resolution, which 16 §8.3 found and this check has to
        agree with: a campaign declaring `snapshot` resolves to
        `CorpusMode.SUPPLIED`, not `SNAPSHOT`, because `source_scope`
        maps mock data to a supplied corpus.

        The second is the packet's "or the source snapshot digest moves",
        and it is not vacuous: the ref is pinned per episode at seal
        time, so a snapshot that was re-cut mid-campaign moves it while
        the *mode* stays exactly where it was.

        For a live campaign neither check can see what arXiv actually
        held; the per-episode retrieval window and ids in
        `episode-state.json` are what a later analysis reads for that.
        """
        resolved = finished.corpus_mode
        if not resolved:
            return None
        if (resolved == "live") != (self._declared_corpus_mode == "live"):
            return (
                f"episode {finished.episode.output_path} resolved corpus mode "
                f"{resolved!r} against a campaign that declared "
                f"{self._declared_corpus_mode!r}"
            )
        current = (resolved, finished.source_snapshot_ref)
        if self._first_source is None:
            self._first_source = current
            return None
        if current == self._first_source:
            return None
        return (
            "the source boundary moved after the first episode: "
            f"{self._first_source!r} -> {current!r}. Episodes before and "
            "after read two corpora."
        )

    def _judge_failure_rate(self, finished: ExecutedEpisode) -> tuple[StopReason, str] | None:
        """Stop when the judges are failing often enough to hollow the scores.

        Armed only for episodes a judge actually scored: a campaign
        running the free deterministic scorer has no judge to fail, and a
        rule that counted its episodes would divide by the wrong
        denominator.
        """
        if not finished.judges_run:
            return None
        self._judged += 1
        if finished.judge_metric_failures:
            self._judge_failures += 1
        if self._judged <= JUDGE_FAILURE_EARLY_WINDOW:
            if self._judge_failures < JUDGE_FAILURE_EARLY_TRIGGER:
                return None
        elif self._judge_failures <= self._judged * JUDGE_FAILURE_RATE_TRIGGER:
            return None
        return (
            "judge_failure_rate",
            (
                f"{self._judge_failures} of {self._judged} judged episode(s) "
                "lost at least one judged metric. A campaign whose scores are "
                "mostly absent is not a variance estimate; stop and report the "
                "null-score denominator."
            ),
        )


# ---------------------------------------------------------------------------
# One episode
# ---------------------------------------------------------------------------


def _run_one_episode(
    config: Settings,
    *,
    root: Path,
    directory: Path,
    plan: CampaignPlan,
    episode: PlannedEpisode,
    graph: GraphShape,
    approval_backend: LocalApprovalRecordBackend,
    credential_probe: Any,
    runner: EpisodeRunner,
    scorer: EpisodeScorer,
    sink_root: Path,
    approval_receipt: Any = None,
    state_policy: EpisodeStatePolicy | None = None,
) -> ExecutedEpisode:
    """Seal, open, run, **persist**, score, record, write. In that order.

    The order is RFC 09 §5.1's and it is the only thing this function
    owns. Sealing precedes the trajectory because `run.admitted` binds
    the manifest digest; the trajectory precedes the graph because a side
    effect before the ledger opens is a side effect nothing recorded; and
    `completion.json` is written after every other artifact because it is
    the terminal marker a resume keys on — a crash between the report and
    the receipt leaves the episode pending, which is the truth.

    LE-S moves one step and adds one (EL-03). **Persisting the state now
    precedes scoring**, and scoring can no longer strand the episode:
    before this, `scores = scorer(episode, run)` sat inside a `try` whose
    `finally` closed the trajectory and nothing else, so a judge that
    raised left a directory with a sealed manifest, a paid-for run, and
    no `completion.json` — and the next resume ran the whole graph again,
    paying twice for one measurement. Now the snapshot is on disk first,
    the scorer is called through a guard that turns any exception into a
    null metric with a reason, and an episode that *was* interrupted
    between those two points is recovered from its snapshot on the next
    pass rather than re-run.
    """
    # Emitted before the seal rather than before the run: an episode
    # that hangs never reaches its `completed` line, and this is the only
    # line that says which of 240 slots it hung in.
    log.info(
        "campaign_episode_started",
        extra={
            "campaign_id": plan.campaign_id,
            "case_id": episode.case_id,
            "arm_id": episode.arm_id,
            "repeat_index": episode.repeat_index,
        },
    )
    assert_not_overwriting(directory, episode)
    spec = plan.task_spec_for(episode.case_id)
    arm_config = arm_settings(config, episode.arm_id)
    prepare_episode = getattr(runner, "prepare_episode", None)
    policy_execution = (
        prepare_episode(arm_config, objective=spec.objective)
        if callable(prepare_episode)
        else None
    )
    sealed, resumed_attempt_id = _seal_or_resume(
        config,
        root=root,
        directory=directory,
        plan=plan,
        episode=episode,
        spec=spec,
        graph=graph,
        approval_backend=approval_backend,
        credential_probe=credential_probe,
        approval_receipt=approval_receipt,
        policy_execution=policy_execution,
    )
    target = episode_directory(directory, episode)
    retention = state_policy if state_policy is not None else EpisodeStatePolicy()
    sources = sealed.manifest.payload.sources
    recovered = _recoverable_run(target, episode)

    bridge = _open_trajectory(
        arm_config, sealed=sealed, plan=plan, sink_root=sink_root
    )
    attempt_id = resumed_attempt_id or str(bridge.attempt_id)
    closed = False
    try:
        step = _Step()
        if recovered is not None:
            # EL-03's recovery half. The graph is *not* run: this episode
            # already produced its outcome and its snapshot, and the only
            # thing missing is the scoring pass that failed after them.
            # The node route is replayed onto the trajectory because
            # those nodes were visited — the trajectory records what the
            # policy did, and a recovery that dropped them would make the
            # re-opened run look like an episode that never planned.
            run = recovered
            for node in run.visited:
                bridge.node_step(node, step=step.next())
            log.warning(
                "campaign_episode_recovered",
                extra={
                    "campaign_id": plan.campaign_id,
                    "case_id": episode.case_id,
                    "arm_id": episode.arm_id,
                    "repeat_index": episode.repeat_index,
                    "status": run.status.value,
                    "workflow_cost_usd": run.workflow_cost_usd,
                },
            )
        else:
            # ADR 0097: around the policy and nothing else. A degradation
            # recorded by the scorer or by `_record_terminal` would be the
            # harness degrading, not the arm, and ADR 0050's boundary is the
            # one this scope is drawn on.
            with _degradation_scope(bridge):
                if policy_execution is None:
                    run = runner(
                        arm_config,
                        episode=episode,
                        objective=spec.objective,
                        run_id=sealed.manifest.payload.identity.run_id,
                        on_node=lambda node: bridge.node_step(node, step=step.next()),
                    )
                else:
                    run = runner(
                        arm_config,
                        episode=episode,
                        objective=spec.objective,
                        run_id=sealed.manifest.payload.identity.run_id,
                        on_node=lambda node: bridge.node_step(node, step=step.next()),
                        on_tier=lambda execution: _record_tier_selection(
                            bridge, sealed=sealed, execution=execution
                        ),
                    )
        # Persisted *before* the scorer, which is the whole of EL-05's
        # ordering claim: the judge reads the file, so a re-judge weeks
        # later reads the same bytes, and a scorer that dies leaves the
        # episode scoreable rather than unrepeatable.
        persisted = write_episode_state(
            target,
            campaign_id=plan.campaign_id,
            episode=episode,
            objective=spec.objective,
            run=run,
            sealed_at=sealed.manifest.payload.identity.created_at,
            corpus_mode=sources.input_corpus_mode.value,
            live_access_allowed=sources.live_access_allowed,
            source_snapshot_ref=(
                sources.source_snapshot_ref.digest
                if sources.source_snapshot_ref is not None
                else None
            ),
            policy=retention,
        )
        scores = _score_safely(
            scorer, episode=episode, run=run, state=persisted, campaign_id=plan.campaign_id
        )
        _record_terminal(bridge, run)
        bridge.reconcile(Decimal(run.workflow_cost_usd))
        bridge.close()
        closed = True
    finally:
        # Only on the path that did *not* close. A harness failure — the
        # scorer raising, the bridge refusing an event — leaves a
        # trajectory with no terminal event, and its head hash still has
        # to be written so the partial ledger stays checkable. The flag
        # is what stops the happy path paying for a second chain
        # verification and a second `trajectory_chain_verified` line on
        # every one of 240 episodes.
        if not closed:
            with contextlib.suppress(Exception):
                bridge.durable_store.close_run(bridge.run_id)

    record = _write_episode_artifacts(
        target,
        plan=plan,
        episode=episode,
        sealed=sealed,
        attempt_id=attempt_id,
        run=run,
        scores=scores,
        bridge=bridge,
        sink_root=sink_root,
    )
    outcome = EpisodeOutcome(
        episode_key=episode.episode_key,
        run_id=episode.run_id,
        status=run.status,
        reason=run.reason,
        workflow_cost_usd=run.workflow_cost_usd,
        judge_cost_usd=scores.judge_cost_usd,
        primary_metric_available=scores.receipt.primary_metric_available,
    )
    log.info(
        "campaign_episode_completed",
        extra={
            "campaign_id": plan.campaign_id,
            "case_id": episode.case_id,
            "arm_id": episode.arm_id,
            "repeat_index": episode.repeat_index,
            "status": run.status.value,
            # Both, because they answer different questions: `status` is
            # the terminal receipt's, and `ledger_status` is the
            # denominator bucket — a succeeded episode whose primary
            # metric is missing is `succeeded` and `null_metric`.
            "ledger_status": outcome.ledger_status.value,
            "call_count": run.model_calls,
            "workflow_cost_usd": run.workflow_cost_usd,
            "judge_cost_usd": scores.judge_cost_usd,
            "judge_model_calls": scores.judge_model_calls,
            "elapsed_sec": round(run.elapsed_seconds, 3),
        },
    )
    return ExecutedEpisode(
        episode=episode,
        record=record,
        outcome=outcome,
        directory=target,
        provider_fingerprint=provider_fingerprint(sealed.manifest),
        corpus_mode=sources.input_corpus_mode.value,
        source_snapshot_ref=(
            sources.source_snapshot_ref.digest
            if sources.source_snapshot_ref is not None
            else None
        ),
        judge_metric_failures=_judge_failures_of(scores),
        judges_run=bool(scores.detail.get("judges_run")),
    )


def _score_safely(
    scorer: EpisodeScorer,
    *,
    episode: PlannedEpisode,
    run: EpisodeRun,
    state: Mapping[str, Any],
    campaign_id: str,
) -> EpisodeScores:
    """Score one episode, converting any failure into a null metric.

    EL-03. A scorer is a *measurement* of an episode that has already
    happened, and the episode's money is already spent by the time it
    runs: there is no failure mode in which raising is the better answer.
    A judge that 429s past its retries, a metric module that trips over a
    malformed citation, a scorer an operator wrote themselves — all of
    them land here as `primary_metric_available=false` with a reason, the
    episode keeps its place in the denominator, and `completion.json` is
    still written.

    The scorer is offered the *persisted* snapshot when it declares
    `score_persisted` (`StateAwareScorer`), so the judges read the file
    rather than the live state and a re-judge is reproducible. Scorers
    that do not — the deterministic one, the mock-judge one — are called
    exactly as before.
    """
    try:
        persisted = getattr(scorer, "score_persisted", None)
        if callable(persisted):
            scores = persisted(episode, run, state)
            assert isinstance(scores, EpisodeScores)
            return scores
        return scorer(episode, run)
    except Exception as exc:  # noqa: BLE001 — a scorer never strands an episode
        log.exception(
            "campaign_episode_scoring_failed",
            extra={
                "campaign_id": campaign_id,
                "case_id": episode.case_id,
                "arm_id": episode.arm_id,
                "repeat_index": episode.repeat_index,
                "error_type": type(exc).__name__,
            },
        )
        return EpisodeScores(
            receipt=EpisodeScoreReceipt(
                run_id=episode.run_id,
                primary_metric_available=False,
                null_reason=f"the scorer raised {type(exc).__name__}"[:200],
            ),
            primary_metric=PRIMARY_METRIC,
            primary_score=None,
            detail={
                "judges_run": False,
                "scoring_error": f"{type(exc).__name__}: {exc}"[:500],
                "scored_from_persisted_state": bool(state),
            },
        )


def _judge_failures_of(scores: EpisodeScores) -> tuple[str, ...]:
    """The judged metrics this episode lost, as the scorer reported them."""
    failures = scores.detail.get("judge_metric_failures")
    if not isinstance(failures, list | tuple):
        return ()
    return tuple(str(item) for item in failures)


def _recoverable_run(target: Path, episode: PlannedEpisode) -> EpisodeRun | None:
    """Rebuild a finished-but-unscored episode from its own snapshot.

    Reached only for a slot with no terminal `completion.json` — a
    completed one never gets here, `assert_not_overwriting` refuses it.
    So the snapshot's presence means exactly one thing: the policy ran,
    the state was persisted, and the pass died between that write and the
    receipt. Re-running the graph would pay for the same measurement a
    second time, and under a live corpus would not even measure the same
    thing, because the corpus moved.

    `None` — meaning "run the graph" — in three cases, each of them a
    snapshot that cannot stand in for the run: no file, a stub (the
    snapshot itself was refused), or a reduction level that dropped the
    report text. The last is the interesting one: a scorer handed a
    snapshot whose report was reduced away would score a successful
    episode as having produced nothing, and a wrong score is worse than a
    repeated run.
    """
    snapshot = read_episode_state(target)
    if snapshot is None:
        return None
    outcome = snapshot.get("outcome")
    report = snapshot.get("report")
    if not isinstance(outcome, Mapping) or not isinstance(report, Mapping):
        return None
    text = str(report.get("text") or "")
    if not text and int(report.get("chars") or 0) > 0:
        return None
    try:
        status = CompletionStatus(str(outcome.get("status")))
        raw_reason = outcome.get("reason")
        reason = RunReason(str(raw_reason)) if raw_reason else None
    except ValueError:
        return None
    state: dict[str, Any] = {
        "draft_report": text,
        "papers": list(snapshot.get("papers") or []),
        "citations": list(snapshot.get("citations") or []),
        "paper_analyses": list(snapshot.get("paper_analyses") or []),
        "evidence": list(snapshot.get("evidence") or []),
        "sub_questions": list((snapshot.get("plan") or {}).get("sub_questions") or []),
        "search_queries": list((snapshot.get("plan") or {}).get("search_queries") or []),
        "stop_reason": str(outcome.get("stop_reason") or ""),
        "iteration": int(outcome.get("iteration_count") or 0),
    }
    detail = str(outcome.get("detail") or "") or None
    return EpisodeRun(
        status=status,
        reason=reason,
        visited=tuple(str(node) for node in outcome.get("node_route") or ()),
        state=state,
        workflow_cost_usd=str(outcome.get("workflow_cost_usd") or "0.000000"),
        model_calls=int(outcome.get("model_calls") or 0),
        elapsed_seconds=float(outcome.get("elapsed_seconds") or 0.0),
        # Marked on the record, because an episode scored from a snapshot
        # and an episode scored from a live graph are the same *number*
        # and not the same *provenance*, and an analyst reading a campaign
        # with recoveries in it should be able to see which is which.
        detail=(f"{detail}; " if detail else "") + "scored from persisted state",
        iterations=tuple(
            item for item in snapshot.get("iterations") or () if isinstance(item, Mapping)
        ),
        reader_fallbacks=dict((snapshot.get("reader") or {}).get("abstract_only") or {}),
    )


class _Step:
    """A monotone step counter for the trajectory's node actions."""

    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


def _seal_or_resume(
    config: Settings,
    *,
    root: Path,
    directory: Path,
    plan: CampaignPlan,
    episode: PlannedEpisode,
    spec: TaskSpecV1,
    graph: GraphShape,
    approval_backend: LocalApprovalRecordBackend,
    credential_probe: Any,
    approval_receipt: Any = None,
    policy_execution: PolicyExecutionSnapshot | None = None,
) -> tuple[SealedCampaignEpisode, str | None]:
    """Seal a fresh episode, or append a new attempt to an interrupted one.

    RFC 09 §11.3's distinction, made structural. A directory with no
    manifest is a first attempt. A directory with a manifest and no
    terminal receipt is an *interrupted* run: the run id does not change,
    a new attempt id is minted, and `validate_resume` re-checks every
    precondition including a fresh approval verification.

    The re-seal on the resume path uses the stored manifest's own
    `created_at`, so an identical configuration produces an identical
    digest. A digest that moved means the checkout, the settings, the
    prompts or the registry changed under an interrupted run, and that is
    `manifest_mismatch` — refused, because a run that cannot prove what
    it ran is not data.
    """
    target = episode_directory(directory, episode)
    store = ManifestFileStore()
    existing: RunManifestV1 | None = None
    if (target / store.filename).is_file():
        try:
            existing = store.load(target)
        except RunManifestError as exc:
            raise CampaignError(f"episode manifest is unreadable: {exc.detail}") from exc

    sealed = seal_campaign_episode(
        config,
        campaign=plan.manifest,
        episode=episode,
        task_spec=spec,
        graph=graph,
        approval_backend=approval_backend,
        credential_probe=credential_probe,
        sealed_at=(existing.payload.identity.created_at if existing is not None else None),
        policy_execution=policy_execution,
    )
    if existing is None:
        try:
            store.seal(target, sealed.manifest)
        except RunManifestError as exc:
            raise CampaignError(f"episode manifest is already sealed: {exc.detail}") from exc
        return sealed, None

    if existing.integrity.payload_sha256 != sealed.manifest_digest:
        raise CampaignError(
            f"episode {episode.output_path} was sealed under a different "
            "configuration; a run that cannot prove what it ran is not data. "
            "Rerun it as a new run with lineage."
        )
    return sealed, str(
        resume_episode(
            root,
            campaign_id=plan.campaign_id,
            episode=episode,
            approval_receipt=approval_receipt or sealed.approval_receipt,
        )
    )


def _open_trajectory(
    arm_config: Settings,
    *,
    sealed: SealedCampaignEpisode,
    plan: CampaignPlan,
    sink_root: Path,
) -> Any:
    """Open W08's durable trajectory for an already-sealed episode.

    The campaign's sealed episode is adapted into W05's `SealedEpisode`
    rather than resealed: the manifest, the projection and the compiled
    task are already the campaign's, and building a second one here would
    put two manifests behind one run id.
    """
    from src.contracts import runtime_bridge as rb
    from src.contracts.research_binding import SealedEpisode

    episode = SealedEpisode(
        origin="research_eval",
        task_spec=sealed.task_spec,
        task_ref=sealed.episode.task_ref,
        receipt=sealed.receipt,
        manifest=sealed.manifest,
        projection=sealed.projection,
        shape=sealed.shape,
        policy=sealed.policy,
    )
    return rb.start_research_run(
        arm_config,
        episode=episode,
        runtime_run_id=sealed.manifest.payload.identity.run_id,
        principal_key_id=f"synthetic:{plan.campaign_id}",
        cost_ceiling_usd=plan.manifest.payload.protocol.episode_budget.workflow_cost_usd_max,
        sink_root=sink_root,
    )


def _degradation_scope(bridge: Any) -> Any:
    """Bind this episode's degradation observer, or a scope that does nothing.

    The import is local for the reason every other `runtime_bridge`
    import in this module is local: the campaign package must not put
    the contract package on the import graph of a process that only
    plans a matrix.
    """
    from src.contracts import runtime_bridge as rb

    return rb.observe_degradations(bridge)


def _record_tier_selection(
    bridge: Any,
    *,
    sealed: SealedCampaignEpisode,
    execution: PolicyExecutionSnapshot,
) -> None:
    """Verify and emit the tier fact sealed before execution began."""
    if sealed.policy_execution is None:
        raise CampaignError("runner selected a compute tier absent from the sealed manifest")
    if execution != sealed.policy_execution:
        raise CampaignError("runtime compute-tier decision differs from the sealed execution")
    bridge.compute_tier_selected(
        tier=execution.compute_tier,
        eligible_tiers=execution.eligible_tiers,
        reason_codes=execution.decision_rule_ids,
        feature_snapshot_ref=execution.feature_snapshot_ref,
        tier_budget_ref=execution.tier_budget_ref,
    )


def _record_terminal(bridge: Any, run: EpisodeRun) -> None:
    """Close the trajectory on the terminal event the outcome names.

    Four outcomes, four terminals, and none of them is "record a report
    and hope". A failed episode that produced partial text keeps it as an
    artifact (ADR 0051's reason), and a cancelled one records the request
    before the acknowledgement, as the contract orders them.
    """
    from src.contracts.trajectory import ArtifactRole

    if run.status is CompletionStatus.SUCCEEDED:
        artifact = bridge.record_candidate(run.report)
        candidate_id = bridge._candidate_id  # noqa: SLF001 — the bridge's own id
        verification_ids = tuple(
            event.event_id
            for event in bridge.events()
            if event.event_type == "verification.completed"
        )
        bridge.finalize(
            candidate_id=candidate_id,
            artifact=artifact.model_copy(update={"role": ArtifactRole.CANDIDATE_REPORT}),
            selection_basis="single_candidate",
            verification_event_ids=verification_ids,
        )
        return
    if run.status is CompletionStatus.CANCELLED:
        bridge.cancel(
            reason_code="user_requested",
            stage=run.visited[-1] if run.visited else "admission",
            partial_report=run.report,
        )
        return
    if run.status is CompletionStatus.BUDGET_STOPPED:
        bridge.budget_stop(
            spent_usd=float(run.workflow_cost_usd), partial_report=run.report
        )
        return
    bridge.fail(
        error_code="internal_unexpected",
        stage=run.visited[-1] if run.visited else "admission",
        partial_report=run.report,
    )


# ---------------------------------------------------------------------------
# The episode's files
# ---------------------------------------------------------------------------


def _write_episode_artifacts(
    target: Path,
    *,
    plan: CampaignPlan,
    episode: PlannedEpisode,
    sealed: SealedCampaignEpisode,
    attempt_id: str,
    run: EpisodeRun,
    scores: EpisodeScores,
    bridge: Any,
    sink_root: Path,
) -> EpisodeRecord:
    """Write RFC 09 §5.3's episode files, terminal receipt last.

    `completion.json` is the last write and it is the only file resume
    reads to decide whether the slot is done. Everything before it is
    idempotent enough to be rewritten by a later attempt; the receipt is
    not, so it goes last and a crash anywhere before it leaves an episode
    that is pending rather than falsely complete.
    """
    from src.contracts import runtime_bridge as rb

    completed_at = utc_timestamp()
    projection = sealed.projection
    projection_digest = projection.integrity.payload_sha256
    _write_text(
        target / PROJECTION_FILENAME, projection.model_dump_json() + "\n"
    )
    _write_text(
        target / PROJECTION_SIDECAR,
        f"{projection_digest}  {PROJECTION_FILENAME}\n",
    )

    jsonl = bridge.durable_jsonl() or bridge.export_jsonl()
    _write_text(target / TRAJECTORY_FILENAME, jsonl)
    sink = bridge.durable_store.sink
    head = sink.head(bridge.run_id) if sink is not None else None
    # `durable` is measured, not assumed: `capture_permitted` can refuse
    # the sink (D8's gate, or capture switched off), and an episode whose
    # trajectory lives only in this process's memory must say so rather
    # than name a directory nothing wrote.
    trajectory = TrajectoryRef(
        run_id=bridge.run_id,
        durable=sink is not None,
        sink_root=str(sink_root) if sink is not None else "",
        run_directory=(
            str(Path(sink_root) / rb.SINK_RUN_DIRECTORY / bridge.run_id)
            if sink is not None
            else ""
        ),
        events_file=rb.SINK_EVENTS_FILE if sink is not None else "",
        head_event_hash=(str(head["head_event_hash"]) if head else None),
        event_count=int(head["event_count"]) if head else len(bridge.events()),
    )
    write_json(target / TRAJECTORY_REF_FILENAME, trajectory.model_dump(mode="json"))

    events = bridge.events()
    _write_text(
        target / VERIFICATION_FILENAME,
        "".join(
            event.model_dump_json() + "\n"
            for event in events
            if event.event_type.startswith("verification.")
        ),
    )
    _write_artifact_index(target, events=events, bridge=bridge)

    write_json(
        target / ATTEMPTS_DIRNAME / f"{attempt_id}.json",
        _attempt_receipt(
            episode=episode,
            sealed=sealed,
            attempt_id=attempt_id,
            run=run,
            scores=scores,
            ended_at=completed_at,
        ).model_dump(mode="json"),
    )

    outcome = EpisodeOutcome(
        episode_key=episode.episode_key,
        run_id=episode.run_id,
        status=run.status,
        reason=run.reason,
        workflow_cost_usd=run.workflow_cost_usd,
        judge_cost_usd=scores.judge_cost_usd,
        primary_metric_available=scores.receipt.primary_metric_available,
    )
    record = EpisodeRecord(
        campaign_id=plan.campaign_id,
        episode_key=episode.episode_key,
        replicate_group_id=episode.replicate_group_id,
        run_id=episode.run_id,
        attempt_id=attempt_id,
        case_id=episode.case_id,
        arm_id=episode.arm_id,
        repeat_index=episode.repeat_index,
        design_index=episode.design_index,
        order_in_block=episode.order_in_block,
        manifest_digest=sealed.manifest_digest,
        task_spec_id=sealed.task_spec.task_spec_id,
        task_full_digest=episode.task_ref.full_digest,
        projection_digest=projection_digest,
        status=run.status,
        reason=run.reason,
        ledger_status=outcome.ledger_status,
        node_route=run.visited,
        model_calls=run.model_calls,
        workflow_cost_usd=run.workflow_cost_usd,
        judge_cost_usd=scores.judge_cost_usd,
        judge_model_calls=scores.judge_model_calls,
        elapsed_seconds=round(run.elapsed_seconds, 6),
        primary_metric=scores.primary_metric,
        primary_score=scores.primary_score,
        primary_metric_available=scores.receipt.primary_metric_available,
        scores=dict(scores.detail),
        trajectory=trajectory,
        detail=run.detail,
        completed_at=completed_at,
    )
    write_json(target / RECORD_FILENAME, record.model_dump(mode="json"))
    write_json(target / SCORES_FILENAME, scores.receipt.model_dump(mode="json"))

    receipt = CompletionReceipt(
        run_id=episode.run_id,
        manifest_digest=sealed.manifest_digest,
        status=run.status,
        reason=run.reason,
        completed_at=completed_at,
        final_artifact_refs=(),
        accumulated_workflow_cost_usd=run.workflow_cost_usd,
        accumulated_judge_cost_usd=scores.judge_cost_usd,
    )
    write_json(target / COMPLETION_FILENAME, receipt.model_dump(mode="json"))
    return record


def _attempt_receipt(
    *,
    episode: PlannedEpisode,
    sealed: SealedCampaignEpisode,
    attempt_id: str,
    run: EpisodeRun,
    scores: EpisodeScores,
    ended_at: Rfc3339Utc,
) -> AttemptReceipt:
    """This attempt's bounded receipt, in `AttemptReceipt`'s own vocabulary.

    That vocabulary has three members — `running`, `interrupted`,
    `failed` — and deliberately no `succeeded`: success is a property of
    the *run*, recorded once on the completion receipt, and an attempt
    that produced it is simply an attempt that never closed badly. So a
    successful attempt is left `running` rather than being closed with an
    invented outcome, and a cancellation is `interrupted` rather than
    `failed`, because an operator who stopped a run did not observe the
    policy fail.
    """
    common: dict[str, Any] = {
        "run_id": episode.run_id,
        "attempt_id": attempt_id,
        "manifest_digest": sealed.manifest_digest,
        "started_at": sealed.manifest.payload.identity.created_at,
        "accumulated_workflow_cost_usd": run.workflow_cost_usd,
        "accumulated_judge_cost_usd": scores.judge_cost_usd,
    }
    if run.status is CompletionStatus.SUCCEEDED:
        return AttemptReceipt(outcome="running", **common)
    outcome: Literal["interrupted", "failed"] = (
        "interrupted" if run.status is CompletionStatus.CANCELLED else "failed"
    )
    return AttemptReceipt(
        outcome=outcome,
        ended_at=ended_at,
        reason=run.reason or RunReason.UNKNOWN,
        **common,
    )


def _write_artifact_index(target: Path, *, events: Sequence[Any], bridge: Any) -> None:
    """Index the run's artifacts rather than copying their bytes.

    W08's store is content-addressed and shared across the campaign, so
    duplicating a briefing into every episode directory would store the
    same bytes 240 times and give a reader two places to disagree. The
    index names each artifact, its digest, its content address and
    whether the store actually holds the bytes — the last because the
    artifact store still refuses a body carrying a *structural* reasoning
    marker (ADR 0096, which narrowed the topical refusal W11-F1 found to
    that one case), and a digest-only reference is a fact worth recording
    rather than an absence.
    """
    seen: dict[str, dict[str, Any]] = {}
    store = getattr(bridge, "artifacts", None)
    for event in events:
        for ref in event.artifact_refs:
            entry = seen.setdefault(
                ref.artifact_id,
                {
                    "artifact_id": ref.artifact_id,
                    "digest": ref.digest,
                    "media_type": ref.media_type,
                    "byte_length": ref.byte_length,
                    "storage_uri": ref.storage_uri,
                    "roles": [],
                    "stored": bool(store is not None and store.contains(ref.artifact_id)),
                },
            )
            role = str(ref.role)
            if role not in entry["roles"]:
                entry["roles"].append(role)
    write_json(
        target / ARTIFACT_INDEX_PATH,
        {
            "schema_kind": "campaign-episode-artifact-index",
            "schema_version": "1.0.0",
            "store_root": str(getattr(store, "root", "")) if store is not None else "",
            "artifacts": [seen[key] for key in sorted(seen)],
        },
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Repeats, aggregated by task
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskArmAggregate:
    """One (case, arm) condition's repeats, folded into one row.

    The unit a paired contrast is run over. 07 §5 asks for at least three
    independent repeats per query and arm, and `src/eval/regression_diff.py`
    already says why they are aggregated before anything is compared: a
    campaign with three repeats has three rows per task and diffing them
    row-by-row compares `r1` to `r1`, which is an arbitrary pairing.

    Every number here comes from `src/eval/stats.py`. Nothing in this
    package computes an interval or a reliability statistic of its own.
    """

    case_id: str
    arm_id: str
    repeats: int
    scored: int
    successes: int
    mean_primary_score: float | None
    pass_hat_k: float | None
    interval: tuple[float, float] | None
    null_metric: int
    errored: int
    fields: Mapping[str, Any] = field(default_factory=dict)


def aggregate_by_task(
    records: Sequence[EpisodeRecord], *, threshold: float = 1.0
) -> tuple[TaskArmAggregate, ...]:
    """Fold each (case, arm) condition's repeats into one row.

    Args:
        records: Episode records from one campaign, in any order.
        threshold: The primary score at which a repeat counts as a
            success for `pass^k`. Defaults to 1.0 — every claim the
            report made was supported — because a partially supported
            report is not a success at the thing D1 optimizes.

    Returns:
        One row per (case, arm), ordered by case then arm.

    Raises:
        CampaignError: Two records claim the same episode key, which
            would double-count a repeat.
    """
    from src.eval.stats import pass_hat_k, wilson_interval

    keys = [record.episode_key for record in records]
    if len(set(keys)) != len(keys):
        raise CampaignError("two records claim the same episode; repeats would double count")

    grouped: dict[tuple[str, str], list[EpisodeRecord]] = {}
    for record in records:
        grouped.setdefault((record.case_id, record.arm_id), []).append(record)

    rows: list[TaskArmAggregate] = []
    for (case_id, arm_id), group in sorted(grouped.items()):
        scored = [item for item in group if item.primary_score is not None]
        successes = sum(1 for item in scored if (item.primary_score or 0.0) >= threshold)
        mean = (
            sum(item.primary_score or 0.0 for item in scored) / len(scored)
            if scored
            else None
        )
        rows.append(
            TaskArmAggregate(
                case_id=case_id,
                arm_id=arm_id,
                repeats=len(group),
                scored=len(scored),
                successes=successes,
                mean_primary_score=mean,
                pass_hat_k=(
                    pass_hat_k(successes, len(scored), len(scored)) if scored else None
                ),
                interval=(
                    _bounds(wilson_interval(successes, len(scored))) if scored else None
                ),
                null_metric=sum(
                    1 for item in group if item.ledger_status is LedgerStatus.NULL_METRIC
                ),
                errored=sum(
                    1
                    for item in group
                    if item.ledger_status
                    in (
                        LedgerStatus.ERRORED,
                        LedgerStatus.TIMED_OUT,
                        LedgerStatus.CANCELLED,
                        LedgerStatus.BUDGET_STOPPED,
                    )
                ),
            )
        )
    return tuple(rows)


def _bounds(interval: Any) -> tuple[float, float]:
    """`stats.Interval` as a plain pair, without restating its arithmetic."""
    return (float(interval.low), float(interval.high))


def load_episode_records(directory: Path, plan: CampaignPlan) -> tuple[EpisodeRecord, ...]:
    """Read every episode record a campaign directory holds.

    Raises:
        CampaignError: A record exists and is invalid. A corrupt record
            is not a missing one, and guessing would put a wrong number
            into an aggregate.
    """
    records: list[EpisodeRecord] = []
    for episode in plan.runnable:
        path = episode_directory(directory, episode) / RECORD_FILENAME
        if not path.is_file():
            continue
        try:
            records.append(EpisodeRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise CampaignError(
                f"episode record for {episode.output_path} is invalid: {exc}"
            ) from exc
    return tuple(records)


__all__ = [
    "ARTIFACT_INDEX_PATH",
    "ATTEMPTS_DIRNAME",
    "COMPLETION_FILENAME",
    "EPISODE_STATE_FILENAME",
    "GATEWAY_CLIENT_ATTR",
    "GATEWAY_MODULE",
    "JUDGE_FAILURE_EARLY_TRIGGER",
    "JUDGE_FAILURE_EARLY_WINDOW",
    "JUDGE_FAILURE_RATE_TRIGGER",
    "MAX_EPISODE_STATE_BYTES",
    "PRIMARY_METRIC",
    "PROJECTION_FILENAME",
    "RECORD_FILENAME",
    "SCORES_FILENAME",
    "SETTINGS_CONSUMERS",
    "STATE_RETENTION_LEVELS",
    "SUMMARY_FILENAME",
    "TRAJECTORY_FILENAME",
    "TRAJECTORY_REF_FILENAME",
    "VERIFICATION_FILENAME",
    "CampaignRunReport",
    "EpisodeRecord",
    "EpisodeRun",
    "EpisodeRunner",
    "EpisodeScorer",
    "EpisodeScores",
    "EpisodeStatePolicy",
    "ExecutedEpisode",
    "GraphEpisodeRunner",
    "StateAwareScorer",
    "StopReason",
    "TaskArmAggregate",
    "TrajectoryRef",
    "aggregate_by_task",
    "arm_graph_probe",
    "bound_settings",
    "build_episode_state",
    "compiled_graph",
    "deterministic_scorer",
    "execute_campaign",
    "load_episode_records",
    "provider_fingerprint",
    "read_episode_state",
    "run_campaign",
    "write_episode_state",
]
