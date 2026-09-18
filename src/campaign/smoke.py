"""The CAP-06 funded smoke: five probes, one accumulator, one receipt.

[ADR 0090](../../docs/decisions/0090-anthropic-sdk-1x.md) raised the
Anthropic SDK to 1.x against fakes and a golden fixture, and closed with
a paragraph headed *"What CAP-06 (funded smoke) must verify live"*: five
things about the provider's behaviour that **no test in this repository
can establish**, because the model is faked at `src.llm._get_client` and
at `src.llm.anthropic.Anthropic`, above the HTTP layer entirely. The list
has sat there since, with no script behind it — so "run the CAP-06
smoke" meant an engineer improvising five calls by hand against a real
key and writing down what they saw.

This is that script. The five probes are ADR 0090's five, in its order:

1. a plain `call_llm` round trip returns text and `record_llm_call`
   receives non-zero `input_tokens` / `output_tokens` — the whole cost
   table is derived from those and no test exercises a real `usage`;
2. `raw.retries_taken` is populated by the 1.x raw-response class.
   Classified `observed` / `not_observed` and **never failed** on
   `not_observed`: a healthy provider does not retry, and a smoke that
   demanded a retry would be demanding an outage;
3. the prompt-cache buckets still arrive under the names
   `cache_read_input_tokens` / `cache_creation_input_tokens` on a
   `cache_system=True` call — checked on the raw `usage` object by name,
   because the gateway reads them through `getattr(..., 0)` and would
   report zeros for a rename rather than failing;
4. a structured-output call whose `output_config.format` was built by
   `anthropic.transform_schema` is accepted and returns schema-valid
   JSON — the golden fixture proves the *body* is unchanged, not that
   the provider still accepts it;
5. an induced 4xx surfaces as `anthropic.APIStatusError` carrying a
   readable `request_id`, which is what `_log_upstream_error` records and
   what an on-call engineer asks the provider about. Induced with
   `max_tokens=0`, which is refused before any generation and therefore
   **costs nothing**.

Three properties make it safe to point at a credential.

**It cannot bypass approval.** `assert_approval_covers` is the same
function `execute_campaign` pre-flights with, called with the smoke's own
campaign id and stage, so a smoke needs an owner's record exactly as a
campaign does. Possessing a key admits nothing; a zero cap is refused
rather than silently making no calls.

**It spends under one accumulator and one bound cap.** Everything the
five probes do is recorded against a single `RunCosts` with `--cap-usd`
bound as the effective ceiling, so the gateway's own pre-call check stops
the smoke at the number the operator typed.

**It refuses the sentinel before constructing a client.** `_get_client`
already refuses `local-preview-disabled`, but it refuses it *inside* the
constructor — after this module would have decided it was going to
spend. The refusal here is first, and it is this module's own.

See [ADR 0101](../../docs/decisions/0101-the-funded-episode-path.md).
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Final, Literal, TypeAlias

import pydantic
from pydantic import Field, StringConstraints

from src.campaign.approval import (
    DISABLED_API_KEY,
    LocalApprovalRecordBackend,
    assert_approval_covers,
)
from src.campaign.errors import CampaignError
from src.campaign.manifest import write_json
from src.config import Settings
from src.contracts.kernel import MoneyUsd, Rfc3339Utc, StrictContractModel
from src.contracts.research_binding import utc_timestamp
from src.observability import get_logger

log = get_logger(__name__)

#: The campaign id an approval record has to name to authorize a smoke.
#: Its own, not a research campaign's: a record that covers sixty funded
#: episodes should not also, silently, cover an unrelated five calls, and
#: an owner approving a $0.50 smoke should not have to mint a research
#: campaign to hang it on.
SMOKE_CAMPAIGN_ID: Final[str] = "camp_cap06_smoke"

#: The stage that record has to cover. `ApprovalScope.stages` is checked
#: exactly, so this string is part of the approval's shape.
SMOKE_STAGE: Final[str] = "cap-06-smoke"

#: The provider the record has to cover.
SMOKE_PROVIDER: Final[str] = "anthropic"

#: ADR 0090's five, in its order. A closed tuple, so a probe that is
#: added without being reported fails `tests/test_campaign_smoke.py`
#: rather than quietly shortening the list.
SMOKE_PROBES: Final[tuple[str, ...]] = (
    "round-trip-usage",
    "retries-taken",
    "prompt-cache-buckets",
    "structured-output",
    "induced-4xx-request-id",
)

#: Probes whose `not_observed` is an acceptable outcome rather than a
#: failure. Probe 2 because a healthy provider does not retry; probe 4
#: because a model whose capability row forbids structured outputs cannot
#: be asked for them, and reporting that as a failure would blame the
#: provider for the deployment's model choice.
MAY_BE_UNOBSERVED: Final[frozenset[str]] = frozenset(
    {"retries-taken", "structured-output"}
)

#: The system prompt probe 3 caches. Long on purpose: Anthropic's
#: ephemeral cache has a per-model minimum below which a `cache_control`
#: marker silently does nothing, and a probe that sent forty tokens would
#: report two zero buckets and prove only that the fields exist. It still
#: proves that much when the minimum is not met, which is why probe 3's
#: pass condition is the *names* rather than non-zero values.
_CACHE_SYSTEM_PROMPT: Final[str] = (
    "You are a smoke-test responder for a research agent's provider "
    "gateway. Answer in one short word and never explain. "
) * 60

ProbeOutcome: TypeAlias = Literal["passed", "failed", "not_observed"]


class SmokeAnswer(pydantic.BaseModel):
    """The schema probe 4 asks the provider to satisfy.

    Deliberately tiny and deliberately not a contract model: what is
    under test is `anthropic.transform_schema` over a pydantic model and
    the provider's acceptance of the result, so the model should be the
    plainest thing that exercises a required string and a required
    integer.
    """

    verdict: str
    confidence: int


class SmokeProbe(StrictContractModel):
    """One probe's classification and the numbers behind it."""

    probe: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    outcome: ProbeOutcome
    detail: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    request_id: str | None = None
    http_status: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    retries: int | None = None
    cost_usd: MoneyUsd = "0.000000"
    elapsed_seconds: float = 0.0


