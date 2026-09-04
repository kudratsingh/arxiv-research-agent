"""Two call chains that could outlive the job they belong to.

ADR 0068 established the rule this file enforces: a call chain's worst
case is `(attempts) x (per-attempt timeout)`, and nothing may issue one
whose worst case does not fit its share of `api_job_timeout_sec`. It
also recorded, as follow-ups 3 and 4, the two places on `main` that
still did — both in files that work order did not own.

The fault being injected in both cases is **slowness**, which is the
one fault this tier cannot inject by waiting: a test that actually
burned 600 seconds proving a 600-second budget is a test nobody runs.
So each test injects the *arithmetic* instead — a settings object whose
declared timeouts make the worst case unaffordable, or a first attempt
whose measured elapsed time has already spent the budget — and asserts
the decision that arithmetic is supposed to produce. That is the whole
observable: a call that is not made, and a WARNING that says why.

| fault | decision | event |
|---|---|---|
| the synthesizer's first attempt returns something unusable, late | no second call | `synthesizer_retry_budget_exhausted` |
| the same, but early | the retry happens | `synthesizer_retrying_malformed_response` |
| a PDF timeout the job budget cannot afford four attempts of | retries trimmed | `retry_envelope_clamped` |
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import requests

from src import llm as llm_module
from src.agents import synthesizer as synth_module
from src.config import Settings
from src.tools import http_session as http_module
from src.tools import pdf_parser as pdf_module

pytestmark = [pytest.mark.unit, pytest.mark.fault]

#: A response the synthesizer must treat as unusable. Empty
#: `draft_report` is the `max_tokens`-truncation signature, and it is
#: the failure the corrective retry exists to rescue — so it is the one
#: that has to still be tried when the budget allows it.
_UNUSABLE: dict[str, Any] = {"draft_report": "", "citations": []}

#: What a rescued retry returns.
_USABLE: dict[str, Any] = {"draft_report": "## Report", "citations": []}


class _CountingLlm:
    """Stands in for `call_llm_json`, counting calls and timing them.

    `elapsed_sec` is what the first attempt *reports* having taken, not
    what it takes: the clock the synthesizer reads is
    `time.monotonic`, so the double advances a fake one rather than
    sleeping. A tier that proved a ten-minute budget by waiting ten
    minutes would be a tier nobody ran.
    """

    def __init__(self, *, responses: list[dict[str, Any]], elapsed_sec: float) -> None:
        self.calls = 0
        self._responses = responses
        self._elapsed_sec = elapsed_sec
        self.now = 0.0

    def __call__(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        # Only the first attempt is charged: the question the clamp
        # answers is "does another one fit after what has already been
        # spent", and a second charge would be measuring the answer.
        if self.calls == 1:
            self.now += self._elapsed_sec
        return self._responses[min(self.calls, len(self._responses)) - 1]


def _install_llm(
    monkeypatch: pytest.MonkeyPatch, fake: _CountingLlm, **overrides: Any
) -> None:
    """Point the synthesizer at `fake`, with a pinned settings pair.

    Both handles have to be pinned. `_second_attempt_fits` reads the
    job budget off the synthesizer's own `settings`, while
    `_retry_envelope` reads the model's timeout and retry count off
    `src.llm`'s — the module that builds the client. Patching one and
    not the other produces a half-overridden run whose result means
    nothing, which is the failure mode `tests/e2e/conftest.py` documents
    at length.
    """
    monkeypatch.setattr(synth_module, "call_llm_json", fake)
    monkeypatch.setattr(synth_module.time, "monotonic", lambda: fake.now)
    pinned = Settings(**overrides)
    monkeypatch.setattr(synth_module, "settings", pinned)
    monkeypatch.setattr(llm_module, "settings", pinned)


def _pin_http(monkeypatch: pytest.MonkeyPatch, *, pdf_download_timeout_sec: float) -> None:
    """Pin both settings handles on the PDF download path, and cut the wire.

    `pdf_parser` supplies the per-attempt timeout and `http_session`
    owns the budget the retries are trimmed against, so both handles
    have to carry the same object or the arithmetic under test is half
    the test's and half the shipped default's.

    The session is built for real — that build *is* the decision being
    asserted — and the request that would follow it is what raises, so
    nothing in this tier reaches the network.
    """
    pinned = Settings(
        api_job_timeout_sec=600,
        http_max_retries=3,
        http_call_chain_budget_fraction=0.25,
        pdf_download_timeout_sec=pdf_download_timeout_sec,
    )
    monkeypatch.setattr(pdf_module, "settings", pinned)
    monkeypatch.setattr(http_module, "settings", pinned)

    real_builder = pdf_module.build_retrying_session

    def _build_then_refuse(**kwargs: Any) -> requests.Session:
        session = real_builder(**kwargs)
        session.get = _refuse  # type: ignore[method-assign]
        return session

    monkeypatch.setattr(pdf_module, "build_retrying_session", _build_then_refuse)


def _refuse(*_args: Any, **_kwargs: Any) -> Any:
    """Every request this tier would otherwise put on the network."""
    raise requests.ConnectionError("no network in this tier")


class TestTheSynthesizersSecondAttempt:
    """ADR 0068 follow-up 3, on the retry that survived consolidation.

    `_call_with_one_retry` re-prompts once on an unusable response. It
    is a *semantic* retry — a different prompt, not the same request —
    so WO-A04 kept it deliberately: it is the only thing that rescues a
    `max_tokens` truncation, and the fan-out that paid for the analyses
    has already been billed. What it lacked was a bound. `src/llm.py`
    clamps one call chain against the job budget and cannot see that
    this node makes the call twice, so the worst case was 2 x 5 x 120s
    against a 600s job.
    """

    def test_a_late_first_attempt_spends_the_budget_and_the_retry_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No second call, and a WARNING carrying the arithmetic.

        The failure the run ends with is unchanged —
        `SynthesizerOutputError`, the honest "the report is the product
        and there is none" — so what this bound changes is only
        *when* the job learns it: at the moment the budget ran out,
        rather than two minutes later as a timeout with the same
        outcome and a worse error code.
        """
        fake = _CountingLlm(responses=[_UNUSABLE], elapsed_sec=400.0)
        _install_llm(monkeypatch, fake, api_job_timeout_sec=600)

        with (
            caplog.at_level(logging.WARNING, logger="src.agents.synthesizer"),
            pytest.raises(synth_module.SynthesizerOutputError),
        ):
            synth_module._call_with_one_retry("prompt", "system")

        assert fake.calls == 1
        record = next(
            r
            for r in caplog.records
            if r.message == "synthesizer_retry_budget_exhausted"
        )
        # 400s spent, 0.75 x 600s = 450s allowed, and one more clamped
        # chain is 3 x 120s. The line has to carry all three or an
        # operator cannot tell which knob refused the retry.
        assert record.elapsed_sec == 400.0  # type: ignore[attr-defined]
        assert record.budget_sec == pytest.approx(450.0)  # type: ignore[attr-defined]
        assert record.worst_case_request_sec > 0.0  # type: ignore[attr-defined]
        assert (
            record.elapsed_sec + record.worst_case_request_sec  # type: ignore[attr-defined]
            > record.budget_sec  # type: ignore[attr-defined]
        )
        # The retry it skipped never announced itself.
        assert not [
            r
            for r in caplog.records
            if r.message == "synthesizer_retrying_malformed_response"
        ]

    def test_a_fast_first_attempt_still_gets_its_corrective_retry(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The half that makes the bound a bound rather than a deletion.

        A clamp that refused the retry on a healthy run would not be
        conservative, it would be the removal WO-A04 explicitly declined
        to make: this is the call that turns a truncated response into a
        delivered report, and on a normal run there is most of a job
        budget left when it is asked for.
        """
        fake = _CountingLlm(responses=[_UNUSABLE, _USABLE], elapsed_sec=9.0)
        _install_llm(monkeypatch, fake, api_job_timeout_sec=600)

        with caplog.at_level(logging.WARNING, logger="src.agents.synthesizer"):
            parsed = synth_module._call_with_one_retry("prompt", "system")

        assert parsed == _USABLE
        assert fake.calls == 2
        assert [
            r
            for r in caplog.records
            if r.message == "synthesizer_retrying_malformed_response"
        ]
        assert not [
            r
            for r in caplog.records
            if r.message == "synthesizer_retry_budget_exhausted"
        ]

    def test_the_worst_case_it_budgets_for_is_the_one_the_client_was_built_with(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The number cannot drift from `src/llm.py`'s own clamp.

        `_worst_case_call_sec` imports `_retry_envelope` rather than
        re-deriving it, and this is what that buys: a second copy of the
        arithmetic would agree until someone changed one of them, and
        the symptom would be a retry budget that quietly stopped
        matching the client it was budgeting for.
        """
        monkeypatch.setattr(
            llm_module,
            "settings",
            Settings(
                api_job_timeout_sec=600,
                anthropic_timeout_sec=120.0,
                anthropic_max_retries=4,
            ),
        )

        max_retries, timeout_sec = llm_module._retry_envelope()

        # 0.75 x 600 = 450s of budget buys three 120s attempts, so the
        # configured four retries are trimmed to two.
        assert (max_retries, timeout_sec) == (2, 120.0)
        assert synth_module._worst_case_call_sec() == 360.0


class TestThePdfDownloadChain:
    """ADR 0068 follow-up 4, on the last hardcoded timeout.

    `DOWNLOAD_TIMEOUT_SEC = 60` was a module constant, so nothing
    declared it to `build_retrying_session` and the clamp had nothing to
    trim against: four attempts x 60s, per redirect hop, inside a 600s
    job. It is now `settings.pdf_download_timeout_sec` and it is
    declared.
    """

    def test_a_timeout_the_budget_cannot_afford_trims_the_retries(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        """The retries are trimmed, and the WARNING names the dependency.

        Asserted through `_download_pdf` rather than through
        `build_retrying_session` directly, because the defect was never
        in the session builder — it was that this call site did not tell
        it anything. A test of the builder would have passed on the
        broken code.
        """
        _pin_http(monkeypatch, pdf_download_timeout_sec=60.0)

        with caplog.at_level(logging.WARNING):
            # False, not an exception: a download that cannot complete
            # is a graceful fall back to the abstract, which is exactly
            # why the retry envelope had to be bounded somewhere other
            # than at the caller.
            assert (
                pdf_module._download_pdf(
                    "https://arxiv.org/pdf/2311.09000", tmp_path / "p.pdf"
                )
                is False
            )

        record = next(
            r for r in caplog.records if r.message == "retry_envelope_clamped"
        )
        # 0.25 x 600 = 150s affords two 60s attempts, so three
        # configured retries become one.
        assert record.max_retries == 1  # type: ignore[attr-defined]
        assert record.configured_max_retries == 3  # type: ignore[attr-defined]
        assert record.timeout_sec == 60.0  # type: ignore[attr-defined]
        assert record.worst_case_request_sec == 120.0  # type: ignore[attr-defined]
        assert record.budget_sec == pytest.approx(150.0)  # type: ignore[attr-defined]

    def test_a_timeout_the_budget_can_afford_leaves_the_retries_alone(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Path,
    ) -> None:
        """The clamp is a bound, not a policy, and it must stay silent.

        A clamp that fired on every configuration would be a retry count
        the operator no longer controls, and a WARNING nobody reads. At
        20s per attempt the full envelope fits, so nothing is trimmed
        and nothing is logged.
        """
        _pin_http(monkeypatch, pdf_download_timeout_sec=20.0)

        with caplog.at_level(logging.WARNING):
            assert (
                pdf_module._download_pdf(
                    "https://arxiv.org/pdf/2311.09000", tmp_path / "p.pdf"
                )
                is False
            )

        assert not [
            r for r in caplog.records if r.message == "retry_envelope_clamped"
        ]
