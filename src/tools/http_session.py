"""Shared `requests.Session` with retry + backoff on transient HTTP errors.

`urllib3.util.Retry` is the industry-standard way to layer retries on top
of the `requests` library — respects `Retry-After` headers on 429s and
uses exponential backoff (`backoff_factor * (2 ** attempt)`) with jitter.
Every outbound HTTP call in the project (arXiv API, PDF downloads)
should go through `build_retrying_session()` so retry behavior is one
place and every knob comes from `settings`.

See ADR 0013 for the choice of `urllib3.Retry` over `tenacity` /
manual loops.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import settings

# Idempotent methods only; POSTs must opt-in explicitly by passing a
# session built with `allowed_methods` overridden.
_DEFAULT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Transient statuses worth retrying. 408 (request timeout), 425 (too
# early), 429 (rate limit), 500 / 502 / 503 / 504 (server errors).
RETRYABLE_STATUSES = (408, 425, 429, 500, 502, 503, 504)


def build_retrying_session(
    *,
    max_retries: int | None = None,
    backoff_factor: float | None = None,
) -> requests.Session:
    """Return a `requests.Session` with retry+backoff on transient HTTP errors.

    Both `max_retries` and `backoff_factor` default to the values in
    `settings` so callers don't have to pass them (and tests can
    override via `monkeypatch.setattr(module, "settings", ...)`).

    Args:
        max_retries: Retry attempts after the first failure.
        backoff_factor: `urllib3.Retry` backoff_factor. Delay before
            attempt `n` is `factor * (2 ** (n - 1))`.

    Returns:
        A `requests.Session` with an `HTTPAdapter` wired to a `Retry`
        policy on both `http://` and `https://`.
    """
    total = max_retries if max_retries is not None else settings.http_max_retries
    backoff = (
        backoff_factor
        if backoff_factor is not None
        else settings.http_backoff_factor
    )
    retry = Retry(
        total=total,
        backoff_factor=backoff,
        status_forcelist=RETRYABLE_STATUSES,
        allowed_methods=_DEFAULT_METHODS,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