class SmokeReceipt(StrictContractModel):
    """What one funded smoke observed, and what it cost.

    Written to a file because the point of the exercise is to be able to
    answer "is the 1.x gateway verified against the real provider?"
    without re-running it — and, if the answer is no, to say which of the
    five probes is the reason.
    """

    schema_kind: Literal["campaign-cap06-smoke-receipt"] = "campaign-cap06-smoke-receipt"
    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: str = SMOKE_CAMPAIGN_ID
    stage: str = SMOKE_STAGE
    provider: str = SMOKE_PROVIDER
    approval_id: str
    approval_record_digest: str
    cap_usd: MoneyUsd
    model: str
    sdk_version: str
    started_at: Rfc3339Utc
    completed_at: Rfc3339Utc
    probes: tuple[SmokeProbe, ...]
    model_calls: Annotated[int, Field(ge=0)]
    total_cost_usd: MoneyUsd
    cap_reached: bool = False

    @property
    def passed(self) -> bool:
        """Whether every probe reached an acceptable classification.

        `not_observed` counts as acceptable for exactly the two probes
        `MAY_BE_UNOBSERVED` names, and as a failure everywhere else — an
        unobserved round trip is a round trip that did not happen.
        """
        return all(
            probe.outcome == "passed"
            or (probe.outcome == "not_observed" and probe.probe in MAY_BE_UNOBSERVED)
            for probe in self.probes
        )

    @property
    def unverified(self) -> tuple[str, ...]:
        """The probes ADR 0090's list is still owed."""
        return tuple(
            probe.probe
            for probe in self.probes
            if not (
                probe.outcome == "passed"
                or (probe.outcome == "not_observed" and probe.probe in MAY_BE_UNOBSERVED)
            )
        )


