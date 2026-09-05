"""Resilience policy: one retry level per dependency, and a budget for it.

The measured problem this module answers is *retry amplification*, not
an absent breaker. `planning/08-assurance/01-BASELINE.md` §2 counted
retries at five levels of one stack — the Anthropic SDK's own envelope,
`urllib3.Retry` under every `requests` call, and three hand-rolled
loops — and three retries at five levels is 243x load on a dependency
that is already failing. Two things follow, and this module holds both.

## 1. Retry at exactly one level, per dependency

The consolidation is worth more than any new mechanism, so it is
written down here rather than left implicit in five files:

| Dependency        | Owning level                          | Everything else |
|-------------------|---------------------------------------|-----------------|
| Anthropic API     | the SDK's clamped envelope (`src/llm.py:62-91`) | no application loop |
| arXiv / S2 / PDFs | `urllib3.Retry` (`src/tools/http_session.py`)   | no per-call loop |
| Redis             | `redis-py`'s own `Retry` (`src/api/redis_store.py`) | no application loop |

The table is a claim about the code, so
`tests/test_resilience_transport.py` proves the arXiv row by counting
the requests a loopback server actually receives, rather than trusting
this comment.

Two loops that survive the consolidation are *not* transport retries
and are recorded as such in ADR 0068: `src/agents/synthesizer.py`
re-prompts once on an unparseable model response (a semantic retry),
and `src/api/runner.py` re-attempts a terminal *write* (an internal
persistence retry, no upstream involved).

## 2. A retry token bucket, not a circuit breaker

`planning/08-assurance/02-STANDARDS.md` §5.2 records the contest —
Nygard and Fowler argue for breakers, AWS argues against them because
they introduce modal behaviour that is hard to test — and the reasons
the bucket wins here: it is small, it adds no second mode to the
success path, and it addresses the measured problem directly. A
breaker changes what happens to *requests*; the budget changes only
what happens to *retries*, which is the load that multiplies.

The bucket is per-process, not shared through Redis. That is the AWS
design and it is the right one for a retry guard: a budget that had to
ask Redis for permission would be unavailable in exactly the outage it
exists for, and would add a network round trip to the failure path.
The cost is that N workers get N budgets, so the fleet-wide ceiling is
N x `retry_budget_capacity` — stated in ADR 0068 rather than hidden.

## 3. Full Jitter, everywhere

`sleep = random(0, min(cap, base * 2**attempt))`. Equal jitter and
"exponential plus a small random addend" both leave the retries of a
synchronised fleet correlated; Full Jitter is the one that decorrelates
them. `full_jitter_delay` is the single implementation, so a call site
cannot quietly get a different curve.
"""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

from src.cancellation import check_cancelled
from src.config import settings
from src.observability import get_logger, record_degradation_rung

log = get_logger(__name__)

__all__ = [
    "DEPENDENCY_ARXIV",
    "DEPENDENCY_HTTP",
    "RetryBudget",
    "clamped_retry_envelope",
    "degradation_counts",
    "full_jitter_delay",
    "get_retry_budget",
    "interruptible_sleep",
    "record_degradation",
    "reset_clamp_warnings",
    "reset_degradation_counts",
    "reset_retry_budgets",
]


# ---------------------------------------------------------------------------
# Dependency names. Deliberately a small closed vocabulary: the budget is
# per-dependency because an arXiv outage must not spend the budget that
# keeps PDF downloads retrying, and a free-form string key would let a
# typo silently create a second, empty bucket that never throttles.
# ---------------------------------------------------------------------------

DEPENDENCY_ARXIV: Final[str] = "arxiv"
"""The arXiv Atom API — the one call site wired to a named budget today."""

DEPENDENCY_HTTP: Final[str] = "http"
"""Every other `build_retrying_session` caller: PDFs, Semantic Scholar."""

_DEPENDENCIES: Final[frozenset[str]] = frozenset({DEPENDENCY_ARXIV, DEPENDENCY_HTTP})


