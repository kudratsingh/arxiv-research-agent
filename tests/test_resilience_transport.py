"""What the resilience policy does to a real HTTP call (ADR 0068).

`tests/test_resilience.py` proves the policy's arithmetic. This file
proves the wiring, against a loopback server that counts the requests it
receives — because the two claims that matter most here are claims about
*how many times the socket was used*, and no amount of mocking can make
those honestly:

- retries for one dependency happen at **one** level, so a failing arXiv
  query costs `http_max_retries + 1` requests and not
  `(http_max_retries + 1)^2`;
- an exhausted retry budget makes the chain stop at the first retry,
  and the failure that reaches the caller is still `upstream_arxiv`.

The server is bound to 127.0.0.1, which `tests/conftest.py`'s network
guard permits by design ("the integration tier needs this"). Nothing
here reaches the internet, and no request is ever paid for.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
import requests

import src.tools.arxiv_search as arxiv_module
import src.tools.http_session as http_session_module
from src.config import Settings
from src.resilience import DEPENDENCY_ARXIV, get_retry_budget, reset_retry_budgets
from src.tools.arxiv_search import ArxivUnavailableError, search_arxiv
from src.tools.http_session import build_retrying_session

pytestmark = [pytest.mark.integration, pytest.mark.fault]


ATOM_OK = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<entry>"
    "<id>http://arxiv.org/abs/2311.09000v1</id>"
    "<title>A Paper</title>"
    "<summary>An abstract.</summary>"
    '<author><name>A. Author</name></author>'
    '<link title="pdf" href="http://arxiv.org/pdf/2311.09000v1"/>'
    "</entry>"
    "</feed>"
)


class CountingServer:
    """A loopback HTTP server that counts requests and replays a script.

    `statuses` is consumed one entry per request; once it runs out the
    last entry repeats, so a test says "503 forever" by passing `[503]`
    and "fail once then succeed" by passing `[503, 200]`.
    """

    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses
        self.requests = 0
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
                with server._lock:
                    index = min(server.requests, len(server.statuses) - 1)
                    status = server.statuses[index]
                    server.requests += 1
                body = ATOM_OK.encode() if status == 200 else b"upstream is unwell"
                self.send_response(status)
                self.send_header("Content-Type", "application/atom+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                """Silence the handler's stderr narration."""

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/query"

    def __enter__(self) -> CountingServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _fresh_budgets() -> Iterator[None]:
    """The budget registry is process-wide; leaving a drained one behind
    would fail a later test in a file that never mentions retries."""
    reset_retry_budgets()
    yield
    reset_retry_budgets()


def _fast_settings(**overrides: Any) -> Settings:
    """Settings with the backoff removed so a retry chain runs instantly.

    `http_backoff_factor=0` makes every Full Jitter draw zero, which is
    the one knob a test may flatten without changing what is under test:
    the *count* of attempts is the claim, not the delay between them.
    """
    return Settings(
        use_mock_data=False,
        http_backoff_factor=0.0,
        **overrides,
    )


def _point_arxiv_at(
    monkeypatch: pytest.MonkeyPatch, server: CountingServer, settings: Settings
) -> None:
    monkeypatch.setattr(arxiv_module, "ARXIV_API_URL", server.url)
    monkeypatch.setattr(arxiv_module, "settings", settings)
    monkeypatch.setattr(http_session_module, "settings", settings)
    monkeypatch.setattr("src.resilience.settings", settings)