@dataclass
class _Recorded:
    """One raw response the gateway received, kept for the receipt.

    `call_llm` reads `raw.retries_taken` and throws the rest away —
    including `raw.request_id` on a *successful* call, which is the one
    number probes 1 and 3 would otherwise have to go without. Recording
    it here rather than changing the gateway keeps the funded path this
    smoke is verifying byte-identical to the one a campaign runs.
    """

    request_id: str | None
    retries: int | None
    usage_fields: tuple[str, ...]
    input_tokens: int | None
    output_tokens: int | None
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None


@dataclass
class _Observed:
    """One priced call, as `record_llm_call` reported it to an observer."""

    model: str
    cost_usd: float


@dataclass
class _Probes:
    """The two side records the probes are classified from."""

    raws: list[_Recorded] = field(default_factory=list)
    calls: list[_Observed] = field(default_factory=list)


class _RecordedRaw:
    """Intercept `messages.with_raw_response.create` and keep what it returned."""

    def __init__(self, inner: Any, sink: list[_Recorded]) -> None:
        self._inner = inner
        self._sink = sink

    def create(self, **kwargs: Any) -> Any:
        raw = self._inner.create(**kwargs)
        self._sink.append(_describe(raw))
        return raw

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _RecordedMessages:
    """`client.messages`, with the raw-response accessor wrapped."""

    def __init__(self, inner: Any, sink: list[_Recorded]) -> None:
        self._inner = inner
        self.with_raw_response = _RecordedRaw(inner.with_raw_response, sink)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _RecordingClient:
    """The SDK client, unchanged, with one accessor observed.

    Installed as `src.llm._client` for the duration of the smoke, which
    is the seam `bound_settings` already manipulates: the memoised client
    is dropped on the way in and restored on the way out, so putting this
    in its place for the body cannot outlive the smoke. Everything the
    gateway does with the client — the retry envelope, the timeout, the
    server address on the span — goes to the real object through
    `__getattr__`.
    """

    def __init__(self, inner: Any, sink: list[_Recorded]) -> None:
        self._inner = inner
        self.messages = _RecordedMessages(inner.messages, sink)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _describe(raw: Any) -> _Recorded:
    """Read a raw response without being able to fail on it.

    Every field here is *descriptive* — nothing the smoke returns depends
    on any of them — so the same rule `src.llm._describes` states applies:
    an observability read must never break the call it observes. A probe
    that could not read a field reports `None` for it, which is itself
    the finding when the field is one ADR 0090 says should be there.
    """
    usage: Any = None
    with contextlib.suppress(Exception):
        usage = raw.parse().usage
    fields = tuple(
        name
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        if usage is not None and hasattr(usage, name)
    )
    return _Recorded(
        request_id=_str_or_none(getattr(raw, "request_id", None)),
        retries=_int_or_none(getattr(raw, "retries_taken", None)),
        usage_fields=fields,
        input_tokens=_int_or_none(getattr(usage, "input_tokens", None)),
        output_tokens=_int_or_none(getattr(usage, "output_tokens", None)),
        cache_read_input_tokens=_int_or_none(
            getattr(usage, "cache_read_input_tokens", None)
        ),
        cache_creation_input_tokens=_int_or_none(
            getattr(usage, "cache_creation_input_tokens", None)
        ),
    )


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


@contextlib.contextmanager
def _smoke_gateway(config: Settings, probes: _Probes) -> Iterator[None]:
    """Install the smoke's settings, its recording client and its observer.

    `bound_settings` is the campaign's own mechanism and is used here for
    the reason W21 added `src.llm` to its consumer list: the admission
    probe and the gateway must read the same `Settings`, or a smoke could
    be approved against one credential and dial with another. It also
    drops the memoised client on the way in, which is what makes it safe
    to put a recording wrapper there for the body.
    """
    import src.llm as gateway
    from src.campaign.execute import bound_settings
    from src.observability.costs import bind_llm_call_observer, reset_llm_call_observer

    def observe(observation: Any) -> None:
        probes.calls.append(
            _Observed(model=str(observation.model), cost_usd=float(observation.cost_usd))
        )

    token = bind_llm_call_observer(observe)
    try:
        with bound_settings(config):
            gateway._client = _RecordingClient(  # type: ignore[assignment]
                gateway._get_client(), probes.raws
            )
            yield
    finally:
        reset_llm_call_observer(token)