# ---------------------------------------------------------------------------
# Full Jitter
# ---------------------------------------------------------------------------


def full_jitter_delay(
    attempt: int,
    *,
    base_sec: float,
    cap_sec: float,
    rng: random.Random | None = None,
) -> float:
    """Return the Full Jitter backoff for a zero-based retry `attempt`.

    `random(0, min(cap, base * 2**attempt))`. The uniform draw over the
    *whole* interval rather than around its top is the point: two
    workers that failed at the same instant must not wake at the same
    instant, and a delay drawn near the ceiling keeps them nearly as
    correlated as no jitter at all.

    Args:
        attempt: Zero-based retry number — 0 is the first retry.
        base_sec: The un-jittered delay before the first retry.
        cap_sec: Ceiling on the interval the delay is drawn from.
        rng: Source of randomness. Tests pass a seeded `random.Random`;
            production leaves it `None` and uses the shared module RNG.

    Returns:
        Seconds to sleep. Always in `[0, cap_sec]`.
    """
    # `2**attempt` on a large attempt count is an unbounded int, so the
    # cap is applied to the exponent's *result* via `min` before the
    # draw — never to the draw afterwards, which would re-correlate the
    # fleet at the ceiling.
    ceiling = min(cap_sec, base_sec * (2**attempt))
    draw = rng.uniform if rng is not None else random.uniform
    return float(draw(0.0, max(0.0, ceiling)))


# ---------------------------------------------------------------------------
# The retry token bucket
# ---------------------------------------------------------------------------


@dataclass
class RetryBudget:
    """A refilling token budget that throttles retries, not requests.

    A *first attempt* never consults this object. Only a retry spends a
    token, so a healthy caller — one whose requests succeed, or whose
    requests fail in a way nobody retries — cannot be affected by the
    bucket at all. That property is what makes the budget cheaper to
    reason about than a breaker: there is no second mode in which the
    success path behaves differently.

    Tokens come back two ways, and both are needed:

    - **Time.** `refill_per_sec` guarantees a fully drained bucket
      recovers on its own. Without it, a process that drained its
      budget during an outage would never retry again, because the
      other refill source requires successes it can no longer get.
    - **Success.** `success_refund` couples the budget to the *ratio*
      of retries to successes rather than to their absolute rate. A
      high-throughput caller with a healthy dependency earns retries as
      fast as it spends them; the same caller against a dead dependency
      earns nothing, and the bucket empties. AWS's SDKs use 5 successes
      per retry and so does the shipped default.

    Every method is guarded by a lock: the graph runs nodes in a thread
    pool, so one budget is contended by several threads and a
    read-modify-write of `_tokens` across them would over-issue exactly
    when the budget matters.
    """

    name: str
    capacity: float
    refill_per_sec: float
    success_refund: float
    #: Injected so tests are deterministic rather than slow. `monotonic`
    #: and not `time()`: a wall-clock step (NTP, a suspended laptop)
    #: must not hand the bucket a windfall of tokens.
    time_source: Callable[[], float] = time.monotonic
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _exhaustions: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        # Starts full. A process that boots into an ongoing outage gets
        # one bucket's worth of retries before it starts throttling,
        # which is the same allowance every other process has.
        self._tokens = self.capacity
        self._last_refill = self.time_source()

    def _refill_locked(self) -> None:
        """Add the tokens elapsed time has earned. Caller holds the lock."""
        now = self.time_source()
        elapsed = now - self._last_refill
        self._last_refill = now
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)

    def try_spend(self, cost: float = 1.0) -> bool:
        """Take `cost` tokens for one retry, or refuse.

        Returns:
            True if the retry may proceed. False means the budget is
            exhausted and the caller must fail *now* rather than
            retrying — which is the whole point: during an outage the
            job stops paying its full retry envelope and fails fast.
        """
        with self._lock:
            self._refill_locked()
            if self._tokens < cost:
                self._exhaustions += 1
                return False
            self._tokens -= cost
            return True

    def on_success(self) -> None:
        """Refund the ratio share earned by one successful call."""
        with self._lock:
            self._refill_locked()
            self._tokens = min(self.capacity, self._tokens + self.success_refund)

    @property
    def tokens(self) -> float:
        """Tokens available right now, time refill included."""
        with self._lock:
            self._refill_locked()
            return self._tokens

    @property
    def exhaustions(self) -> int:
        """How many retries this budget has refused since construction."""
        with self._lock:
            return self._exhaustions