class TestRetriesHappenAtOneLevelOnly:
    """The largest finding in `01-BASELINE.md` §2, closed and measured.

    Retry amplification is multiplicative: three retries at five levels
    of a stack is 243x the load on a dependency that is already failing.
    The fix is not a mechanism, it is a decision — one owning level per
    dependency — and the only way to hold that decision is to count.
    """

    def test_a_failing_arxiv_query_costs_exactly_the_configured_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _fast_settings(http_max_retries=3, enable_retry_budget=False)
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)

            # 1 first attempt + 3 retries. A second retrying level
            # anywhere in the stack would show up here as 8 or 16.
            assert server.requests == 4

    def test_the_count_tracks_the_setting_rather_than_a_constant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards the assertion above against a coincidence: a hidden
        second level that happened to multiply by one."""
        settings = _fast_settings(http_max_retries=1, enable_retry_budget=False)
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)

            assert server.requests == 2

    def test_a_transient_failure_still_recovers_inside_one_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Consolidating levels must not remove retrying, only duplicate it."""
        settings = _fast_settings(http_max_retries=3, enable_retry_budget=False)
        with CountingServer([503, 200]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            papers = search_arxiv("anything", raise_on_unavailable=True)

            assert server.requests == 2
            assert [p["title"] for p in papers] == ["A Paper"]


class TestTheBudgetIsInvisibleUntilItIsNeeded:
    def test_a_full_budget_changes_nothing_about_a_healthy_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _fast_settings(enable_retry_budget=True)
        with CountingServer([200]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            papers = search_arxiv("anything", raise_on_unavailable=True)

            assert server.requests == 1
            assert len(papers) == 1

    def test_a_full_budget_changes_nothing_about_a_retried_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _fast_settings(http_max_retries=3, enable_retry_budget=True)
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)

            assert server.requests == 4

    def test_a_success_refunds_the_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _fast_settings(
            http_max_retries=3, enable_retry_budget=True, retry_budget_success_refund=0.2
        )
        with CountingServer([503, 200]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            budget = get_retry_budget(DEPENDENCY_ARXIV)
            assert budget is not None
            before = budget.tokens

            search_arxiv("anything", raise_on_unavailable=True)

            # One retry spent, one success refunded: net -0.8 tokens,
            # which is the ratio coupling the whole design rests on.
            assert budget.tokens == pytest.approx(before - 0.8, abs=0.05)

    def test_an_upstream_answer_that_is_a_refusal_earns_no_refund(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A steady stream of 503s must not keep the bucket topped up."""
        settings = _fast_settings(http_max_retries=1, enable_retry_budget=True)
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            budget = get_retry_budget(DEPENDENCY_ARXIV)
            assert budget is not None
            before = budget.tokens

            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)

            assert budget.tokens < before


class TestAnExhaustedBudgetFailsFast:
    def test_the_chain_stops_at_the_first_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measured problem, closed: during an outage every job used
        to pay its full retry envelope before failing."""
        settings = _fast_settings(
            http_max_retries=3,
            enable_retry_budget=True,
            retry_budget_capacity=1,
            retry_budget_refill_per_sec=0.0001,
        )
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            budget = get_retry_budget(DEPENDENCY_ARXIV)
            assert budget is not None

            # First call: one token, so one retry — two requests.
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)
            assert server.requests == 2
            assert budget.tokens == pytest.approx(0.0, abs=0.01)

            # Second call: no tokens left, so the first attempt is not
            # retried at all — one request, not four.
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)
            assert server.requests == 3

    def test_the_failure_is_still_an_upstream_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failing fast must not fail *differently*: a budget changes
        when arXiv's outage is reported, not what it is."""
        settings = _fast_settings(
            http_max_retries=3,
            enable_retry_budget=True,
            retry_budget_capacity=1,
            retry_budget_refill_per_sec=0.0001,
        )
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("anything", raise_on_unavailable=True)

            with pytest.raises(ArxivUnavailableError) as caught:
                search_arxiv("anything", raise_on_unavailable=True)

        assert caught.value.code == "upstream_arxiv"
        assert caught.value.retryable is True

    def test_the_historical_empty_list_contract_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Callers that never opted into `raise_on_unavailable` still get `[]`."""
        settings = _fast_settings(
            http_max_retries=3,
            enable_retry_budget=True,
            retry_budget_capacity=1,
            retry_budget_refill_per_sec=0.0001,
        )
        with CountingServer([503]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            search_arxiv("anything")
            assert search_arxiv("anything") == []

    def test_the_budget_is_charged_per_retry_and_not_per_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A budget that charged first attempts would be a circuit breaker."""
        settings = _fast_settings(
            http_max_retries=3, enable_retry_budget=True, retry_budget_refill_per_sec=0.0001
        )
        with CountingServer([200]) as server:
            _point_arxiv_at(monkeypatch, server, settings)
            budget = get_retry_budget(DEPENDENCY_ARXIV)
            assert budget is not None
            budget.on_success()  # top it up so the refund below cannot mask a spend
            before = budget.tokens

            for _ in range(5):
                search_arxiv("anything", raise_on_unavailable=True)

            assert server.requests == 5
            assert budget.tokens == pytest.approx(before)


class TestTheBudgetSurvivesUrllib3sInternalCopying:
    def test_the_policy_object_still_carries_its_budget_after_a_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`Retry.new` rebuilds from a fixed parameter list.

        Without the `new` override the budget silently becomes `None` on
        the first retry — the bucket would look wired and would never
        charge anything, which is the kind of bug a test that only
        asserts "no exception" would never see.
        """
        settings = _fast_settings(enable_retry_budget=True)
        monkeypatch.setattr(http_session_module, "settings", settings)
        monkeypatch.setattr("src.resilience.settings", settings)

        session = build_retrying_session(dependency=DEPENDENCY_ARXIV)
        policy = session.get_adapter("http://127.0.0.1/").max_retries
        assert isinstance(policy, http_session_module.BudgetedRetry)

        copied = policy.new()

        assert copied.budget is policy.budget
        assert copied.budget is get_retry_budget(DEPENDENCY_ARXIV)


class TestTheApplicationAddsNoLoopOfItsOwn:
    def test_a_transport_failure_is_not_retried_by_the_arxiv_wrapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of "one owning level": the level above must be
        empty. Counted at `session.get`, which is below the wrapper and
        above urllib3."""
        calls = 0

        class OneShotSession:
            def get(self, *args: Any, **kwargs: Any) -> Any:
                nonlocal calls
                calls += 1
                raise requests.ConnectionError("down")

        monkeypatch.setattr(
            arxiv_module, "build_retrying_session", lambda **_kw: OneShotSession()
        )

        with pytest.raises(ArxivUnavailableError):
            search_arxiv("anything", raise_on_unavailable=True)

        assert calls == 1