def run_smoke(
    config: Settings,
    *,
    approval_id: str,
    cap_usd: MoneyUsd,
    approval_backend: LocalApprovalRecordBackend,
    receipt_path: Path | None = None,
) -> SmokeReceipt:
    """Run ADR 0090's five probes once, under one cap, and write a receipt.

    Args:
        config: The deployment's settings. Structured outputs are turned
            on for the smoke's own copy — probe 4 is *about* them, and no
            other probe passes a schema, so the switch changes nothing
            else about what goes on the wire.
        approval_id: The owner's approval record. Verified against the
            smoke's own campaign id and stage before a client exists.
        cap_usd: The ceiling, bound as the effective cap for every call.
            Must be positive: a zero cap is a campaign that cannot spend,
            and `assert_approval_covers` refuses an approval claim on one.
        approval_backend: Where the record is read.
        receipt_path: Where to write the JSON receipt. `None` returns it
            without writing.

    Returns:
        The receipt, whether or not every probe passed.

    Raises:
        CampaignError: The credential is missing or is the zero-spend
            sentinel, the cap is not positive, or the approval does not
            cover the smoke. All three are refused *before* a client is
            constructed.
    """
    import anthropic

    secret = config.anthropic_api_key
    key = secret.get_secret_value() if secret is not None else ""
    if not key:
        raise CampaignError("the CAP-06 smoke needs a provider credential; none is set")
    if key == DISABLED_API_KEY:
        raise CampaignError(
            "ANTHROPIC_API_KEY=local-preview-disabled structurally disables "
            "provider calls; the CAP-06 smoke is the one thing that cannot be "
            "run under it, because its whole subject is what the provider does"
        )
    if Decimal(cap_usd) <= 0:
        raise CampaignError(
            "the CAP-06 smoke needs a positive --cap-usd; a zero cap makes no "
            "call and verifies nothing"
        )
    receipt_digest = _verify_approval(approval_backend, approval_id, cap_usd)

    started_at = utc_timestamp()
    log.info(
        "campaign_smoke_started",
        extra={
            "campaign_id": SMOKE_CAMPAIGN_ID,
            "approval_id": approval_id,
            "cap_usd": cap_usd,
            "model": config.anthropic_model,
        },
    )
    smoke_config = config.model_copy(update={"enable_structured_outputs": True})
    assert isinstance(smoke_config, Settings)

    probes = _Probes()
    results: list[SmokeProbe] = []
    from src.observability.costs import (
        bind_effective_cost_cap,
        reset_effective_cost_cap,
        start_cost_tracking,
    )

    costs = start_cost_tracking()
    cap_token = bind_effective_cost_cap(float(Decimal(cap_usd)))
    cap_reached = False
    try:
        with _smoke_gateway(smoke_config, probes):
            results.append(_probe_round_trip(smoke_config, probes))
            results.append(_probe_prompt_cache(smoke_config, probes))
            results.append(_probe_structured_output(smoke_config, probes))
            # Probe 2 reads the raw responses the first three produced,
            # so it is classified after them and reported in ADR 0090's
            # order below rather than in execution order.
            results.insert(1, _probe_retries(probes))
            results.append(_probe_induced_4xx(smoke_config, probes, anthropic))
    finally:
        reset_effective_cost_cap(cap_token)
        cap_reached = float(costs.total_cost_usd) >= float(Decimal(cap_usd))

    receipt = SmokeReceipt(
        approval_id=approval_id,
        approval_record_digest=receipt_digest,
        cap_usd=cap_usd,
        model=config.anthropic_model,
        sdk_version=str(getattr(anthropic, "__version__", "unknown")),
        started_at=started_at,
        completed_at=utc_timestamp(),
        probes=tuple(results),
        model_calls=int(costs.call_count),
        total_cost_usd=f"{Decimal(str(round(float(costs.total_cost_usd), 6))):.6f}",
        cap_reached=cap_reached,
    )
    if receipt_path is not None:
        write_json(receipt_path, receipt.model_dump(mode="json"))
    log.info(
        "campaign_smoke_completed",
        extra={
            "campaign_id": SMOKE_CAMPAIGN_ID,
            "outcome": "passed" if receipt.passed else "failed",
            "call_count": receipt.model_calls,
            "total_cost_usd": receipt.total_cost_usd,
            "cap_usd": cap_usd,
        },
    )
    return receipt


