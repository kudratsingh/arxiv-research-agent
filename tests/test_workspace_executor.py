"""Executable fake generation over real isolated Postgres; never paid inference."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from psycopg.types.json import Jsonb

from src.workspace import executor as x
from src.workspace.admission import AdmissionError, GenerationAdmission
from src.workspace.schemas import EntryData, EntryWrite, ProfileData, ProfileWrite
from src.workspace.store import ConflictError
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = pytest.mark.integration


def source(store, version=1, **changes):
    item = support.ingest(store, version, **changes)
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT material_id,data FROM workspace_material WHERE version_id=%s",
            (item["version_id"],),
        ).fetchone()
    return item, row[0], row[1]


def queued(store, kind="summary", *, owner="a", request_id="one", version=1):
    _, material, _ = source(store, version)
    executor = x.FakeExecutor(store)
    preview = executor.preview(owner, kind, [material])
    return (
        executor,
        material,
        executor.submit(
            owner, request_id, kind, [material], expected_digest=preview.request_digest
        ),
    )


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
def test_retained_source_to_sealed_draft_checks_and_persisted_fake_result(store, kind):
    executor, material, job = queued(store, kind)
    assert job.state == x.FakeJobState.QUEUED and not job.result
    assert job.request["selection"]["material_ids"] == [material]
    assert job.request["private_context"] == {
        "notes": False,
        "reading_history": False,
        "profile": False,
    }
    assert job.request["question"] == ""
    assert all(contract["output_schema"] for contract in job.request["stage_contracts"].values())
    result = executor.run_to_terminal("a", job.id)
    assert result.state == x.FakeJobState.READY
    assert result.result and result.result.mode == "fake"
    assert (
        result.result.model_id == x.MODEL_ID
        and "not a calibrated judge" in result.result.check_basis
    )
    assert result.grounding["supported"] == 1 and result.grounding["unsupported"] == 0
    assert result.usage.workflow.input_tokens > 0 and result.usage.checker.input_tokens > 0
    assert result.usage.workflow.output_tokens > 0 and result.usage.checker.output_tokens > 0
    assert result.usage.used_calls == 2 and result.usage.actual_usd == "0.000000"
    assert result.usage.unknown.input_tokens == result.usage.unknown.output_tokens == 0
    assert [step.phase for step in result.steps] == ["draft", "check"]
    assert all(step.state == "completed" and step.response for step in result.steps)
    assert all(x._hash(step.request) == step.request_digest for step in result.steps)
    assert x.FakeExecutor(store).get("a", job.id) == result
    assert executor.run_to_terminal("a", job.id) == result
    assert executor.cancel("a", job.id) == result
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM workspace_spend_reservations").fetchone()[0] == 0
    if kind == "deep_dive":
        assert {"method", "assumptions", "experiment"} <= result.draft.sections.keys()


def test_preview_excludes_private_notes_profile_and_history_unless_question_explicit(store):
    item, material, _ = source(store)
    store.write_profile(
        "a",
        ProfileWrite(
            revision=0,
            request_id="profile",
            data=ProfileData(research_question="DO NOT SEND THIS PRIVATE QUESTION"),
        ),
    )
    store.write_entry(
        "a",
        EntryWrite(
            id="private",
            revision=0,
            request_id="private",
            data=EntryData(
                work_id=item["work_id"],
                version_id=item["version_id"],
                kind="note",
                body="DO NOT SEND THIS PRIVATE NOTE",
            ),
        ),
    )
    executor = x.FakeExecutor(store)
    preview = executor.preview("a", "summary", [material])
    assert "DO NOT SEND" not in preview.model_dump_json()
    explicit = executor.preview(
        "a", "summary", [material], question="My explicit local fake question"
    )
    assert explicit.request["question"] == "My explicit local fake question"
    assert explicit.request_digest != preview.request_digest
    assert preview.actual_usd == "0.000000" and "not provider tokens" in preview.usage_basis
    with pytest.raises(ConflictError):
        executor.submit(
            "a",
            "changed",
            "summary",
            [material],
            expected_digest=preview.request_digest,
            question="Changed since preview",
        )
    assert executor.list("a") == []


def test_idempotent_submission_cache_owner_and_new_version_invalidation(store):
    executor, material, job = queued(store)
    replay = executor.submit("a", "one", "summary", [material], expected_digest=job.request_digest)
    assert replay.id == job.id
    ready = executor.run_to_terminal("a", job.id)
    cached = executor.submit("a", "two", "summary", [material], expected_digest=job.request_digest)
    assert cached.cached and cached.id == ready.id
    other = executor.submit("b", "two", "summary", [material], expected_digest=job.request_digest)
    assert other.id != ready.id and not other.cached
    _, revised, _ = source(store, 2)
    current = executor.preview("a", "summary", [revised])
    assert current.request_digest != job.request_digest
    fresh = executor.submit(
        "a", "three", "summary", [revised], expected_digest=current.request_digest
    )
    assert not fresh.cached and fresh.id != ready.id
    assert ready.result.draft.claims[0].evidence[0].version_id.endswith("v1")
    assert len(executor.list("a")) == 2
    with pytest.raises(x.ExecutorError, match="not_found"):
        executor.get("b", ready.id)
    with pytest.raises(x.ExecutorError, match="not_found"):
        executor.cancel("b", ready.id)
    altered = executor.preview("a", "summary", [material], question="Other request")
    with pytest.raises(ConflictError):
        executor.submit(
            "a",
            "one",
            "summary",
            [material],
            expected_digest=altered.request_digest,
            question="Other request",
        )


class FalseFirst(x.FakeProvider):
    def draft(self, request, *, cancelled):
        draft = super().draft(request, cancelled=cancelled)
        draft["claims"][0]["text"] = "The source proves an invented 999 percent improvement."
        return draft

    def repair(self, request, *, cancelled):
        return x.FakeProvider.draft(self, request, cancelled=cancelled)


class StillFalse(FalseFirst):
    def repair(self, request, *, cancelled):
        return self.draft(request, cancelled=cancelled)


@pytest.mark.parametrize("provider,state", [(FalseFirst(), "ready"), (StillFalse(), "failed")])
def test_false_cited_claim_needs_bounded_repair_and_recheck(store, provider, state):
    executor, _, job = queued(store)
    result = executor.run_to_terminal("a", job.id, provider=provider)
    assert result.state.value == state
    assert [step.phase for step in result.steps] == ["draft", "check", "repair", "check"]
    assert result.usage.used_calls == 4
    assert result.steps[1].response["checks"][0]["decision"] == "unsupported"
    assert result.usage.checker.input_tokens > 0 and result.usage.workflow.input_tokens > 0
    if state == "ready":
        assert result.grounding["supported"] == 1 and result.result
    else:
        assert result.grounding["unsupported"] == 1 and not result.result
        assert result.error == "unsupported_claims_after_bounded_repair"
    assert executor.run_to_terminal("a", job.id, provider=provider) == result


def test_scope_abstention_and_labelled_inference_are_not_verified_facts(store):
    class Methods(x.FakeProvider):
        def draft(self, request, *, cancelled):
            draft = super().draft(request, cancelled=cancelled)
            draft["claims"][0]["required_scope"] = "full_text"
            draft["claims"][0]["required_section"] = "methods"
            return draft

    executor, material, job = queued(store)
    partial = executor.run_to_terminal("a", job.id, provider=Methods())
    assert partial.state == x.FakeJobState.READY_PARTIAL
    assert partial.grounding["abstained"] == 1 and partial.grounding["support_ratio"] is None
    assert partial.grounding["assessments"][0]["reason"] == "source_scope_insufficient"
    assert partial.usage.used_calls == 2

    class Inferences(x.FakeProvider):
        def draft(self, request, *, cancelled):
            draft = super().draft(request, cancelled=cancelled)
            draft["claims"][0].update(
                kind="inference", inference_label="Hypothesis, not a factual finding"
            )
            return draft

    preview = executor.preview("a", "summary", [material], question="Different input")
    inference = executor.submit(
        "a",
        "inference",
        "summary",
        [material],
        expected_digest=preview.request_digest,
        question="Different input",
    )
    result = executor.run_to_terminal("a", inference.id, provider=Inferences())
    assert result.state == x.FakeJobState.READY_PARTIAL
    assert result.grounding["total_factual"] == 0 and result.grounding["inference_count"] == 1
    assert result.grounding["support_ratio"] is None


def test_restart_between_completed_steps_never_repeats_draft(store):
    class Counter(x.FakeProvider):
        drafts = 0
        checks = 0

        def draft(self, request, *, cancelled):
            self.drafts += 1
            return super().draft(request, cancelled=cancelled)

        def check(self, request, *, cancelled):
            self.checks += 1
            return super().check(request, cancelled=cancelled)

    executor, _, job = queued(store)
    provider = Counter()
    middle = executor.advance("a", job.id, provider=provider)
    assert middle.state == x.FakeJobState.CHECKING and middle.draft and middle.lease_until is None
    result = x.FakeExecutor(store).run_to_terminal("a", job.id, provider=provider)
    assert result.state == x.FakeJobState.READY
    assert (provider.drafts, provider.checks) == (1, 1)


def test_process_loss_becomes_unknown_without_blind_retry(store):
    class Crash(x.FakeProvider):
        def draft(self, request, *, cancelled):
            raise SystemExit("simulated process loss")

    executor, _, job = queued(store)
    now = datetime.fromisoformat(store.cutoff())
    with pytest.raises(SystemExit):
        executor.advance("a", job.id, provider=Crash(), now=now, worker="lost")
    running = executor.get("a", job.id)
    assert running.state == x.FakeJobState.DRAFTING and running.usage.used_calls == 1
    assert executor.recover("a", job.id, now=now) == running
    recovered = executor.recover("a", job.id, now=now + timedelta(seconds=x.LEASE_SECONDS + 1))
    assert recovered.state == x.FakeJobState.INTERRUPTED and not recovered.result
    assert recovered.steps[0].state == "interrupted"
    assert recovered.usage.unknown.input_tokens == recovered.steps[0].input_tokens
    assert (
        recovered.usage.unknown.output_tokens == running.request["limits"]["per_call_output_tokens"]
    )
    assert recovered.usage.actual_usd == "0.000000"
    assert executor.advance("a", job.id) == recovered
    assert executor.recover("a", job.id, now=now + timedelta(days=1)) == recovered


def test_queued_between_stages_and_inflight_cancellation_preserve_usage(store):
    executor, _, job = queued(store)
    cancelled = executor.cancel("a", job.id)
    assert cancelled.state == x.FakeJobState.CANCELLED and cancelled.usage.used_calls == 0
    assert executor.run_to_terminal("a", job.id) == cancelled
    _, material, _ = source(store)
    preview = executor.preview("a", "summary", [material], question="Between steps")
    between = executor.submit(
        "a",
        "between",
        "summary",
        [material],
        question="Between steps",
        expected_digest=preview.request_digest,
    )
    draft = executor.advance("a", between.id)
    stopped = executor.cancel("a", between.id)
    assert stopped.draft == draft.draft and stopped.usage == draft.usage
    assert stopped.state == x.FakeJobState.CANCELLED and not stopped.result
    preview = executor.preview("a", "summary", [material], question="Inside stage")
    inside = executor.submit(
        "a",
        "inside",
        "summary",
        [material],
        question="Inside stage",
        expected_digest=preview.request_digest,
    )

    class Cancel(x.FakeProvider):
        def draft(self, request, *, cancelled):
            pending = executor.cancel("a", inside.id)
            assert pending.cancel_requested and pending.usage.unknown.input_tokens > 0
            return super().draft(request, cancelled=cancelled)

    result = executor.advance("a", inside.id, provider=Cancel())
    assert result.state == x.FakeJobState.CANCELLED and result.usage.used_calls == 1
    assert result.usage.workflow.input_tokens > 0 and result.usage.workflow.output_tokens == 0
    assert result.usage.unknown.input_tokens == result.usage.unknown.output_tokens == 0
    assert not result.result


def test_concurrent_workers_hold_no_lock_through_provider_and_never_duplicate_call(store):
    executor, _, job = queued(store)
    entered, release = Event(), Event()

    class Waiting(x.FakeProvider):
        calls = 0

        def draft(self, request, *, cancelled):
            self.calls += 1
            entered.set()
            assert release.wait(10)
            return super().draft(request, cancelled=cancelled)

    provider = Waiting()
    with ThreadPoolExecutor(max_workers=2) as workers:
        future = workers.submit(executor.advance, "a", job.id, provider=provider, worker="first")
        assert entered.wait(10)
        try:
            other = executor.run_to_terminal("a", job.id, provider=provider, worker="second")
            assert other.state == x.FakeJobState.DRAFTING and other.usage.used_calls == 1
        finally:
            release.set()
        assert future.result(timeout=10).state == x.FakeJobState.CHECKING
    assert provider.calls == 1
    assert executor.run_to_terminal("a", job.id).usage.used_calls == 2


def test_request_mutation_source_tampering_and_bad_checker_are_not_published(store):
    class Mutates(x.FakeProvider):
        def draft(self, request, *, cancelled):
            request["sealed_request"]["settings"]["temperature"] = 1
            return super().draft(request, cancelled=cancelled)

    executor, material, job = queued(store)
    result = executor.advance("a", job.id, provider=Mutates())
    assert (
        result.state == x.FakeJobState.FAILED
        and result.error == "fake_provider_mutated_sealed_request"
    )
    assert not result.result
    preview = executor.preview("a", "summary", [material], question="Source drift")
    stale = executor.submit(
        "a",
        "stale",
        "summary",
        [material],
        question="Source drift",
        expected_digest=preview.request_digest,
    )
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT data FROM workspace_material WHERE material_id=%s", (material,)
        ).fetchone()
        data = row[0]
        data["pages"][0] += " altered"
        conn.execute(
            "UPDATE workspace_material SET data=%s WHERE material_id=%s", (Jsonb(data), material)
        )
    refused = executor.advance("a", stale.id)
    assert refused.state == x.FakeJobState.STALE and refused.usage.used_calls == 0


def test_bounded_selection_never_silently_truncates_or_leaks_other_owner(store):
    _, material, data = source(store, abstract="long source " * 1000)
    executor = x.FakeExecutor(store)
    with pytest.raises(x.ExecutorError, match="too_large"):
        executor.preview("a", "summary", [material])
    span = data["spans"][0]
    preview = executor.preview("a", "summary", [material], span_ids=[span["span_id"]])
    retained = preview.request["sources"][0]["spans"]
    assert len(retained) == 1 and retained[0]["text"] == span["text"]
    assert preview.request["selection"]["span_ids"] == [span["span_id"]]
    with pytest.raises(x.ExecutorError, match="span_not"):
        executor.preview("a", "summary", [material], span_ids=["unknown"])
    private_store = store
    # A different immutable version can be private only in a separate work.
    item = support.item(
        1, work_id="private:work", version_id="private:work:v1", visibility_owner="a"
    )
    private_store.ingest("arxiv-cs-ai", [item], {"status": "success"}, {})
    with store.pool.connection() as conn:
        private = conn.execute(
            "SELECT material_id FROM workspace_material WHERE version_id='private:work:v1'"
        ).fetchone()[0]
    with pytest.raises(x.ExecutorError, match="missing_or_private"):
        executor.preview("b", "summary", [private])


def test_fake_and_paid_lanes_never_share_approval_records_or_accept_paid_adapter(
    store, monkeypatch
):
    executor, material, job = queued(store)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-credential")
    with pytest.raises(x.ExecutorError, match="disabled_key"):
        executor.advance("a", job.id)
    with pytest.raises(x.ExecutorError, match="disabled_key"):
        executor.submit("a", "new", "summary", [material], expected_digest=job.request_digest)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    with pytest.raises(x.ExecutorError, match="local_fake_provider"):
        executor.advance("a", job.id, provider=Mock())
    from tests.test_workspace_admission import inputs

    with pytest.raises(AdmissionError, match="owner_approval_required"):
        GenerationAdmission(store).reserve("a", "paid", inputs(store), "0.1")


@pytest.mark.parametrize("failure", ["exception", "invalid_json", "non_object", "oversized"])
def test_provider_failure_shapes_preserve_usage_and_never_publish(store, failure):
    class Broken(x.FakeProvider):
        def draft(self, request, *, cancelled):
            if failure == "exception":
                raise RuntimeError("private details must not appear in error")
            if failure == "invalid_json":
                return {"not_serializable": object()}
            if failure == "non_object":
                return ["unexpected but serializable response"]
            reply = super().draft(request, cancelled=cancelled)
            reply["questions"] = ["x" * 40000]
            return reply

    executor, _, job = queued(store)
    result = executor.advance("a", job.id, provider=Broken())
    assert not result.result and result.usage.used_calls == 1
    assert result.usage.workflow.input_tokens > 0
    assert "private details" not in result.model_dump_json()
    if failure in {"exception", "invalid_json"}:
        assert result.state == x.FakeJobState.FAILED and result.error == "fake_provider_error"
        assert result.usage.unknown.output_tokens == job.request["limits"]["per_call_output_tokens"]
    elif failure == "non_object":
        assert result.error == "invalid_fake_response" and result.usage.workflow.output_tokens > 0
        assert result.usage.unknown.output_tokens == 0
    else:
        assert result.state == x.FakeJobState.BUDGET_STOPPED
        assert result.usage.workflow.output_tokens > job.request["limits"]["per_call_output_tokens"]
        assert result.steps[0].response is None


@pytest.mark.parametrize(
    "defect",
    [
        "unknown_section",
        "unknown_claim",
        "duplicate_claim",
        "blank_question",
        "wrong_kind",
        "unselected_span",
        "missing_evidence",
        "factual_title",
        "factual_limitation",
    ],
)
def test_malformed_or_unbound_factual_draft_never_becomes_ready(store, defect):
    class Invalid(x.FakeProvider):
        def draft(self, request, *, cancelled):
            reply = super().draft(request, cancelled=cancelled)
            if defect == "unknown_section":
                reply["sections"] = {"unchecked_factual_prose": ("quote-1",)}
            elif defect == "unknown_claim":
                reply["sections"] = {"overview": ("not-an-emitted-claim",)}
            elif defect == "duplicate_claim":
                reply["claims"].append(reply["claims"][0])
            elif defect == "blank_question":
                reply["questions"] = [" "]
            elif defect == "wrong_kind":
                reply["kind"] = "deep_dive"
            elif defect == "unselected_span":
                reply["claims"][0]["evidence"][0]["span_id"] = "not-selected"
            elif defect == "factual_title":
                reply["title"] = "The uncited method proves 999 percent improvement"
            elif defect == "factual_limitation":
                reply["limitations"] = ["The uncited experiment proves a perfect score"]
            else:
                reply["claims"][0]["evidence"] = []
            return reply

    executor, _, job = queued(store)
    result = executor.advance("a", job.id, provider=Invalid())
    assert result.state == x.FakeJobState.FAILED and result.error == "invalid_fake_draft_or_checks"
    assert not result.result and result.usage.workflow.output_tokens > 0
    assert result.usage.checker.input_tokens == 0


@pytest.mark.parametrize(
    "defect", ["missing", "wrong_checker", "wrong_revision", "wrong_input", "malformed"]
)
def test_checker_cannot_skip_claims_or_change_bound_instrument(store, defect):
    class InvalidChecker(x.FakeProvider):
        def check(self, request, *, cancelled):
            reply = super().check(request, cancelled=cancelled)
            if defect == "missing":
                reply["checks"] = []
            elif defect == "malformed":
                reply["checks"] = "not-a-verdict-batch"
            else:
                key = {
                    "wrong_checker": "checker_id",
                    "wrong_revision": "checker_revision",
                    "wrong_input": "input_digest",
                }[defect]
                reply["checks"][0][key] = "changed"
            return reply

    executor, _, job = queued(store)
    result = executor.run_to_terminal("a", job.id, provider=InvalidChecker())
    assert result.state == x.FakeJobState.FAILED and not result.result
    assert result.usage.used_calls == 2 and result.usage.checker.output_tokens > 0
    assert result.error == "invalid_fake_draft_or_checks"


def test_default_repair_rechecks_when_fixture_checker_initially_rejects(store):
    class RejectOnce(x.FakeProvider):
        checks = 0

        def check(self, request, *, cancelled):
            reply = super().check(request, cancelled=cancelled)
            self.checks += 1
            if self.checks == 1:
                reply["checks"][0]["decision"] = "unsupported"
            return reply

    executor, _, job = queued(store)
    result = executor.run_to_terminal("a", job.id, provider=RejectOnce())
    assert result.state == x.FakeJobState.READY
    assert result.usage.used_calls == 4 and result.grounding["supported"] == 1


@pytest.mark.parametrize("budget", ["calls", "input", "output"])
def test_runtime_reservation_envelope_stops_before_next_provider_step(store, budget):
    executor, _, job = queued(store)
    executor.advance("a", job.id)
    with store.pool.connection() as conn:
        assignment = {
            "calls": "max_calls=1",
            "input": "max_input_tokens=1",
            "output": "max_output_tokens=1",
        }[budget]
        conn.execute(
            "UPDATE workspace_fake_generation_reservations SET " + assignment + " WHERE job_id=%s",
            (job.id,),
        )
    provider = x.FakeProvider()
    provider.check = Mock(side_effect=AssertionError("budget stopped before provider"))
    stopped = executor.advance("a", job.id, provider=provider)
    assert stopped.state == x.FakeJobState.BUDGET_STOPPED
    assert stopped.usage.used_calls == 1 and not stopped.result
    assert stopped.draft and stopped.usage.workflow.input_tokens > 0
    provider.check.assert_not_called()


def test_late_response_after_recovery_or_lease_expiry_cannot_publish(store):
    executor, _, job = queued(store)
    now = datetime.fromisoformat(store.cutoff())

    class Recovered(x.FakeProvider):
        def draft(self, request, *, cancelled):
            reply = super().draft(request, cancelled=cancelled)
            executor.recover("a", job.id, now=now + timedelta(seconds=x.LEASE_SECONDS + 1))
            return reply

    lost = executor.advance("a", job.id, provider=Recovered(), now=now)
    assert lost.state == x.FakeJobState.INTERRUPTED and not lost.result
    assert lost.usage.unknown.output_tokens > 0 and lost.usage.workflow.output_tokens == 0
    # A completion whose lease elapsed is fenced even without a second worker.
    executor, _, expiring = queued(store, request_id="expiring")

    class Expires(x.FakeProvider):
        def draft(self, request, *, cancelled):
            reply = super().draft(request, cancelled=cancelled)
            with store.pool.connection() as conn:
                conn.execute(
                    "UPDATE workspace_fake_generation_jobs SET lease_until=%s WHERE id=%s",
                    (now - timedelta(seconds=1), expiring.id),
                )
            return reply

    expired = executor.advance("a", expiring.id, provider=Expires(), now=now)
    assert expired.state == x.FakeJobState.INTERRUPTED and not expired.result
    assert expired.usage.unknown.input_tokens > 0


def test_advance_recovers_expired_work_and_cancelled_loss_keeps_unknown_once(store):
    executor, _, job = queued(store)
    now = datetime.fromisoformat(store.cutoff())

    class Crash(x.FakeProvider):
        def draft(self, request, *, cancelled):
            raise SystemExit()

    with pytest.raises(SystemExit):
        executor.advance("a", job.id, provider=Crash(), now=now)
    lost = executor.advance("a", job.id, now=now + timedelta(seconds=x.LEASE_SECONDS + 1))
    assert lost.state == x.FakeJobState.INTERRUPTED
    executor, _, stopped = queued(store, request_id="cancel-and-loss")

    class CancelCrash(x.FakeProvider):
        def draft(self, request, *, cancelled):
            executor.cancel("a", stopped.id)
            raise SystemExit()

    with pytest.raises(SystemExit):
        executor.advance("a", stopped.id, provider=CancelCrash(), now=now)
    before = executor.get("a", stopped.id)
    after = executor.recover("a", stopped.id, now=now + timedelta(seconds=x.LEASE_SECONDS + 1))
    assert after.state == x.FakeJobState.CANCELLED and after.usage == before.usage
    assert after.steps[0].state == "interrupted"


def test_source_drift_during_a_stage_is_fenced_at_completion(store):
    executor, material, job = queued(store)

    class Drift(x.FakeProvider):
        def draft(self, request, *, cancelled):
            reply = super().draft(request, cancelled=cancelled)
            with store.pool.connection() as conn:
                value = conn.execute(
                    "SELECT data FROM workspace_material WHERE material_id=%s", (material,)
                ).fetchone()[0]
                value["pages"][0] += " altered while drafting"
                conn.execute(
                    "UPDATE workspace_material SET data=%s WHERE material_id=%s",
                    (Jsonb(value), material),
                )
            return reply

    result = executor.advance("a", job.id, provider=Drift())
    assert result.state == x.FakeJobState.STALE and not result.result
    assert result.usage.workflow.input_tokens > 0


@pytest.mark.parametrize(
    "selection", [[], [""], ["x" * 301], ["same", "same"], ["1", "2", "3", "4"]]
)
def test_invalid_material_selection_refuses_without_creating_jobs(store, selection):
    with pytest.raises(x.ExecutorError, match="invalid_material_selection"):
        x.FakeExecutor(store).preview("a", "summary", selection)
    assert x.FakeExecutor(store).list("a") == []


def test_invalid_requests_empty_material_and_span_selection_are_explicit(store):
    executor, material, job = queued(store)
    for kind, question in (("other", ""), ("summary", "x" * 4001)):
        with pytest.raises(x.ExecutorError, match="invalid_fake_request"):
            executor.preview("a", kind, [material], question=question)
    for spans in (("",), ("same", "same")):
        with pytest.raises(x.ExecutorError, match="invalid_span_selection"):
            executor.preview("a", "summary", [material], span_ids=spans)
    for request_id in ("", "x" * 121):
        with pytest.raises(x.ExecutorError, match="invalid_request_id"):
            executor.submit(
                "a", request_id, "summary", [material], expected_digest=job.request_digest
            )
    with pytest.raises(x.ExecutorError, match="invalid_owner"):
        executor.list("a" * 121)
    for limit in (0, 101, True):
        with pytest.raises(x.ExecutorError, match="invalid_job_limit"):
            executor.list("a", limit)
    with pytest.raises(x.ExecutorError, match="aware_clock_required"):
        executor.advance("a", job.id, now=datetime(2026, 1, 1))
    _, empty, _ = source(store, 2, abstract="")
    with pytest.raises(x.ExecutorError, match="source_text_required"):
        executor.preview("a", "summary", [empty])


def test_full_input_envelope_and_unicode_byte_bounds_refuse_without_truncating(store, monkeypatch):
    _, material, data = source(store, abstract="🚀" * 2200)
    executor = x.FakeExecutor(store)
    with pytest.raises(x.ExecutorError, match="too_large_choose_spans"):
        executor.preview("a", "summary", [material])
    one = data["spans"][0]["span_id"]
    assert (
        len(
            executor.preview("a", "summary", [material], span_ids=[one]).request["sources"][0][
                "spans"
            ]
        )
        == 1
    )
    _, second, _ = source(store, 2, abstract="Second material")
    with pytest.raises(x.ExecutorError, match="no_selected_span"):
        executor.preview("a", "summary", [material, second], span_ids=[one])
    original = x._limits
    monkeypatch.setattr(
        x, "_limits", lambda kind: original(kind).model_copy(update={"per_call_input_tokens": 100})
    )
    with pytest.raises(x.ExecutorError, match="sealed_request_too_large"):
        executor.preview("a", "summary", [second])


@pytest.mark.parametrize("defect", ["identity", "shape", "request"])
def test_persisted_material_or_sealed_request_corruption_fails_closed(store, defect):
    executor, material, job = queued(store)
    with store.pool.connection() as conn:
        if defect == "request":
            request = job.request.copy()
            request["settings"] = {"temperature": 99}
            conn.execute(
                "UPDATE workspace_fake_generation_jobs SET request=%s WHERE id=%s",
                (Jsonb(request), job.id),
            )
        else:
            value = conn.execute(
                "SELECT data FROM workspace_material WHERE material_id=%s", (material,)
            ).fetchone()[0]
            if defect == "identity":
                value["material_id"] = "invented-id"
            else:
                value.pop("pages")
            conn.execute(
                "UPDATE workspace_material SET data=%s WHERE material_id=%s",
                (Jsonb(value), material),
            )
    result = executor.advance("a", job.id)
    assert result.state == x.FakeJobState.STALE and result.usage.used_calls == 0
    assert not result.result


def test_selected_pdf_page_retains_original_page_mapping_and_exact_quotes_through_result(store):
    from dataclasses import asdict

    from src.workspace.material import extract_pdf
    from tests.test_workspace_material import sample_pdf

    item, _, _ = source(store)
    material = extract_pdf(
        sample_pdf(), work_id=item["work_id"], version_id=item["version_id"], page_numbers=[2]
    )
    assert material.page_numbers == (2,) and material.spans[0].page == 2
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
            (
                material.material_id,
                material.version_id,
                material.content_hash,
                material.scope,
                Jsonb(asdict(material)),
            ),
        )
    executor = x.FakeExecutor(store)
    preview = executor.preview("a", "deep_dive", [material.material_id])
    retained = preview.request["sources"][0]
    assert retained["page_numbers"] == [2] and retained["page_count"] == 2
    assert retained["warnings"] == list(material.warnings)
    assert retained["spans"][0]["page"] == 2
    job = executor.submit(
        "a",
        "selected-pdf",
        "deep_dive",
        [material.material_id],
        expected_digest=preview.request_digest,
    )
    result = executor.run_to_terminal("a", job.id)
    assert result.state == x.FakeJobState.READY
    ref = result.result.draft.claims[0].evidence[0]
    assert ref.page == 2 and ref.quote == material.pages[0][ref.start : ref.end]
    assert ref.version_id == item["version_id"] and ref.source_hash == material.source_hash
    assert result.grounding["supported"] == 1


@pytest.mark.parametrize("terminal", ["cancelled", "stale"])
def test_failed_completion_stays_unknown_after_cancellation_or_source_drift(store, terminal):
    executor, material, job = queued(store)

    class FailingCompletion(x.FakeProvider):
        calls = 0

        def draft(self, request, *, cancelled):
            self.calls += 1
            if terminal == "cancelled":
                pending = executor.cancel("a", job.id)
                assert pending.usage.unknown.input_tokens > 0
                assert pending.usage.unknown.output_tokens > 0
            else:
                with store.pool.connection() as conn:
                    payload = conn.execute(
                        "SELECT data FROM workspace_material WHERE material_id=%s", (material,)
                    ).fetchone()[0]
                    payload["pages"][0] += " changed during unresolved completion"
                    conn.execute(
                        "UPDATE workspace_material SET data=%s WHERE material_id=%s",
                        (Jsonb(payload), material),
                    )
            raise RuntimeError("completion unavailable; private diagnostic must stay private")

    provider = FailingCompletion()
    result = executor.advance("a", job.id, provider=provider)
    assert result.state.value == terminal and result.result is None
    assert result.usage.used_calls == 1 and result.usage.workflow.input_tokens > 0
    assert result.usage.workflow.output_tokens == result.usage.unknown.input_tokens == 0
    assert result.usage.unknown.output_tokens == job.request["limits"]["per_call_output_tokens"]
    assert result.error == (
        "cancelled" if terminal == "cancelled" else "sealed_request_or_source_drift"
    )
    assert "private diagnostic" not in result.model_dump_json()
    assert executor.get("a", job.id) == result
    assert executor.run_to_terminal("a", job.id, provider=provider) == result
    assert provider.calls == 1
    with store.pool.connection() as conn:
        assert conn.execute(
            "SELECT state,actual_usd FROM workspace_fake_generation_reservations WHERE job_id=%s",
            (job.id,),
        ).fetchone() == ("uncertain", 0)
