"""What the fault tier itself is allowed to assert on.

Every other module here asserts a *failure*. This one asserts the
tier's own three vocabularies, so that the rest of the directory cannot
quietly drift out of the registries it claims to be enforcing:

- the instrument names it uses all exist on this branch;
- the exact attribute shape of the job counter, pinned in **one** place;
- the codes it names are in `ERROR_CODES`, and the job-level ones are
  in the `JOB_ERROR_TYPES` subset the frontend derives its copy from.

The middle one is the load-bearing entry and the reason this module
exists. WO-A07 is adding a `kind` attribute to the job metrics in this
same wave, and `TripleObserver.point` deliberately matches on named
attributes rather than on the whole set so that change does not turn
fifteen assertions red. The whole-set claim still has to live
somewhere or nothing would notice an attribute arriving unannounced —
so it lives here, as a single failure with a single fix.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.api.jobs import InMemoryJobStore, Job
from src.api.runner import run_job
from src.errors import (
    ERROR_CODES,
    JOB_ERROR_TYPES,
    AppError,
    BudgetExceededRun,
    JobCancelled,
    JobOrphaned,
    UpstreamPaperRead,
)
from src.observability import metrics as metrics_module
from src.observability.logging import KNOWN_EVENTS

from .conftest import LIVE_INSTRUMENTS, ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]

#: Every log event any test in this directory asserts on. Written out
#: rather than scraped, for the same reason `ERROR_CODES` and the SSE
#: contract are written out: a contract that derives itself from its
#: subject pins nothing.
ASSERTED_EVENTS: frozenset[str] = frozenset(
    {
        "api_job_cancelled",
        "api_job_cost_budget_exceeded",
        "api_job_failed",
        "api_job_terminal_persist_failed",
        "api_job_terminal_persist_retry",
        "api_request_failed",
        "api_request_rejected",
        "conversation_append_failed",
        "embedding_cache_get_failed",
        "job_redriver_reclaimed",
        "llm_upstream_error",
        "sse_publish_failed",
        "sse_terminal_publish_failed",
        "sse_terminal_publish_gave_up",
    }
)

#: Every code this directory names as a job outcome.
ASSERTED_JOB_CODES: frozenset[str] = frozenset(
    {
        AppError.code,
        BudgetExceededRun.code,
        JobCancelled.code,
        JobOrphaned.code,
        UpstreamPaperRead.code,
    }
)


class TestTheVocabulariesThisTierAssertsOn:
    def test_every_event_this_tier_asserts_on_is_registered(self) -> None:
        """A typo'd event name is a test that can never fail.

        `TripleObserver.one_record` would catch it the first time it
        ran, but only for events a test actually reaches. This catches
        the ones a future edit stops reaching.
        """
        assert ASSERTED_EVENTS <= KNOWN_EVENTS

    def test_every_instrument_this_tier_asserts_on_exists_today(
        self, triple: TripleObserver
    ) -> None:
        """The alias promise, checked from the consumer's side.

        WO-A07 renames these to the OpenTelemetry GenAI conventions and
        keeps the current names as aliases for one release. Driving
        every record helper and reading the names back out is what
        makes this a check on the *module* rather than on a list
        somebody remembered to update — and it is what will fail, with
        an obvious cause, on the day the alias window closes.
        """
        metrics_module.record_job_terminal(
            status="succeeded", error_type=None, duration_sec=1.0
        )
        metrics_module.record_llm_usage(model="m", cost_usd=0.01)
        metrics_module.record_llm_retries(model="m", retries=1)
        metrics_module.record_llm_upstream_error(model="m", status="500")
        metrics_module.record_rate_limit_rejection(backend="memory")

        assert triple.instrument_names() >= LIVE_INSTRUMENTS

    def test_every_code_this_tier_names_is_in_the_closed_set(self) -> None:
        assert ASSERTED_JOB_CODES <= ERROR_CODES

    def test_every_job_outcome_this_tier_names_is_in_the_job_subset(self) -> None:
        """`JOB_ERROR_TYPES` is what the frontend's copy dictionary is
        derived from, so a run that ends with a code outside it renders
        as an unmapped error in the product."""
        assert ASSERTED_JOB_CODES <= JOB_ERROR_TYPES


class TestTheShapeOfTheJobCounter:
    async def test_the_job_series_carries_exactly_status_and_error_type(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """The one whole-attribute-set assertion in this directory.

        An attribute added to `research_jobs_total` is a new series:
        every existing dashboard query, alert rule and recording rule
        keyed on the old shape stops matching, and the symptom is a
        panel that silently goes flat rather than an error anybody
        sees. So the shape gets pinned — once, here, where a deliberate
        change is one line to update and an accidental one is a red
        test with an obvious cause.

        WO-A07 adds `kind` to this set. When it lands, this assertion
        gains `"kind"` and nothing else in `tests/fault/` moves.

        It landed (ADR 0066), and it moved *both* assertions below
        rather than the one this docstring predicted: `kind` is on the
        duration histogram too. That is a different judgement from the
        `error_type` one, not an inconsistency with it. Splitting
        duration by error type divides an already-thin histogram a
        dozen ways to answer a question nobody asks. Splitting it by
        `kind` divides it in exactly two, and the two halves are
        genuinely different distributions — a research job is minutes
        of graph, a guided-read session runs at a learner's pace — so
        merging them leaves p95 meaningless for both, which is exactly
        why no session SLO could be built before.
        """
        job = Job(job_id="shape", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)
        await run_job(
            job,
            scripted_workflow(updates=[{"synthesizer": {"draft_report": "# R"}}]),
            store,
            asyncio.Semaphore(1),
        )

        points = triple.points("research_jobs_total")
        assert len(points) == 1
        assert set(dict(points[0].attributes)) == {"status", "error_type", "kind"}

        timed = triple.points("research_job_duration_seconds")
        assert len(timed) == 1
        # Deliberately *not* keyed on `error_type`: the duration
        # question is "how long do failures take", not "how long does
        # each kind of failure take", and splitting it would divide an
        # already-thin histogram across a dozen series. `kind` is the
        # one split worth paying for — see the docstring.
        assert set(dict(timed[0].attributes)) == {"status", "kind"}

    def test_the_no_error_sentinel_is_a_literal_not_an_omission(self) -> None:
        """A missing key would make success a different series shape.

        `sum by (status)` over `research_jobs_total` has to work across
        succeeded and failed alike; if the success series simply
        omitted `error_type`, it would need a separate query per
        outcome.
        """
        assert metrics_module.NO_ERROR == "none"
