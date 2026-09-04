"""Shared `requests.Session` with retry + backoff on transient HTTP errors.

`urllib3.util.Retry` is the industry-standard way to layer retries on top
of the `requests` library — respects `Retry-After` headers on 429s and
uses exponential backoff. Every outbound HTTP call in the project (arXiv
API, PDF downloads, Semantic Scholar) should go through
`build_retrying_session()` so retry behavior is one place and every knob
comes from `settings`.

See ADR 0013 for the choice of `urllib3.Retry` over `tenacity` / manual
loops, and ADR 0068 for the three things this module gained afterwards:

- **This is the one owning level for HTTP retries.** No caller adds a
  loop of its own; retry amplification is multiplicative and the
  baseline found this repository retrying at five levels at once.
- **Full Jitter**, replacing urllib3's exponential-plus-optional-addend
  curve. Two workers that failed at the same instant must not wake at
  the same instant.
- **A retry token bucket**, so during an upstream outage a job stops
  paying its full retry envelope and fails fast instead
  (`src/resilience.py`). The bucket is a pass-through while it is full,
  which is why the healthy path is unchanged.
"""

from __future__ import annotations

from itertools import takewhile
from types import TracebackType
from typing import Any, Self

import requests
from requests.adapters import HTTPAdapter
from urllib3.connectionpool import ConnectionPool
from urllib3.exceptions import MaxRetryError, ResponseError
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from src.config import settings
from src.resilience import (
    DEPENDENCY_HTTP,
    RetryBudget,
    clamped_retry_envelope,
    full_jitter_delay,
    get_retry_budget,
)