def _verify_approval(
    backend: LocalApprovalRecordBackend, approval_id: str, cap_usd: MoneyUsd
) -> str:
    """Check the owner's record covers this smoke, and return its digest.

    The same call `execute_campaign` pre-flights with, against the
    smoke's own campaign id and stage. The whole allocation is asked for
    as workflow spend and none as judge spend, because the five probes
    are gateway calls and there is no judge in a smoke.
    """
    receipt = assert_approval_covers(
        backend,
        approval_id=approval_id,
        campaign_id=SMOKE_CAMPAIGN_ID,
        stage=SMOKE_STAGE,
        provider=SMOKE_PROVIDER,
        resources=(),
        total_cost_usd_max=cap_usd,
        episode_total_usd_max=cap_usd,
        workflow_usd_max=cap_usd,
        judge_usd_max="0.000000",
        verified_at=utc_timestamp(),
    )
    # `assert_approval_covers` returns `None` only for a zero cap, and
    # `run_smoke` refused that before this was called. An assertion
    # rather than a branch: there is no runtime case to handle, and a
    # raise here would be a line no test could reach honestly.
    assert receipt is not None
    return receipt.record_digest


@contextlib.contextmanager
def _probe(name: str, probes: _Probes) -> Iterator[list[SmokeProbe]]:
    """Run one probe, time it, and attribute the calls it made.

    The `list` yielded is the probe's own result slot, and the contract
    is that a body either appends exactly one `SmokeProbe` to it or
    raises — there is no third case, which is why nothing here defends
    against an empty slot. A body that raises is classified `failed`
    with the exception type: a probe that dies must not take the receipt,
    and therefore the other four probes' evidence, down with it.
    """
    slot: list[SmokeProbe] = []
    started = time.monotonic()
    before_raw, before_calls = len(probes.raws), len(probes.calls)
    try:
        yield slot
    except Exception as exc:  # noqa: BLE001 — a failed probe is the finding
        log.warning(
            "campaign_smoke_probe",
            extra={"probe": name, "outcome": "failed", "error_type": type(exc).__name__},
        )
        slot.append(
            SmokeProbe(
                probe=name,
                outcome="failed",
                detail=f"{type(exc).__name__}: {exc}"[:1000],
                cost_usd=_cost_of(probes.calls[before_calls:]),
                elapsed_seconds=round(time.monotonic() - started, 6),
            )
        )
    recorded = probes.raws[before_raw:]
    slot[0] = slot[0].model_copy(
        update={
            "cost_usd": _cost_of(probes.calls[before_calls:]),
            "elapsed_seconds": round(time.monotonic() - started, 6),
            **_usage_of(recorded, slot[0]),
        }
    )
    log.info(
        "campaign_smoke_probe",
        extra={
            "probe": name,
            "outcome": slot[0].outcome,
            "cost_usd": slot[0].cost_usd,
            "request_id": slot[0].request_id,
        },
    )


def _cost_of(calls: Sequence[_Observed]) -> MoneyUsd:
    """What the calls one probe made were priced at."""
    total = sum(Decimal(str(round(call.cost_usd, 6))) for call in calls)
    return f"{Decimal(total):.6f}"


def _usage_of(recorded: Sequence[_Recorded], probe: SmokeProbe) -> dict[str, Any]:
    """The usage fields a probe's own call reported, if it made one."""
    if not recorded:
        return {}
    last = recorded[-1]
    return {
        "request_id": probe.request_id or last.request_id,
        "retries": last.retries,
        "input_tokens": last.input_tokens,
        "output_tokens": last.output_tokens,
        "cache_read_input_tokens": last.cache_read_input_tokens,
        "cache_creation_input_tokens": last.cache_creation_input_tokens,
    }


