"""Cooperative cancellation for graph work that runs off the event loop.

Every LangGraph node in this project is a *synchronous* function, so on
the API's async path LangGraph hands it to a thread pool and awaits the
future. Cancelling that await — which is all `asyncio.wait_for` can do —
stops the coroutine, not the thread: the LLM call or PDF parse inside the
node keeps running, keeps spending, and keeps a worker thread pinned long
after the job was marked failed. Threads cannot be killed from outside in
CPython, so the only honest answer is a cooperative one: a token the
runner sets and every long-running call site checks.

Two pieces live here (ADR 0047):

- `CancelToken` — a `threading.Event` plus a registry of the node threads
  currently executing for one job. The runner sets it on timeout /
  shutdown, then *drains*: it holds the job's semaphore permit until the
  registered threads actually return, so `api_max_concurrent_jobs` keeps
  bounding real concurrency instead of just bounding coroutines.
- A `ContextVar` binding, so `src.llm`, the reader's per-paper fan-out,
  and the node wrapper in `src.graph.workflow` can reach the token
  without threading a handle through every signature. Same shape as
  `_current_costs` in `src.observability.costs`.

When a drain expires the runner gives up and calls `abandon()`. The
thread is still out there, so the process-wide `abandoned_node_count()`
keeps counting it until it finally returns; `/healthz` folds that number
into `active_jobs` rather than reporting a concurrency figure it cannot
back up (ADR 0042's honesty rule, extended by ADR 0047).

Deliberately dependency-free (stdlib only) so the leaf modules that need
it — `src.llm`, the agents — can import it without pulling in the API
layer.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from contextvars import ContextVar, Token

__all__ = [
    "DRAIN_POLL_SEC",
    "CancelToken",
    "JobCancelledError",
    "abandoned_node_count",
    "bind_cancel_token",
    "check_cancelled",
    "current_cancel_token",
    "reset_cancel_token",
]


# How often `CancelToken.drain` re-reads the in-flight set while waiting.
# Polling rather than awaiting the executor futures directly: the futures
# are created deep inside LangGraph's Pregel loop and the drain has to
# work identically when the fallback (default) executor is in use, where
# no `concurrent.futures.Future` is reachable at all. 20ms is invisible
# next to a drain budget measured in seconds and only ever runs on the
# timeout / shutdown path.
DRAIN_POLL_SEC = 0.02


class JobCancelledError(Exception):
    """Raised by a cooperating call site once its job's token is set.

    Carries the job id and the reason the runner recorded (`job_timeout`,
    `shutdown`) so the abort is attributable in logs rather than looking
    like a spontaneous agent failure.
    """

    def __init__(self, job_id: str, reason: str) -> None:
        self.job_id = job_id
        self.reason = reason
        super().__init__(f"job {job_id} cancelled ({reason})")


# ---------------------------------------------------------------------------
# Process-wide zombie accounting
# ---------------------------------------------------------------------------

_abandoned_lock = threading.Lock()
_abandoned_nodes = 0


def _adjust_abandoned(delta: int) -> None:
    """Move the process-wide abandoned-thread counter by `delta`."""
    global _abandoned_nodes
    with _abandoned_lock:
        # Clamped at zero so an accounting bug degrades to "under-report
        # by one" instead of a negative concurrency figure on /healthz.
        _abandoned_nodes = max(0, _abandoned_nodes + delta)


def abandoned_node_count() -> int:
    """Node threads this worker gave up on that are still running.

    Incremented when a runner's drain budget expires with threads still
    executing, decremented when each of those threads finally returns.
    `/healthz` adds it to `active_jobs` so the reported concurrency
    stays honest about work the semaphore no longer covers.

    Returns:
        The current count, never negative.
    """
    with _abandoned_lock:
        return _abandoned_nodes


class CancelToken:
    """One job's cancellation signal plus its in-flight node registry.

    Thread-safe by construction: the runner sets and drains it from the
    event loop while node threads register, check and deregister against
    it from the pool.

    Attributes:
        job_id: Job this token belongs to; stamped on
            `JobCancelledError` and on the runner's drain logs.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()
        # handle -> node name, for the nodes currently executing.
        self._running: dict[int, str] = {}
        self._handles = itertools.count()
        self._abandoned = False

    # ---- signal ----------------------------------------------------

    def cancel(self, reason: str) -> None:
        """Set the token. Idempotent; the first reason wins.

        Args:
            reason: Short machine-readable cause (`job_timeout`,
                `shutdown`) surfaced on `JobCancelledError` and logs.
        """
        with self._lock:
            if not self._reason:
                self._reason = reason
        self._event.set()

    def is_cancelled(self) -> bool:
        """Whether the token has been set."""
        return self._event.is_set()

    @property
    def reason(self) -> str:
        """The reason recorded by the first `cancel` call, or `""`."""
        with self._lock:
            return self._reason

    def raise_if_cancelled(self) -> None:
        """Abort the caller when the token is set.

        Raises:
            JobCancelledError: When `cancel` has been called.
        """
        if self._event.is_set():
            raise JobCancelledError(self.job_id, self.reason or "cancelled")

    # ---- in-flight node registry -----------------------------------

    def enter_node(self, name: str) -> int:
        """Record that a node thread has started; returns its handle.

        Args:
            name: Graph node name, for the drain's log line.

        Returns:
            An opaque handle to pass back to `exit_node`.
        """
        with self._lock:
            handle = next(self._handles)
            self._running[handle] = name
            if self._abandoned:
                # Registered after the runner already gave up — count it
                # so the matching `exit_node` decrement stays balanced.
                _adjust_abandoned(1)
        return handle

    def exit_node(self, handle: int) -> None:
        """Record that a node thread has returned.

        Args:
            handle: The value `enter_node` returned. Unknown handles are
                ignored so a double-exit cannot corrupt the count.
        """
        with self._lock:
            if self._running.pop(handle, None) is None:
                return
            if self._abandoned:
                _adjust_abandoned(-1)

    def running_nodes(self) -> list[str]:
        """Names of the node threads executing right now, in start order."""
        with self._lock:
            return [self._running[h] for h in sorted(self._running)]

    async def drain(self, timeout_sec: float) -> list[str]:
        """Wait, bounded, for every registered node thread to return.

        Args:
            timeout_sec: Wall-clock budget. The caller is expected to be
                holding the job's semaphore permit for the duration —
                that is the entire point of draining.

        Returns:
            The nodes still running when the budget expired; empty when
            the drain completed (including the common case of nothing
            having been running at all).
        """
        deadline = time.monotonic() + timeout_sec
        while True:
            running = self.running_nodes()
            if not running:
                return []
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return running
            await asyncio.sleep(min(DRAIN_POLL_SEC, remaining))

    def abandon(self) -> list[str]:
        """Give up on the still-running threads and start counting them.

        Called only after `drain` expired. Every thread registered at
        this moment is added to the process-wide abandoned count and
        removes itself again when it returns.

        Returns:
            Names of the abandoned nodes; empty when the last thread
            happened to return between the drain giving up and this
            call, in which case there is no zombie to report.
        """
        with self._lock:
            self._abandoned = True
            names = [self._running[h] for h in sorted(self._running)]
            if names:
                _adjust_abandoned(len(names))
            return names


# ---------------------------------------------------------------------------
# Context binding
# ---------------------------------------------------------------------------

_current_cancel_token: ContextVar[CancelToken | None] = ContextVar(
    "current_cancel_token", default=None
)


def current_cancel_token() -> CancelToken | None:
    """The token for the job running in this context, or `None`."""
    return _current_cancel_token.get()


def bind_cancel_token(token: CancelToken) -> Token[CancelToken | None]:
    """Bind `token` to the current context; returns a reset handle.

    Idiomatic usage mirrors `bind_run_id`:

        scope = bind_cancel_token(CancelToken(job_id))
        try:
            ...
        finally:
            reset_cancel_token(scope)
    """
    return _current_cancel_token.set(token)


def reset_cancel_token(scope: Token[CancelToken | None]) -> None:
    """Restore the binding `bind_cancel_token` replaced."""
    _current_cancel_token.reset(scope)


def check_cancelled() -> None:
    """Abort the caller when the current job has been cancelled.

    A no-op when no token is bound, so the CLI, the eval runner and unit
    tests calling agents directly are unaffected.

    Raises:
        JobCancelledError: When the bound token is set.
    """
    token = _current_cancel_token.get()
    if token is not None:
        token.raise_if_cancelled()