_budgets: dict[str, RetryBudget] = {}
_budgets_lock: Final[threading.Lock] = threading.Lock()


def get_retry_budget(dependency: str) -> RetryBudget | None:
    """Return the process-wide budget for `dependency`.

    Built lazily from `settings` on first use rather than at import, so
    a test that overrides the settings before touching HTTP gets the
    budget it configured — the same reason `src/llm.py` builds its
    client lazily.

    Args:
        dependency: One of the `DEPENDENCY_*` constants.

    Returns:
        The shared budget, or None when `enable_retry_budget` is off —
        in which case every caller behaves exactly as it did before
        this module existed.

    Raises:
        ValueError: `dependency` is not a declared name. A typo would
            otherwise create a private bucket that never throttles.
    """
    if dependency not in _DEPENDENCIES:
        raise ValueError(
            f"unknown retry-budget dependency {dependency!r}; "
            f"expected one of {sorted(_DEPENDENCIES)}"
        )
    if not settings.enable_retry_budget:
        return None
    with _budgets_lock:
        budget = _budgets.get(dependency)
        if budget is None:
            budget = RetryBudget(
                name=dependency,
                capacity=float(settings.retry_budget_capacity),
                refill_per_sec=settings.retry_budget_refill_per_sec,
                success_refund=settings.retry_budget_success_refund,
            )
            _budgets[dependency] = budget
        return budget


def reset_retry_budgets() -> None:
    """Drop every cached budget.

    The budget is process-wide state and the test suite is one process,
    so a test that drains a bucket would otherwise leak an exhausted
    budget into whatever ran next. Exported for that, and for a future
    settings hot-reload.
    """
    with _budgets_lock:
        _budgets.clear()


# ---------------------------------------------------------------------------
# The retry-envelope clamp — the shape `src/llm.py:62-91` established
# ---------------------------------------------------------------------------

#: Clamps already reported, keyed by the four inputs and the one output
#: that the WARNING is made of. Once per distinct clamp per process, not
#: once per call, for the reason `costs._unpriced_warned` exists: a call
#: site inside a per-paper loop turns a line that matters into hundreds
#: of lines that don't, and the way a warning stops being read is by
#: repeating. `pdf_parser` is that call site — one download per paper,
#: the same clamp every time.
#:
#: Keyed on the whole determinant rather than on `(dependency, clamped)`
#: alone, because `dependency` is a two-value vocabulary and every
#: non-arXiv caller shares `http`: PDFs at 60s and Semantic Scholar at
#: some other timeout can clamp to the same retry count for completely
#: different reasons, and a key that collapsed them would silence the
#: second misconfiguration on the strength of having reported the
#: first. The rule this key implements is exactly "the same clamp does
#: not repeat itself, and any clamp that differs in any respect
#: speaks" — which is the only version of it that cannot under-warn.
#:
#: Guarded by a lock because the reader's fan-out builds sessions from
#: a thread pool.
_clamp_warned: set[tuple[str, int, int, float, float]] = set()
_clamp_lock = threading.Lock()


