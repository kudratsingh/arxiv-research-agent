"""Walk the funded path to the credential boundary and stop there.

[`16-w12-approval-packet-draft.md`](../../docs/agent-engineering/16-w12-approval-packet-draft.md)
§8 lists what a funded arm-A baseline still needs. Until this module
existed, the only way to find out whether *anything else* was missing
was to fund one and watch it fail — which is the one experiment the
packet is not allowed to run. `rehearse` is the other way: it drives the
same call graph `run` drives, under
`ANTHROPIC_API_KEY=local-preview-disabled`, and stops at exactly the
first door a credential opens.

The four steps before that door are the real ones, not stand-ins:

1. **Load** the materialized campaign — the sealed manifest, the
   registry lock and the compiled task set, checked against the refs the
   manifest pinned (`load_campaign` refuses a substituted spec).
2. **Verify approval** through `preflight_approval`, which is the same
   call `execute_campaign` makes before its first episode.
3. **Open the ledger** by reconciling the campaign's expected
   denominators against the receipts on disk — in memory, so the
   rehearsal does not rewrite the ledger it is reading.
4. **Seal an episode manifest** for the first pending slot, against a
   graph compiled from this checkout, through `seal_next_episode` — the
   same function `_run_one_episode` calls. It seals into a temporary
   root that is deleted on the way out, so a rehearsal leaves the
   campaign directory byte for byte as it found it, and says so.

Then the boundary, in the order the funded path reaches it:
`SettingsCredentialProbe` (which refuses a key that cannot pay, because
possession is not authorization) and `src.llm`'s client constructor
(which refuses the sentinel before the SDK can build a transport). Both
refusals are reported, neither is raised, and no episode runs.

**The two doors read the same settings, and the rehearsal shows it
rather than asserting it.** Both read the campaign's `Settings`: the
admission probe is handed the object, and the gateway is rebound to it
by `bound_settings`, which this module enters around the client probe
exactly as `_run_one_episode` does around an episode. Until W21 that was
not true — `src.llm` was absent from `execute_campaign`'s
`SETTINGS_CONSUMERS`, so the gateway read the process-global singleton
and a campaign carrying a `model_copy`ed `Settings` with a different
credential was admitted against one key and would have dialled with
another. In a normal deployment both descend from one `.env` and the
distinction was invisible, which is exactly why an operator should learn
it from a rehearsal rather than from a bill.

**A rehearsal never spends and never dials.** It makes no model call, no
judge call and no network call of any kind; `tests/test_campaign_rehearsal.py`
proves the last one against the harness's socket guard rather than
against a promise. And it refuses to start at all under a credential
that *could* pay unless an approval id is named, because a rehearsal
that quietly became a run under a real key would be the exact failure
12 §3.10 is about.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import Field, model_validator

from src.campaign.approval import (
    DISABLED_API_KEY,
    LocalApprovalRecordBackend,
    SettingsCredentialProbe,
)
from src.campaign.errors import CampaignError
from src.campaign.ledger import DenominatorLedger, read_outcomes, reconcile
from src.campaign.matrix import PlannedEpisode
from src.campaign.planner import (
    CampaignPlan,
    GraphProbe,
    load_campaign,
    preflight_approval,
    rebuild_plan,
    seal_next_episode,
    status_counts,
)
from src.config import Settings
from src.contracts.kernel import StrictContractModel, sha256_digest
from src.contracts.research_binding import utc_timestamp
from src.observability import get_logger

log = get_logger(__name__)

#: The steps a rehearsal walks, in the order the funded path reaches
#: them. Named as a closed tuple so a step that is added without being
#: reported fails `tests/test_campaign_rehearsal.py` rather than
#: silently shortening the walk.
REHEARSAL_STEPS: Final[tuple[str, ...]] = (
    "campaign-loaded",
    "approval-verified",
    "ledger-opened",
    "episode-manifest-sealed",
    "provider-credential-probed",
    "provider-client-constructed",
)

#: Where the funded path stops today. A rehearsal that got further would
#: be reporting a different string, which is the point of recording it.
CREDENTIAL_BOUNDARY: Final[str] = "provider-credential-probed"

StepOutcome: TypeAlias = Literal["passed", "refused"]
PreconditionId: TypeAlias = Literal[
    "approval-record", "priced-model-ids", "measured-token-counts"
]

#: What a caller supplies to stand in for `src.llm`'s client
#: constructor. Injected rather than imported at the call site so a test
#: can assert the boundary was reached without owning the SDK.
ClientProbe: TypeAlias = Callable[[], object]


class RehearsalStep(StrictContractModel):
    """One step of the walk and what it proved.

    Attributes:
        step: One of `REHEARSAL_STEPS`.
        outcome: `passed` when the funded path would have continued,
            `refused` when it stopped here.
        detail: What actually happened, in words an operator can act on.
    """

    step: str
    outcome: StepOutcome
    detail: str

    @model_validator(mode="after")
    def the_step_is_one_of_the_declared_ones(self) -> RehearsalStep:
        if self.step not in REHEARSAL_STEPS:
            raise ValueError(f"{self.step} is not one of the declared rehearsal steps")
        return self


class Precondition(StrictContractModel):
    """One of 16 §8's remaining preconditions, and whether it is owed.

    `owed` is *derived* on every rehearsal rather than transcribed from
    the packet: an approval record that appears in the backend, or a
    price table that is re-verified, closes its own line without anybody
    editing this file.
    """

    precondition: PreconditionId
    owed: bool
    owner: Literal["owner", "mechanical"]
    detail: str


class RehearsalReport(StrictContractModel):
    """What one rehearsal walked, where it stopped, and what is still owed."""

    schema_kind: Literal["campaign-rehearsal"] = "campaign-rehearsal"
    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: str
    directory: str
    chargeable: bool
    stopped_at: str
    steps: tuple[RehearsalStep, ...]
    preconditions: tuple[Precondition, ...]
    episodes_run: Literal[0] = 0
    model_calls: Literal[0] = 0
    network_calls: Literal[0] = 0
    artifacts_written: tuple[str, ...] = ()
    pending_episodes: Annotated[int, Field(ge=0)]
    message: str

    @model_validator(mode="after")
    def the_walk_is_complete(self) -> RehearsalReport:
        walked = tuple(step.step for step in self.steps)
        if walked != REHEARSAL_STEPS:
            raise ValueError(
                "a rehearsal reports every declared step in order; this one "
                f"reported {walked}"
            )
        if self.stopped_at not in REHEARSAL_STEPS:
            raise ValueError(f"{self.stopped_at} is not a rehearsal step")
        return self

    @property
    def owed(self) -> tuple[PreconditionId, ...]:
        """The preconditions this rehearsal found still outstanding."""
        return tuple(item.precondition for item in self.preconditions if item.owed)


def rehearse_campaign(
    config: Settings,
    *,
    root: Path,
    campaign_id: str,
    approval_backend: LocalApprovalRecordBackend | None = None,
    approval_id: str | None = None,
    graph_probe: GraphProbe | None = None,
    client_probe: ClientProbe | None = None,
    today: date | None = None,
) -> RehearsalReport:
    """Walk a materialized campaign's funded path and stop at the credential.

    Args:
        config: The campaign's base settings.
        root: Directory holding campaign roots.
        campaign_id: The campaign to rehearse.
        approval_backend: Where an external approval record would be
            read. Defaults to an empty backend, which is what a checkout
            without an owner's record actually has.
        approval_id: The approval record the operator claims covers a
            funded run. Required before a rehearsal will start under a
            credential that could pay; checked for presence in the
            backend when given.
        graph_probe: One compiled `GraphShape` per arm. Defaults to
            compiling this checkout's real graph, which is what makes
            the seal step evidence rather than a mock.
        client_probe: What stands in for `src.llm`'s client constructor.
            Defaults to that constructor.
        today: The date the price table's staleness is measured against.
            Supplied rather than read from a clock so a rehearsal is
            reproducible; defaults to the wall clock's UTC date.

    Returns:
        The report.

    Raises:
        CampaignError: The campaign is not materialized, the credential
            could pay and no approval id was named, the approval does not
            cover the plan, or the rehearsal left something behind.
    """
    directory = root / campaign_id
    if not (directory / "campaign-manifest.json").is_file():
        raise CampaignError(
            f"campaign {campaign_id} is not materialized; plan it first"
        )
    _refuse_a_credential_that_could_pay(config, approval_id=approval_id)
    backend = (
        approval_backend if approval_backend is not None else LocalApprovalRecordBackend()
    )
    before = _directory_census(directory)
    log.info("campaign_rehearsal_started", extra={"campaign_id": campaign_id})

    steps: list[RehearsalStep] = []
    manifest, specs = load_campaign(directory)
    plan = rebuild_plan(manifest, specs)
    payload = plan.manifest.payload
    steps.append(
        RehearsalStep(
            step="campaign-loaded",
            outcome="passed",
            detail=(
                f"sealed manifest {manifest.integrity.payload_sha256} over lock "
                f"{payload.lock_digest}, {len(specs)} compiled TaskSpecs, each "
                "matching the ref the manifest pinned"
            ),
        )
    )
    steps.append(_approval_step(plan, backend, approval_id=approval_id))
    ledger, pending = _ledger_step(directory, plan, steps)
    steps.append(
        _seal_step(
            config,
            plan=plan,
            pending=pending,
            approval_backend=backend,
            graph_probe=graph_probe,
        )
    )
    steps.append(_credential_step(config))
    steps.append(_client_step(config, client_probe))

    stopped_at = next(
        (step.step for step in steps if step.outcome == "refused"),
        REHEARSAL_STEPS[-1],
    )
    written = tuple(sorted(_directory_census(directory) - before))
    if written:
        raise CampaignError(
            "a rehearsal must leave no artifacts behind; these appeared in the "
            f"campaign directory: {', '.join(written)}"
        )
    preconditions = _preconditions(
        payload.protocol.approval_id,
        backend=backend,
        ledger_counts=status_counts(ledger),
        config=config,
        today=today or datetime.now(UTC).date(),
    )
    report = RehearsalReport(
        campaign_id=campaign_id,
        directory=str(directory),
        chargeable=payload.protocol.chargeable,
        stopped_at=stopped_at,
        steps=tuple(steps),
        preconditions=preconditions,
        pending_episodes=len(pending),
        message=_message(stopped_at, preconditions),
    )
    log.info(
        "campaign_rehearsal_stopped",
        extra={
            "campaign_id": campaign_id,
            "stop_reason": stopped_at,
            "preconditions_owed": list(report.owed),
        },
    )
    return report


def _refuse_a_credential_that_could_pay(
    config: Settings, *, approval_id: str | None
) -> None:
    """Refuse to rehearse under a key that could pay and no approval named.

    The sentinel is fine — refusing it would make the zero-spend checkout
    the one place a rehearsal is impossible. An empty key is fine too:
    nothing can be charged to it. What is refused is the middle case, a
    credential that would work, with nothing recording that anyone
    authorized using it. 12 §3.10 in executable form.
    """
    secret = config.anthropic_api_key
    key = secret.get_secret_value() if secret is not None else ""
    if not key or key == DISABLED_API_KEY:
        return
    if approval_id is None:
        raise CampaignError(
            "rehearsal refused: ANTHROPIC_API_KEY is a credential that could "
            "pay and no --approval-id was named. Rehearse under "
            "ANTHROPIC_API_KEY=local-preview-disabled, or name the approval "
            "record that authorizes this campaign; possessing a key is never "
            "authorization to spend"
        )


def _approval_step(
    plan: CampaignPlan, backend: LocalApprovalRecordBackend, *, approval_id: str | None
) -> RehearsalStep:
    """Run `execute_campaign`'s own pre-flight and report what it proved."""
    protocol = plan.manifest.payload.protocol
    receipt = preflight_approval(plan, backend)
    if receipt is not None:
        return RehearsalStep(
            step="approval-verified",
            outcome="passed",
            detail=(
                f"approval {protocol.approval_id} covers this campaign's "
                f"{protocol.campaign_budget.total_cost_usd_max} aggregate cap; "
                f"receipt {sha256_digest(receipt)}"
            ),
        )
    claimed = ""
    if approval_id is not None:
        held = approval_id in backend.record_ids
        claimed = (
            f" The named record {approval_id} is "
            f"{'present in' if held else 'absent from'} the backend; whether it "
            "covers a funded run is verified against that run's own campaign "
            "id, which a raised cap moves."
        )
    return RehearsalStep(
        step="approval-verified",
        outcome="passed",
        detail=(
            "this campaign declares a "
            f"{protocol.campaign_budget.total_cost_usd_max} aggregate cap, so "
            "assert_approval_covers required no record and read no credential. "
            "A funded twin of this protocol is chargeable and refuses here "
            f"without one; the backend holds {len(backend.record_ids)} "
            f"record(s).{claimed}"
        ),
    )