def _probe_round_trip(config: Settings, probes: _Probes) -> SmokeProbe:
    """Probe 1: text comes back and the usage the cost table reads is non-zero."""
    from src.llm import call_llm

    with _probe("round-trip-usage", probes) as slot:
        text = call_llm(
            "Reply with the single word: ok.",
            system_prompt="You answer in one word.",
            max_tokens=32,
        )
        recorded = probes.raws[-1] if probes.raws else None
        tokens_in = recorded.input_tokens if recorded else None
        tokens_out = recorded.output_tokens if recorded else None
        ok = bool(text.strip()) and bool(tokens_in) and bool(tokens_out)
        slot.append(
            SmokeProbe(
                probe="round-trip-usage",
                outcome="passed" if ok else "failed",
                detail=(
                    f"{len(text.strip())} char(s) of text; usage reported "
                    f"input_tokens={tokens_in} output_tokens={tokens_out}. "
                    "The cost table is derived from these two numbers."
                ),
            )
        )
    return slot[0]


def _probe_retries(probes: _Probes) -> SmokeProbe:
    """Probe 2: was `raw.retries_taken` populated by the 1.x raw response?

    Read off the calls the other probes already made rather than from a
    call of its own, and **never failed on `not_observed`**: the field is
    the count of attempts the SDK threw away, so observing a non-zero one
    requires the provider to have been throttling or erroring. A smoke
    that insisted on that would be a smoke that only passes during an
    incident. What it can check for free is that the attribute exists and
    reads as an integer, which is the half that a 2.x rename would break.
    """
    present = [item for item in probes.raws if item.retries is not None]
    observed = [item for item in present if (item.retries or 0) > 0]
    if not probes.raws:
        return SmokeProbe(
            probe="retries-taken",
            outcome="failed",
            detail="no raw response was recorded, so the field could not be read",
        )
    if not present:
        return SmokeProbe(
            probe="retries-taken",
            outcome="failed",
            detail=(
                f"none of {len(probes.raws)} raw response(s) carried an integer "
                "`retries_taken`; the gateway reads this field on every call "
                "and would be recording nothing"
            ),
        )
    if not observed:
        return SmokeProbe(
            probe="retries-taken",
            outcome="not_observed",
            detail=(
                f"`retries_taken` was present and integral on all {len(present)} "
                "call(s) and was 0 on every one: nothing retried, which is what "
                "a healthy provider does. The field is readable; a non-zero "
                "value has not been observed live"
            ),
            retries=0,
        )
    return SmokeProbe(
        probe="retries-taken",
        outcome="passed",
        detail=(
            f"{len(observed)} of {len(present)} call(s) reported a non-zero "
            f"`retries_taken` (max {max(item.retries or 0 for item in observed)})"
        ),
        retries=max(item.retries or 0 for item in observed),
    )


def _probe_prompt_cache(config: Settings, probes: _Probes) -> SmokeProbe:
    """Probe 3: the two cache buckets still arrive under those names.

    Checked by name on the raw `usage` object, not by value. The gateway
    reads them as `getattr(response.usage, "cache_read_input_tokens", 0)`,
    so a provider that renamed either field would hand this fleet two
    permanent zeros and no error — every cached call would be priced as
    though it had never hit the cache. That silence is the failure this
    probe exists to break.
    """
    from src.llm import call_llm

    with _probe("prompt-cache-buckets", probes) as slot:
        call_llm(
            "Reply with the single word: cached.",
            system_prompt=_CACHE_SYSTEM_PROMPT,
            max_tokens=32,
            cache_system=True,
        )
        recorded = probes.raws[-1] if probes.raws else None
        names = set(recorded.usage_fields) if recorded else set()
        ok = {"cache_read_input_tokens", "cache_creation_input_tokens"} <= names
        slot.append(
            SmokeProbe(
                probe="prompt-cache-buckets",
                outcome="passed" if ok else "failed",
                detail=(
                    f"usage carried {sorted(names)}; a cache_system=True call "
                    "must report both bucket names or every cached call in "
                    "this fleet is priced as a miss"
                ),
            )
        )
    return slot[0]