def _warn_clamp_once(
    *,
    dependency: str,
    clamped: int,
    configured_retries: int,
    timeout_sec: float,
    budget_sec: float,
) -> None:
    """Emit the clamp WARNING the first time this exact clamp happens.

    Returns silently on every later call with the same five values.
    WARNING and not INFO, unchanged: the operator configured a retry
    count this deployment will not honour, and the shape of the incident
    that follows ("why did it only try twice?") is unanswerable without
    the line. What changes is only how often it is worth saying.
    """
    key = (dependency, clamped, configured_retries, timeout_sec, budget_sec)
    with _clamp_lock:
        if key in _clamp_warned:
            return
        _clamp_warned.add(key)
    log.warning(
        "retry_envelope_clamped",
        extra={
            "dependency": dependency,
            "max_retries": clamped,
            "configured_max_retries": configured_retries,
            "timeout_sec": timeout_sec,
            "budget_sec": budget_sec,
            "worst_case_request_sec": (clamped + 1) * timeout_sec,
        },
    )


def reset_clamp_warnings() -> None:
    """Forget which clamps have already warned.

    Test seam only, mirroring `costs.reset_unpriced_warnings`: the
    warn-once set is process-global and the suite is one process, so a
    test that asserts the warning fires needs a way back to a clean
    slate that does not reach into module internals.
    """
    with _clamp_lock:
        _clamp_warned.clear()