# Idempotent methods only; POSTs must opt-in explicitly by passing a
# session built with `allowed_methods` overridden.
_DEFAULT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Transient statuses worth retrying. 408 (request timeout), 425 (too
# early), 429 (rate limit), 500 / 502 / 503 / 504 (server errors).
RETRYABLE_STATUSES = (408, 425, 429, 500, 502, 503, 504)

#: What `MaxRetryError.reason` carries when the budget, rather than the
#: attempt count, ended the chain. `requests` maps a `ResponseError`
#: reason onto `requests.exceptions.RetryError`, which is a
#: `RequestException` — so every existing `except RequestException`
#: handler already treats budget exhaustion as the upstream failure it
#: is, and no call site needs a new branch to stay correct.
BUDGET_EXHAUSTED_REASON = "retry budget exhausted"


class BudgetedRetry(Retry):
    """`urllib3.Retry` with Full Jitter and a retry token bucket.

    `Retry.increment` is the one place urllib3 decides a retry will
    happen, which makes it the only correct seam for a budget: the
    bucket is charged exactly once per retry actually taken, never per
    request and never per connection. Wrapping the session or the
    adapter instead would have charged the budget for first attempts
    too — and a budget that throttles first attempts is a circuit
    breaker wearing a different name, which ADR 0068 rejects.
    """

    def __init__(self, *args: Any, budget: RetryBudget | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._budget = budget

    @property
    def budget(self) -> RetryBudget | None:
        """The bucket this policy charges, for tests and introspection."""
        return self._budget

    def new(self, **kw: Any) -> Self:
        """Carry the budget across the copy urllib3 makes per attempt.

        `Retry.new` rebuilds the object from a fixed parameter list it
        does not know this subclass extended, so without this override
        the budget would silently become `None` on the first retry —
        the bucket would appear to work and would never charge
        anything.
        """
        kw.setdefault("budget", self._budget)
        return super().new(**kw)

    def get_backoff_time(self) -> float:
        """Full Jitter: `random(0, min(cap, base * 2**attempt))`.

        urllib3's own formula is `backoff_factor * 2**(n-1)` plus an
        optional uniform addend of at most `backoff_jitter`. That addend
        leaves a synchronised fleet correlated — every worker still
        wakes inside the same narrow window — which is the failure Full
        Jitter exists to remove. The exponent and the `<= 1` short
        circuit are kept identical to the base class, so only the
        *shape of the draw* changes: the first retry is still immediate.
        """
        consecutive_errors = len(
            list(takewhile(lambda x: x.redirect_location is None, reversed(self.history)))
        )
        if consecutive_errors <= 1:
            return 0.0
        return full_jitter_delay(
            consecutive_errors - 1,
            base_sec=self.backoff_factor,
            cap_sec=float(self.backoff_max),
        )

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: BaseHTTPResponse | None = None,
        error: Exception | None = None,
        _pool: ConnectionPool | None = None,
        _stacktrace: TracebackType | None = None,
    ) -> Self:
        """Charge the budget, then defer to urllib3's own accounting.

        Refusing here raises the same `MaxRetryError` the base class
        raises when the attempt count runs out, so the failure travels
        the path every caller already handles. What changes is *when*:
        during an outage the chain ends on the first retry instead of
        the last, which is the entire point of a retry budget.
        """
        budget = self._budget
        if budget is not None and not budget.try_spend():
            raise MaxRetryError(_pool, url or "", ResponseError(BUDGET_EXHAUSTED_REASON))  # type: ignore[arg-type]
        return super().increment(method, url, response, error, _pool, _stacktrace)


def build_retrying_session(
    *,
    max_retries: int | None = None,
    backoff_factor: float | None = None,
    timeout_sec: float | None = None,
    dependency: str = DEPENDENCY_HTTP,
) -> requests.Session:
    """Return a `requests.Session` with retry+backoff on transient HTTP errors.

    `max_retries` and `backoff_factor` default to the values in
    `settings` so callers don't have to pass them (and tests can
    override via `monkeypatch.setattr(module, "settings", ...)`).

    Args:
        max_retries: Retry attempts after the first failure.
        backoff_factor: Base delay for the Full Jitter draw. The delay
            before retry `n` is `random(0, min(cap, factor * 2**n))`.
        timeout_sec: The per-attempt timeout the caller will pass to
            `session.get`. Supplying it turns on the ADR 0068 clamp:
            retries are trimmed until `(retries + 1) * timeout_sec`
            fits this dependency's share of the job budget, and a
            `retry_envelope_clamped` WARNING says so. Omitting it keeps
            the historical behaviour, which is what every call site
            that has not yet declared its timeout still gets.
        dependency: Which retry budget this session's retries are
            charged to (`src.resilience.DEPENDENCY_*`). Separate
            budgets, so an arXiv outage cannot spend the retries that
            keep PDF downloads working.

    Returns:
        A `requests.Session` with an `HTTPAdapter` wired to a
        `BudgetedRetry` policy on both `http://` and `https://`.
    """
    total = max_retries if max_retries is not None else settings.http_max_retries
    backoff = backoff_factor if backoff_factor is not None else settings.http_backoff_factor
    chain_budget_sec = settings.api_job_timeout_sec * settings.http_call_chain_budget_fraction
    if timeout_sec is not None:
        total = clamped_retry_envelope(
            configured_retries=total,
            timeout_sec=timeout_sec,
            budget_sec=chain_budget_sec,
            dependency=dependency,
        )
    retry = BudgetedRetry(
        total=total,
        backoff_factor=backoff,
        backoff_max=settings.http_backoff_max_sec,
        status_forcelist=RETRYABLE_STATUSES,
        allowed_methods=_DEFAULT_METHODS,
        respect_retry_after_header=True,
        # urllib3 honours a `Retry-After` of up to six hours by default.
        # A server-supplied delay longer than the whole call chain's
        # budget cannot help this job — the job times out first — and
        # holding a worker thread asleep through it is the worst of
        # both outcomes, so it is truncated to that budget.
        retry_after_max=max(1, int(chain_budget_sec)),
        raise_on_status=False,
        budget=get_retry_budget(dependency),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