def _probe_structured_output(config: Settings, probes: _Probes) -> SmokeProbe:
    """Probe 4: `transform_schema`'s `output_config.format` is still accepted."""
    from src.llm import call_llm_json, resolve_profile

    profile = resolve_profile(config.anthropic_model)
    if not profile.structured_outputs:
        return SmokeProbe(
            probe="structured-output",
            outcome="not_observed",
            detail=(
                f"{config.anthropic_model} does not take structured outputs "
                "according to src/llm_models.py, so no schema could be sent. "
                "This probe is owed against a model whose row allows them"
            ),
        )
    with _probe("structured-output", probes) as slot:
        answer = call_llm_json(
            "Judge the statement 'water is wet'. Answer with a one-word "
            "verdict and an integer confidence from 0 to 100.",
            system_prompt="You answer only in the requested JSON shape.",
            max_tokens=256,
            schema=SmokeAnswer,
        )
        validated = SmokeAnswer.model_validate(answer)
        slot.append(
            SmokeProbe(
                probe="structured-output",
                outcome="passed",
                detail=(
                    "output_config.format built by anthropic.transform_schema "
                    f"was accepted and returned schema-valid JSON "
                    f"({len(validated.verdict)} char verdict, confidence "
                    f"{validated.confidence})"
                ),
            )
        )
    return slot[0]


def _probe_induced_4xx(config: Settings, probes: _Probes, anthropic: Any) -> SmokeProbe:
    """Probe 5: a refused request surfaces as `APIStatusError` with a request id.

    Called against the client directly rather than through `call_llm`,
    and that is the point rather than a shortcut: `call_llm` catches
    `anthropic.APIStatusError`, logs its `request_id` and re-raises
    `UpstreamModel`, which carries no request id at all. So the thing
    ADR 0090 asks to verify — that the id an on-call engineer quotes to
    the provider is readable off the exception — is only observable at
    the SDK boundary.

    `max_tokens=0` is the induced failure because it is refused as an
    invalid request *before* any generation, so this probe costs nothing.
    An invalid model id would also 4xx, but a typo'd id that the provider
    happened to recognise would be a real, billed call.
    """
    from src.llm import _get_client

    with _probe("induced-4xx-request-id", probes) as slot:
        try:
            _get_client().messages.with_raw_response.create(
                model=config.anthropic_model,
                max_tokens=0,
                messages=[{"role": "user", "content": "this request is invalid"}],
            )
        except anthropic.APIStatusError as exc:
            status = int(getattr(exc, "status_code", 0) or 0)
            request_id = _str_or_none(getattr(exc, "request_id", None))
            ok = 400 <= status < 500 and request_id is not None
            slot.append(
                SmokeProbe(
                    probe="induced-4xx-request-id",
                    outcome="passed" if ok else "failed",
                    detail=(
                        f"max_tokens=0 was refused with HTTP {status}; "
                        f"request_id {'present' if request_id else 'absent'}. "
                        "The id is what _log_upstream_error records and what "
                        "the provider is asked about"
                    ),
                    request_id=request_id,
                    http_status=status,
                )
            )
        else:
            slot.append(
                SmokeProbe(
                    probe="induced-4xx-request-id",
                    outcome="failed",
                    detail=(
                        "max_tokens=0 was accepted; the induced failure did not "
                        "fail, so nothing was learned about APIStatusError and "
                        "a billed call may have been made"
                    ),
                )
            )
    return slot[0]


def render_receipt(receipt: SmokeReceipt) -> str:
    """The receipt as the CLI prints it: JSON, plus the one verdict line."""
    payload = receipt.model_dump(mode="json")
    payload["passed"] = receipt.passed
    payload["unverified"] = list(receipt.unverified)
    return json.dumps(payload, indent=2, sort_keys=True)


__all__ = [
    "MAY_BE_UNOBSERVED",
    "SMOKE_CAMPAIGN_ID",
    "SMOKE_PROBES",
    "SMOKE_PROVIDER",
    "SMOKE_STAGE",
    "SmokeAnswer",
    "SmokeProbe",
    "SmokeReceipt",
    "render_receipt",
    "run_smoke",
]