def _ledger_step(
    directory: Path, plan: CampaignPlan, steps: list[RehearsalStep]
) -> tuple[DenominatorLedger, tuple[PlannedEpisode, ...]]:
    """Reconcile the denominators in memory and report the counts.

    In memory on purpose: `campaign_status` rewrites `campaign-ledger.json`
    from the receipts on disk, which is correct for a status verb and is
    an artifact a rehearsal is not allowed to write.
    """
    from src.campaign.episode import episode_is_complete

    outcomes = read_outcomes(directory, plan.ledger)
    ledger = reconcile(plan.ledger, outcomes, reconciled_at=utc_timestamp())
    pending = tuple(
        episode
        for episode in plan.runnable
        if not episode_is_complete(directory, episode)
    )
    steps.append(
        RehearsalStep(
            step="ledger-opened",
            outcome="passed",
            detail=(
                f"{ledger.report.expected} expected episodes, analysis "
                f"denominator {ledger.report.analysis_denominator}, "
                f"{len(pending)} pending; reconciled in memory, the ledger on "
                "disk was not rewritten"
            ),
        )
    )
    return ledger, pending


class _DeferredCredentialProbe:
    """Note that the funded path reached the credential, and let it pass.

    On a chargeable campaign the admission controller reads a credential
    *inside* the seal, after the approval verifies. A probe that refused
    there would make the seal step report the credential's refusal and
    hide whether the seal itself works — and a rehearsal wants both
    facts. So this one records that the door was reached and returns;
    `_credential_step`, which runs immediately after, is where the real
    probe runs and the refusal is reported.

    It cannot turn a rehearsal into a run: nothing after the seal in
    this module executes an episode, and the two provider steps that
    follow use the production probes.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


def _seal_step(
    config: Settings,
    *,
    plan: CampaignPlan,
    pending: Sequence[PlannedEpisode],
    approval_backend: LocalApprovalRecordBackend,
    graph_probe: GraphProbe | None,
) -> RehearsalStep:
    """Seal the next pending episode into a temporary root, then discard it.

    The graph is this checkout's real compiled one, so the arm the seal
    proves is the arm a funded run would execute; a seal against a mock
    would prove nothing about the funded path.

    A refusal here is *reported*, not raised. The whole value of a
    rehearsal is the full picture — an operator who learns that the seal
    refuses and does not also learn that the credential refuses has to
    run it twice — and a refusal at this step is the interesting case:
    it means the funded path is blocked by something that is not the
    owner's three lines.
    """
    if not pending:
        return RehearsalStep(
            step="episode-manifest-sealed",
            outcome="passed",
            detail=(
                "no episode is pending, so there was nothing to seal; every "
                "planned slot already holds a terminal completion receipt"
            ),
        )
    from src.campaign.execute import arm_graph_probe

    episode = pending[0]
    slot = f"{episode.case_id}/arm-{episode.arm_id}/repeat-{episode.repeat_index}"
    probe = graph_probe if graph_probe is not None else arm_graph_probe(config)
    deferred = _DeferredCredentialProbe()
    try:
        with tempfile.TemporaryDirectory(prefix="campaign-rehearsal-") as scratch:
            sealed = seal_next_episode(
                config,
                root=Path(scratch),
                plan=plan,
                episode=episode,
                graph=probe(episode.arm_id),
                approval_backend=approval_backend,
                credential_probe=deferred,
            )
            manifest_digest = sealed.manifest_digest
    except CampaignError as exc:
        return RehearsalStep(
            step="episode-manifest-sealed",
            outcome="refused",
            detail=f"{slot} could not seal: {exc.detail}",
        )
    reached = (
        ", and admission read a credential here, which the next step reports"
        if deferred.calls
        else ", on a plan whose zero cap means admission read no credential"
    )
    return RehearsalStep(
        step="episode-manifest-sealed",
        outcome="passed",
        detail=(
            f"{slot} sealed against the compiled graph as {manifest_digest}, "
            f"in a temporary root that has been deleted{reached}"
        ),
    )


def _credential_step(config: Settings) -> RehearsalStep:
    """Call the probe the admission controller calls after an approval."""
    try:
        SettingsCredentialProbe(config)()
    except CampaignError as exc:
        return RehearsalStep(
            step="provider-credential-probed",
            outcome="refused",
            detail=f"SettingsCredentialProbe refused: {exc.detail}",
        )
    return RehearsalStep(
        step="provider-credential-probed",
        outcome="passed",
        detail=(
            "a credential that could pay is configured; the funded path is "
            "open at this door"
        ),
    )


def _client_step(config: Settings, client_probe: ClientProbe | None) -> RehearsalStep:
    """Attempt provider client construction, and report the refusal.

    Run inside `bound_settings(config)` — the same context
    `_run_one_episode` puts the policy in — so the door this reports on
    is the one a funded episode would actually meet. Before W21 that
    context did not reach `src.llm` and this step read whatever the
    process happened to be configured with; now it reads the campaign's
    own `Settings`, and a rehearsal under a `model_copy`ed credential
    reports on *that* credential.

    `bound_settings` lives in `src.campaign.execute` and is imported
    here at call time for the reason `_default_client_probe` gives: the
    read-only verbs must not pay for the gateway's module graph until
    the walk has reached the gateway.

    `except Exception` and not `except BaseException`: under the test
    harness `src.llm._get_client` is replaced by a guard that raises a
    `BaseException` on purpose, precisely so no `except` in this
    repository can swallow it. A rehearsal that met that guard should
    fail the test loudly rather than report a tidy refusal, so it is
    allowed through.
    """
    from src.campaign.execute import bound_settings

    probe = client_probe if client_probe is not None else _default_client_probe
    reads = (
        " (read from the campaign's own settings, the same object admission "
        "read: src.llm is rebound by bound_settings)"
    )
    try:
        with bound_settings(config):
            probe()
    except Exception as exc:  # noqa: BLE001 — the refusal is the finding
        return RehearsalStep(
            step="provider-client-constructed",
            outcome="refused",
            detail=(
                f"client construction refused: {type(exc).__name__}: {exc}{reads}"
            ),
        )
    return RehearsalStep(
        step="provider-client-constructed",
        outcome="passed",
        detail=f"a provider client was constructed; no call was made with it{reads}",
    )


def _default_client_probe() -> object:
    """`src.llm`'s own client constructor, imported at call time.

    Imported inside the function for the reason the CLI imports
    `src.campaign.execute` inside its `run` branch: the read-only verbs
    must not pay for the gateway's module graph.
    """
    from src.llm import _get_client

    return _get_client()


def _preconditions(
    protocol_approval_id: str | None,
    *,
    backend: LocalApprovalRecordBackend,
    ledger_counts: Mapping[str, int],
    config: Settings,
    today: date,
) -> tuple[Precondition, ...]:
    """16 §8's three remaining lines, each answered from the tree.

    None of the three is transcribed. The approval line reads the
    backend, the price line reads `PRICES_LAST_VERIFIED` through
    `price_staleness`, and the token line reads the campaign's own
    completed count — so a precondition that is met stops being reported
    as owed without anyone editing this function.
    """
    from src.calibration.estimate import current_price_table, price_staleness
    from src.llm_models import MODEL_CAPABILITIES

    records = backend.record_ids
    approval_owed = protocol_approval_id is None and not records
    _, verified_on = current_price_table()
    stale = price_staleness(verified_on, today=today)
    ids = sorted({config.anthropic_model, config.eval_judge_model})
    undescribed = [model for model in ids if model not in MODEL_CAPABILITIES]
    completed = ledger_counts.get("completed", 0)
    return (
        Precondition(
            precondition="approval-record",
            owed=approval_owed,
            owner="owner",
            detail=(
                "no external approval record is loaded; a funded run needs one "
                "an owner created, named with --approval-id and read from "
                "--approval-records"
                if approval_owed
                else f"the backend holds {len(records)} approval record(s)"
            ),
        ),
        Precondition(
            precondition="priced-model-ids",
            owed=True,
            owner="owner",
            detail=(
                f"the ids are pinned — {', '.join(ids)}, both described by "
                f"src/llm_models.py ({len(MODEL_CAPABILITIES)} rows, "
                f"{len(undescribed)} undescribed) — and the prices are not: the "
                f"table was last verified {verified_on}"
                + (f". {stale.splitlines()[0]}" if stale else "")
            ),
        ),
        Precondition(
            precondition="measured-token-counts",
            owed=completed == 0,
            owner="owner",
            detail=(
                f"{completed} episode(s) of this campaign have completed, so "
                "16 §3's token counts are still assumptions; one episode under "
                "a separately approved micro-cap replaces every one of them "
                "with a measurement"
            ),
        ),
    )


def _message(stopped_at: str, preconditions: tuple[Precondition, ...]) -> str:
    """The one sentence an operator reads when the rehearsal returns.

    There is deliberately no "nothing is outstanding" branch. The price
    line is owed on every rehearsal by construction — 07 §4 requires the
    ids and prices resolved immediately *before* the run, and no check in
    this repository can stand in for reading the provider's published
    list — so the list is never empty, and a branch that could never run
    would be a claim this module cannot make.
    `tests/test_campaign_rehearsal.py` holds that invariant.
    """
    owed = [item.precondition for item in preconditions if item.owed]
    if stopped_at == CREDENTIAL_BOUNDARY:
        head = (
            "The funded path is complete up to the credential boundary and "
            "stopped there: every step before it passed against real artifacts."
        )
    elif stopped_at == REHEARSAL_STEPS[-1]:
        head = (
            "The funded path ran to the end of the rehearsal without refusing; "
            "a credential that could pay is configured."
        )
    else:
        head = f"The funded path stopped early, at {stopped_at}."
    return (
        f"{head} Still owed, and none of it is code: {', '.join(owed)}. "
        "Nothing in this repository authorizes spending against them."
    )


def _directory_census(directory: Path) -> frozenset[str]:
    """Every path under a campaign directory, relative and sorted-comparable."""
    return frozenset(
        str(path.relative_to(directory)) for path in directory.rglob("*")
    )


__all__ = [
    "CREDENTIAL_BOUNDARY",
    "REHEARSAL_STEPS",
    "ClientProbe",
    "Precondition",
    "RehearsalReport",
    "RehearsalStep",
    "rehearse_campaign",
]