def clamped_retry_envelope(
    *,
    configured_retries: int,
    timeout_sec: float,
    budget_sec: float,
    dependency: str,
) -> int:
    """Trim `configured_retries` so the worst-case call chain fits a job.

    Copied deliberately from `_retry_envelope` in `src/llm.py`, which
    is the reference implementation and the reason this repository has
    never had one flaky model call eat a whole job. The same arithmetic
    was missing on the HTTP side: `urllib3.Retry` applies its timeout
    *per attempt* exactly as the Anthropic SDK does, so one logical
    request costs `(retries + 1) * timeout` in the worst case, and
    nothing bounded that against `api_job_timeout_sec`. With the
    shipped arXiv values before this change — 4 attempts x 30s, up to
    12 queries — a search node could alone exceed a 600s job.

    Attempts are trimmed rather than the per-attempt timeout, for the
    same reason `src/llm.py` gives: a shorter timeout abandons *slow
    but healthy* responses, which is the failure mode that looks like
    an outage while the dependency is fine.

    A clamp that bites warns **once per distinct clamp per process**
    (`_warn_clamp_once`). The clamp itself is unconditional — every call
    is trimmed — and only the reporting is deduplicated.

    Args:
        configured_retries: What the operator asked for.
        timeout_sec: Per-attempt timeout the retries will be spent at.
        budget_sec: Wall clock this call chain is allowed to occupy.
        dependency: Name for the WARNING, so an operator reading the
            log knows which knob to turn.

    Returns:
        The retry count to use. Never negative, and never larger than
        `configured_retries`.
    """
    # At least one attempt always survives: a timeout larger than the
    # whole budget is an operator's explicit choice, and refusing to
    # call at all would be a worse answer than one long attempt.
    affordable_attempts = max(1, int(budget_sec // timeout_sec)) if timeout_sec > 0 else 1
    clamped = max(0, min(configured_retries, affordable_attempts - 1))
    if clamped < configured_retries:
        _warn_clamp_once(
            dependency=dependency,
            clamped=clamped,
            configured_retries=configured_retries,
            timeout_sec=timeout_sec,
            budget_sec=budget_sec,
        )
    return clamped


# ---------------------------------------------------------------------------
# Degradation markers
# ---------------------------------------------------------------------------

_degradations: Counter[tuple[str, str]] = Counter()
_degradations_lock: Final[threading.Lock] = threading.Lock()


def record_degradation(
    *, rung: str, component: str, reason: str, error: str | None = None
) -> None:
    """Count and log one rung of the degradation ladder.

    `02-STANDARDS.md` §5.3 is blunt about why this exists: every rung
    must emit a distinct marker, or degradation makes the dashboard
    look *better* while the product gets worse. A rate limiter that
    silently falls back to a per-worker counter is serving a weaker
    guarantee than the one its configuration claims, and the only
    honest way to run it is to make the fallback visible.

    All three markers land here: the in-process counter (which
    `/healthz` and the tests read), the `resilience_degraded` WARNING,
    and — since ADR 0081 — the OTel instrument
    `research_degradations_total`, which is what makes the quality SLI
    in `docs/reliability.md` §3 computable. ADR 0068 deferred that last
    one as a named follow-up because `metrics.py` belonged to a peer
    work order mid-wave; this is that follow-up, taken under a granted
    fence exception.

    `rung` is required rather than defaulted. A default would have to be
    `weakened_guarantee`, because that is what the only caller on this
    branch is, and the next caller down a different rung would then be
    counted under the wrong one silently — which is precisely the
    "degradation makes the dashboard look better" failure this function
    exists to prevent, reintroduced one layer up.

    Args:
        rung: A member of `metrics.DEGRADATION_RUNGS` — which rung of
            `docs/reliability.md` §5 was taken. Closed set: see that
            module's docstring for why an open string is not an option
            for a metric attribute.
        component: What degraded — a member of
            `metrics.DEGRADATION_COMPONENTS`.
        reason: Why, as a bounded machine token (`redis_unavailable`),
            never an exception message. Stays on the log line and does
            *not* become a metric attribute: the metric answers "how
            much, where", the log answers "why".
        error: The failing exception's *class name*, when the caller
            has one. Deliberately not `str(exc)`: a client library's
            message embeds the connection URL, which is the leak ADR
            0042 exists to stop, and the class name is what an operator
            greps for anyway.
    """
    with _degradations_lock:
        _degradations[(component, reason)] += 1
        count = _degradations[(component, reason)]
    extra: dict[str, object] = {"component": component, "reason": reason, "count": count}
    if error is not None:
        extra["error"] = error
    log.warning("resilience_degraded", extra=extra)
    record_degradation_rung(rung=rung, component=component)


def degradation_counts() -> Mapping[tuple[str, str], int]:
    """A snapshot of the degradation counters.

    A copy, not the live `Counter`: this is a read surface for tests
    and for whatever exports it next — the OTel fold-in, or `/healthz`
    — and a caller that could mutate the counter through it would be
    able to erase the evidence of a degradation.
    """
    with _degradations_lock:
        return dict(_degradations)


def reset_degradation_counts() -> None:
    """Clear the counters. Same process-wide-state rationale as budgets."""
    with _degradations_lock:
        _degradations.clear()


# ---------------------------------------------------------------------------
# Cancellable waiting
# ---------------------------------------------------------------------------

#: How finely `interruptible_sleep` chops a wait. 50ms is far below the
#: 30s drain window a cancelled job gets and far above the cost of the
#: contextvar read each slice pays, so the check is effectively free and
#: the worst-case overshoot is invisible to a person.
CANCEL_POLL_SEC: Final[float] = 0.05


def interruptible_sleep(seconds: float, *, poll_sec: float = CANCEL_POLL_SEC) -> None:
    """Sleep, but let a cancelled job out promptly.

    `time.sleep(3)` inside a node holds a worker thread for three
    seconds no matter what happens to the job. The search agent's
    pacing loop did exactly that, once per query, and a cancelled job
    could burn its whole 30s drain window on pacing alone
    (`01-BASELINE.md` §2). Slicing the wait and re-checking the token
    between slices costs nothing and bounds the delay at `poll_sec`.

    Args:
        seconds: Total time to wait. Values <= 0 return immediately,
            after one cancellation check.
        poll_sec: Slice length; the worst-case delay before a cancel
            is noticed.

    Raises:
        JobCancelledError: The bound cancel token fired. A no-op when
            no token is bound, which is the CLI and eval-runner case.
    """
    check_cancelled()
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(poll_sec, remaining))
        check_cancelled()
