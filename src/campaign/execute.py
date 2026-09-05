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
import importlib
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
#: and the verifier that only arms C and D reach.
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
    "src.policies.orchestration",
)

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

#: The campaign root's derived summary. Rewritten on every pass, like
#: the ledger, because it is a view of the receipts on disk.
SUMMARY_FILENAME: Final[str] = "campaign-summary.json"

#: The primary outcome this campaign measures at zero cost. 07 §7's D1
#: names claim support as the first optimization target, and ADR 0074's
#: groundedness check answers it without a judge — so a Stage-0 campaign
#: has a real primary metric rather than an absent one.
PRIMARY_METRIC: Final[str] = "supported_claim_precision"

#: Why the loop stopped before running every pending episode.
StopReason = Literal["completed", "campaign_cap_reached", "episode_limit_reached"]


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
    """

    status: CompletionStatus
    reason: RunReason | None
    visited: tuple[str, ...]
    state: Mapping[str, Any]
    workflow_cost_usd: MoneyUsd = "0.000000"
    model_calls: int = 0
    elapsed_seconds: float = 0.0
    detail: str | None = None

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

    def __call__(
        self,
        config: Settings,
        *,
        episode: PlannedEpisode,
        objective: str,
        run_id: str,
        on_node: Callable[[str], None],
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
    """
    modules = [importlib.import_module(name) for name in SETTINGS_CONSUMERS]
    saved = [module.settings for module in modules]
    for module in modules:
        module.settings = config  # type: ignore[attr-defined]
    try:
        yield
    finally:
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
    """
    from src.contracts.research_binding import read_graph_shape

    cache: dict[ArmId, GraphShape] = {}

    def probe(arm_id: ArmId) -> GraphShape:
        if arm_id not in cache:
            with compiled_graph(arm_settings(config, arm_id)) as app:
                cache[arm_id] = read_graph_shape(app)
        return cache[arm_id]

    return probe


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
                Enforced *after* the graph returns, which is the same
                honest bound `CampaignBudget.enforcement` advertises at
                campaign scale: this is an accounting stop, not a
                pre-call reservation.
        """
        self._cap = Decimal(workflow_cost_usd_max)

    def __call__(
        self,
        config: Settings,
        *,
        episode: PlannedEpisode,
        objective: str,
        run_id: str,
        on_node: Callable[[str], None],
    ) -> EpisodeRun:
        from src.graph.state import initial_research_state
        from src.observability.costs import start_cost_tracking

        costs = start_cost_tracking()
        started = time.monotonic()
        visited: list[str] = []
        final: dict[str, Any] = {}
        try:
            with compiled_graph(config) as app, bound_settings(config):
                stream = app.stream(
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
            )

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
            )
        return self._outcome(
            CompletionStatus.SUCCEEDED, None, visited, final, costs, started
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
        )


def _reason_for(exc: BaseException) -> RunReason:
    """Map a raised exception onto RFC 09 §11.2's reason vocabulary.

    Deliberately coarse. A wrong-but-plausible code would be worse than
    `unknown`: the error taxonomy in a campaign report is read as
    evidence about *where* runs break, and this loop only sees the
    exception type, not the stage. The bounded detail string beside it
    carries the type name for whoever reads the record.
    """
    if isinstance(exc, TimeoutError):
        return RunReason.TIMEOUT
    if isinstance(exc, MemoryError | SystemError):
        return RunReason.INFRASTRUCTURE_LOST
    return RunReason.UNKNOWN


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
    """One finished slot, as the loop hands it back."""

    episode: PlannedEpisode
    record: EpisodeRecord
    outcome: EpisodeOutcome
    directory: Path


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
    campaign_cost_usd_max: MoneyUsd
    observed_cost_usd: MoneyUsd
    model_calls: Annotated[int, Field(ge=0)]
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
    outcomes: list[EpisodeOutcome] = list(read_outcomes(directory, plan.ledger))
    runnable = plan.runnable
    pending = [item for item in runnable if not episode_is_complete(directory, item)]
    executed: list[ExecutedEpisode] = []
    stop_reason: StopReason = "completed"
    model_calls = 0

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
        )
        executed.append(finished)
        outcomes.append(finished.outcome)
        model_calls += finished.record.model_calls

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
        campaign_cost_usd_max=cap,
        observed_cost_usd=summary.costs.total_usd,
        model_calls=model_calls,
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
) -> ExecutedEpisode:
    """Seal, open, run, record, score, write. In that order, always.

    The order is RFC 09 §5.1's and it is the only thing this function
    owns. Sealing precedes the trajectory because `run.admitted` binds
    the manifest digest; the trajectory precedes the graph because a side
    effect before the ledger opens is a side effect nothing recorded; and
    `completion.json` is written after every other artifact because it is
    the terminal marker a resume keys on — a crash between the report and
    the receipt leaves the episode pending, which is the truth.
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
    )
    target = episode_directory(directory, episode)

    bridge = _open_trajectory(
        arm_config, sealed=sealed, plan=plan, sink_root=sink_root
    )
    attempt_id = resumed_attempt_id or str(bridge.attempt_id)
    closed = False
    try:
        step = _Step()
        run = runner(
            arm_config,
            episode=episode,
            objective=spec.objective,
            run_id=sealed.manifest.payload.identity.run_id,
            on_node=lambda node: bridge.node_step(node, step=step.next()),
        )
        scores = scorer(episode, run)
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
            "elapsed_sec": round(run.elapsed_seconds, 3),
        },
    )
    return ExecutedEpisode(
        episode=episode, record=record, outcome=outcome, directory=target
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
    artifact store may *refuse* a body (W11-F1), and a digest-only
    reference is a fact worth recording rather than an absence.
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
    "PRIMARY_METRIC",
    "PROJECTION_FILENAME",
    "RECORD_FILENAME",
    "SCORES_FILENAME",
    "SETTINGS_CONSUMERS",
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
    "ExecutedEpisode",
    "GraphEpisodeRunner",
    "StopReason",
    "TaskArmAggregate",
    "TrajectoryRef",
    "aggregate_by_task",
    "arm_graph_probe",
    "bound_settings",
    "compiled_graph",
    "deterministic_scorer",
    "execute_campaign",
    "load_episode_records",
    "run_campaign",
]
