"""The CAP-06 funded smoke, classified against a fake provider.

ADR 0090 closed with five things about Anthropic's behaviour that no test
in this repository can establish, because the model is faked above the
HTTP layer. That is still true and this module does not pretend
otherwise: what it tests is the **classifier** — that each probe reads
the right field, calls the right outcome, and puts the right number in
the receipt — so that when the script is finally pointed at a credential,
the thing it reports is the thing it observed.

The fake client is deliberately the same shape
`tests/test_llm.py`'s is: a raw response carrying `retries_taken` and
`request_id`, a parsed message carrying `content`, `usage` and the three
descriptive fields the span reads. A double that omits a field the code
reads is a double that tests a different function than the one that ships.

Four groups.

1. **The refusals, before a client exists.** The sentinel, an absent
   credential, a non-positive cap, and a missing or non-covering approval
   record — each raised before anything could have constructed a client
   or spent a cent.
2. **The five probes.** One test per ADR 0090 bullet, each driving the
   fake to the behaviour that bullet is about and asserting the
   classification.
3. **The receipt.** Its schema, its arithmetic, and the `passed` /
   `unverified` rule — including that `not_observed` is acceptable for
   exactly the two probes that declare it and fatal everywhere else.
4. **The CLI verb.** `python -m src.campaign smoke` refuses without an
   approval id, and needs no `--campaign-id` — under the repository's
   zero-spend sentinel it refuses at the credential, which is the proof
   that it got past the campaign-id gate rather than being stopped by it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

import src.llm as llm_module
from src.campaign.approval import LocalApprovalRecordBackend, campaign_approval_record
from src.campaign.cli import EXIT_REFUSED, main
from src.campaign.errors import CampaignError
from src.campaign.smoke import (
    MAY_BE_UNOBSERVED,
    SMOKE_CAMPAIGN_ID,
    SMOKE_PROBES,
    SMOKE_PROVIDER,
    SMOKE_STAGE,
    SmokeProbe,
    SmokeReceipt,
    render_receipt,
    run_smoke,
)
from src.config import Settings
from src.contracts.run_manifest import ApprovalRecord
from tests.test_campaign_execution import config


#: A model whose capability row allows structured outputs, so probe 4 can
#: be *observed* rather than skipped. Read from the table rather than
#: hard-coded to a guess, because the row is what `resolve_profile` reads.
def _structured_model() -> str:
    from src.llm_models import MODEL_CAPABILITIES

    for model, caps in MODEL_CAPABILITIES.items():
        if caps.structured_outputs:
            return model
    raise AssertionError("no model in MODEL_CAPABILITIES takes structured outputs")


#: A model id `src/llm_models.py` does not describe. Every id the table
#: *does* describe takes structured outputs today, so the only way to
#: reach probe 4's `not_observed` branch is the conservative fallback —
#: which is also the realistic case, an operator pointing a campaign at
#: an id nobody has added a row for yet.
UNDESCRIBED_MODEL = "claude-not-in-the-capability-table"


def _unstructured_model() -> str:
    from src.llm_models import capabilities_for

    assert not capabilities_for(UNDESCRIBED_MODEL).structured_outputs
    return UNDESCRIBED_MODEL


def smoke_config(**overrides: Any) -> Settings:
    """Settings the smoke will consent to run under.

    The key is a placeholder that is deliberately not `sk-`-shaped: a
    credential-shaped string in a fixture is one copy-paste from an
    artifact body, which the ADR 0096 screen would refuse.
    """
    base: dict[str, Any] = {
        "use_mock_data": False,
        "anthropic_api_key": SecretStr("cap06-smoke-test-key"),
        "anthropic_model": _structured_model(),
        "enable_structured_outputs": True,
    }
    return config(**{**base, **overrides})


def approval_record(
    *,
    cap: str = "1.000000",
    campaign_id: str = SMOKE_CAMPAIGN_ID,
    stage: str = SMOKE_STAGE,
) -> ApprovalRecord:
    """One record, built the way an operator preparing one builds it."""
    return campaign_approval_record(
        approval_id="approval_cap06-smoke",
        campaign_id=campaign_id,
        stage=stage,
        provider=SMOKE_PROVIDER,
        total_cost_usd_max=cap,
        episode_allocation_usd_max=cap,
        workflow_allocation_usd_max=cap,
        judge_allocation_usd_max="0.000000",
        approved_by="owner",
        approved_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )


def approval(**overrides: Any) -> LocalApprovalRecordBackend:
    """A backend holding exactly that record."""
    return LocalApprovalRecordBackend([approval_record(**overrides)])


def approval_file(path: Path, **overrides: Any) -> Path:
    """The JSON array `--approval-records` reads, written to disk."""
    path.write_text(
        "[" + approval_record(**overrides).model_dump_json() + "]", encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# The fake provider
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(
        self,
        *,
        input_tokens: int = 120,
        output_tokens: int = 40,
        cache: bool = True,
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if cache:
            self.cache_read_input_tokens = cache_read
            self.cache_creation_input_tokens = cache_creation


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Message:
    def __init__(self, text: str, usage: _Usage, model: str) -> None:
        self.content = [_Block(text)]
        self.usage = usage
        self.id = "msg_smoke"
        self.model = model
        self.stop_reason = "end_turn"


class _Raw:
    def __init__(self, parsed: _Message, retries: int, request_id: str) -> None:
        self._parsed = parsed
        self.retries_taken = retries
        self.request_id = request_id

    def parse(self) -> _Message:
        return self._parsed


class _RawMessages:
    def __init__(self, parent: _Messages) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _Raw:
        return self._parent.create(**kwargs)


class _Messages:
    def __init__(self, client: _FakeProvider) -> None:
        self._client = client
        self.with_raw_response = _RawMessages(self)

    def create(self, **kwargs: Any) -> _Raw:
        self._client.requests.append(kwargs)
        if int(kwargs.get("max_tokens") or 0) <= 0:
            raise _status_error(self._client.induced_status, "req_induced_4xx")
        usage = _Usage(
            cache=self._client.cache_buckets,
            cache_read=self._client.cache_read,
            cache_creation=self._client.cache_creation,
        )
        text = (
            '{"verdict": "wet", "confidence": 91}'
            if "output_config" in kwargs
            else "ok"
        )
        return _Raw(
            _Message(text, usage, str(kwargs.get("model") or "")),
            self._client.retries_taken,
            f"req_{len(self._client.requests):04d}",
        )


class _FakeProvider:
    """Everything the gateway reads off a client, and nothing else."""

    def __init__(
        self,
        *,
        retries_taken: int = 0,
        cache_buckets: bool = True,
        cache_read: int = 0,
        cache_creation: int = 900,
        induced_status: int = 400,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.retries_taken = retries_taken
        self.cache_buckets = cache_buckets
        self.cache_read = cache_read
        self.cache_creation = cache_creation
        self.induced_status = induced_status
        self.messages = _Messages(self)
        self.base_url = httpx.URL("https://api.anthropic.com")


def _status_error(status_code: int, request_id: str) -> Exception:
    """A real `anthropic.APIStatusError`, as `tests/test_llm.py` builds one."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        status_code,
        request=request,
        headers={"request-id": request_id},
        json={"error": {"type": "invalid_request_error"}},
    )
    return llm_module.anthropic.APIStatusError(
        "max_tokens must be positive", response=response, body=None
    )


def install(monkeypatch: pytest.MonkeyPatch, fake: _FakeProvider) -> _FakeProvider:
    """Install a fake SDK class, leaving `_get_client`'s own body running.

    The second of `tests/conftest.py`'s two documented fake-installation
    styles, and the one this module needs. Replacing `_get_client`
    outright would also replace the memoised `_client` the smoke's
    recording wrapper is installed into — so the wrapper would be built,
    stored, and then bypassed by the very next call, and every probe
    would report `None` for the fields it exists to read. Patching the
    SDK class instead leaves the real construction path — the sentinel
    check, the retry clamp, the memo — exactly where the funded smoke
    will find it.
    """
    monkeypatch.setattr(llm_module.anthropic, "Anthropic", lambda **_kwargs: fake)
    monkeypatch.setattr(llm_module, "_client", None)
    return fake


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _FakeProvider:
    """A fake provider behind the gateway's real client constructor."""
    return install(monkeypatch, _FakeProvider())


def _probe_of(receipt: SmokeReceipt, name: str) -> SmokeProbe:
    return next(probe for probe in receipt.probes if probe.probe == name)


# ---------------------------------------------------------------------------
# 1. The refusals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTheSmokeRefusesBeforeConstructingAClient:
    """Every refusal happens before anything could have spent."""

    def test_the_zero_spend_sentinel_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        constructed: list[str] = []
        monkeypatch.setattr(
            llm_module, "_get_client", lambda: constructed.append("client")
        )
        with pytest.raises(CampaignError, match="local-preview-disabled"):
            run_smoke(
                smoke_config(anthropic_api_key=SecretStr("local-preview-disabled")),
                approval_id="approval_cap06-smoke",
                cap_usd="1.000000",
                approval_backend=approval(),
            )
        assert not constructed

    def test_an_absent_credential_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        constructed: list[str] = []
        monkeypatch.setattr(
            llm_module, "_get_client", lambda: constructed.append("client")
        )
        with pytest.raises(CampaignError, match="needs a provider credential"):
            run_smoke(
                smoke_config(anthropic_api_key=SecretStr("")),
                approval_id="approval_cap06-smoke",
                cap_usd="1.000000",
                approval_backend=approval(),
            )
        assert not constructed

    def test_a_zero_cap_is_refused(self, provider: _FakeProvider) -> None:
        with pytest.raises(CampaignError, match="positive --cap-usd"):
            run_smoke(
                smoke_config(),
                approval_id="approval_cap06-smoke",
                cap_usd="0.000000",
                approval_backend=approval(),
            )
        assert not provider.requests

    def test_an_empty_approval_backend_is_refused(
        self, provider: _FakeProvider
    ) -> None:
        """Possessing a key is never authorization (RFC 09 §10.2)."""
        with pytest.raises(CampaignError, match="does not cover this plan"):
            run_smoke(
                smoke_config(),
                approval_id="approval_cap06-smoke",
                cap_usd="1.000000",
                approval_backend=LocalApprovalRecordBackend(),
            )
        assert not provider.requests

    def test_a_record_for_another_campaign_does_not_cover_the_smoke(
        self, provider: _FakeProvider
    ) -> None:
        """The smoke has a campaign id of its own, and the record names it."""
        with pytest.raises(CampaignError, match="does not cover this plan"):
            run_smoke(
                smoke_config(),
                approval_id="approval_cap06-smoke",
                cap_usd="1.000000",
                approval_backend=approval(campaign_id="camp_some_research_campaign"),
            )
        assert not provider.requests

    def test_a_record_too_small_for_the_cap_does_not_cover_it(
        self, provider: _FakeProvider
    ) -> None:
        with pytest.raises(CampaignError, match="does not cover this plan"):
            run_smoke(
                smoke_config(),
                approval_id="approval_cap06-smoke",
                cap_usd="50.000000",
                approval_backend=approval(cap="1.000000"),
            )
        assert not provider.requests


# ---------------------------------------------------------------------------
# 2. The five probes
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTheFiveProbes:
    """One test per ADR 0090 bullet, driven to the behaviour it is about."""

    @staticmethod
    def _run(**overrides: Any) -> SmokeReceipt:
        return run_smoke(
            smoke_config(**overrides.pop("settings", {})),
            approval_id="approval_cap06-smoke",
            cap_usd=str(overrides.pop("cap_usd", "1.000000")),
            approval_backend=approval(cap="1.000000"),
            **overrides,
        )

    def test_all_five_probes_are_reported_in_the_declared_order(
        self, provider: _FakeProvider
    ) -> None:
        receipt = self._run()
        assert tuple(probe.probe for probe in receipt.probes) == SMOKE_PROBES

    def test_probe_one_reads_the_usage_the_cost_table_is_derived_from(
        self, provider: _FakeProvider
    ) -> None:
        probe = _probe_of(self._run(), "round-trip-usage")
        assert probe.outcome == "passed"
        assert probe.input_tokens == 120
        assert probe.output_tokens == 40
        assert probe.request_id is not None
        assert float(probe.cost_usd) > 0.0

    def test_probe_one_fails_when_usage_reports_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zero tokens on a 2xx would silently price every call at nothing."""
        install(monkeypatch, _FakeProvider())
        monkeypatch.setattr(
            _Messages,
            "create",
            lambda self, **kwargs: _Raw(
                _Message("ok", _Usage(input_tokens=0, output_tokens=0), "m"),
                0,
                "req_zero",
            ),
        )
        probe = _probe_of(self._run(), "round-trip-usage")
        assert probe.outcome == "failed"
        assert "input_tokens=0" in probe.detail

    def test_probe_two_is_not_observed_when_nothing_retried(
        self, provider: _FakeProvider
    ) -> None:
        """A healthy provider does not retry, and that is not a failure."""
        probe = _probe_of(self._run(), "retries-taken")
        assert probe.outcome == "not_observed"
        assert probe.retries == 0
        assert "healthy provider" in probe.detail

    def test_probe_two_passes_when_the_sdk_reports_a_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, _FakeProvider(retries_taken=2))
        probe = _probe_of(self._run(), "retries-taken")
        assert probe.outcome == "passed"
        assert probe.retries == 2

    def test_probe_two_fails_when_the_field_is_gone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 2.x rename would leave the gateway recording nothing, silently."""
        install(monkeypatch, _FakeProvider())

        class _NoRetries(_Raw):
            def __init__(self, parsed: _Message, retries: int, request_id: str) -> None:
                super().__init__(parsed, retries, request_id)
                del self.retries_taken

        monkeypatch.setattr(
            _Messages,
            "create",
            lambda self, **kwargs: _NoRetries(
                _Message("ok", _Usage(), "m"), 0, "req_noretries"
            )
            if int(kwargs.get("max_tokens") or 0) > 0
            else _raise_induced(),
        )
        probe = _probe_of(self._run(), "retries-taken")
        assert probe.outcome == "failed"
        assert "retries_taken" in probe.detail

    def test_probe_three_passes_when_both_cache_buckets_arrive(
        self, provider: _FakeProvider
    ) -> None:
        probe = _probe_of(self._run(), "prompt-cache-buckets")
        assert probe.outcome == "passed"
        assert "cache_read_input_tokens" in probe.detail
        assert probe.cache_creation_input_tokens == 900

    def test_probe_three_fails_when_a_bucket_is_renamed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The silence this probe exists to break: cached calls priced as misses."""
        install(monkeypatch, _FakeProvider(cache_buckets=False))
        probe = _probe_of(self._run(), "prompt-cache-buckets")
        assert probe.outcome == "failed"
        assert "priced as a miss" in probe.detail

    def test_probe_four_sends_the_transformed_schema_and_validates_the_answer(
        self, provider: _FakeProvider
    ) -> None:
        receipt = self._run()
        probe = _probe_of(receipt, "structured-output")
        assert probe.outcome == "passed"
        assert "transform_schema" in probe.detail
        schema_requests = [
            request
            for request in provider.requests
            if "output_config" in request
            and "format" in request.get("output_config", {})
        ]
        assert len(schema_requests) == 1
        assert schema_requests[0]["output_config"]["format"]["type"] == "json_schema"

    def test_probe_four_is_not_observed_on_a_model_that_cannot_take_a_schema(
        self, provider: _FakeProvider
    ) -> None:
        probe = _probe_of(
            self._run(settings={"anthropic_model": _unstructured_model()}),
            "structured-output",
        )
        assert probe.outcome == "not_observed"
        assert "does not take structured outputs" in probe.detail

    def test_probe_five_surfaces_the_status_and_the_request_id(
        self, provider: _FakeProvider
    ) -> None:
        probe = _probe_of(self._run(), "induced-4xx-request-id")
        assert probe.outcome == "passed"
        assert probe.http_status == 400
        assert probe.request_id == "req_induced_4xx"

    def test_probe_five_costs_nothing(self, provider: _FakeProvider) -> None:
        """`max_tokens=0` is refused before any generation, so nothing is billed."""
        probe = _probe_of(self._run(), "induced-4xx-request-id")
        assert probe.cost_usd == "0.000000"

    def test_probe_five_fails_when_the_induced_failure_does_not_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, _FakeProvider())
        monkeypatch.setattr(
            _Messages,
            "create",
            lambda self, **kwargs: _Raw(
                _Message("ok", _Usage(), "m"), 0, "req_accepted"
            ),
        )
        probe = _probe_of(self._run(), "induced-4xx-request-id")
        assert probe.outcome == "failed"
        assert "was accepted" in probe.detail

    def test_probe_five_fails_when_the_status_is_not_a_4xx(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, _FakeProvider(induced_status=503))
        probe = _probe_of(self._run(), "induced-4xx-request-id")
        assert probe.outcome == "failed"
        assert probe.http_status == 503


def _raise_induced() -> Any:
    raise _status_error(400, "req_induced_4xx")


# ---------------------------------------------------------------------------
# 3. The receipt
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTheReceipt:
    """Its schema, its arithmetic, and what `passed` actually means."""

    @staticmethod
    def _receipt(**overrides: Any) -> SmokeReceipt:
        return run_smoke(
            smoke_config(),
            approval_id="approval_cap06-smoke",
            cap_usd="1.000000",
            approval_backend=approval(),
            **overrides,
        )

    def test_it_is_written_where_it_was_asked_for_and_validates(
        self, provider: _FakeProvider, tmp_path: Path
    ) -> None:
        path = tmp_path / "receipts" / "cap06.json"
        receipt = self._receipt(receipt_path=path)
        assert path.is_file()
        reloaded = SmokeReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        assert reloaded == receipt
        assert reloaded.schema_kind == "campaign-cap06-smoke-receipt"
        assert reloaded.campaign_id == SMOKE_CAMPAIGN_ID
        assert reloaded.stage == SMOKE_STAGE
        assert reloaded.approval_id == "approval_cap06-smoke"
        assert reloaded.approval_record_digest.startswith("sha256:")
        assert reloaded.sdk_version

    def test_the_total_is_the_calls_the_probes_actually_made(
        self, provider: _FakeProvider
    ) -> None:
        receipt = self._receipt()
        assert receipt.model_calls == 3, "three 2xx calls; the induced 4xx bills nothing"
        assert float(receipt.total_cost_usd) == pytest.approx(
            sum(float(probe.cost_usd) for probe in receipt.probes)
        )
        assert receipt.cap_reached is False

    def test_not_observed_is_acceptable_for_exactly_two_probes(
        self, provider: _FakeProvider
    ) -> None:
        receipt = self._receipt()
        assert _probe_of(receipt, "retries-taken").outcome == "not_observed"
        assert receipt.passed is True
        assert receipt.unverified == ()
        assert {"retries-taken", "structured-output"} == MAY_BE_UNOBSERVED

    def test_a_failed_probe_makes_the_receipt_not_pass_and_names_itself(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, _FakeProvider(cache_buckets=False))
        receipt = self._receipt()
        assert receipt.passed is False
        assert receipt.unverified == ("prompt-cache-buckets",)

    def test_an_unobserved_round_trip_is_a_failure(self) -> None:
        """`not_observed` outside the declared two is never acceptable."""
        receipt = SmokeReceipt(
            approval_id="approval_x",
            approval_record_digest="sha256:" + "0" * 64,
            cap_usd="1.000000",
            model="m",
            sdk_version="1.4.0",
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
            probes=(
                SmokeProbe(
                    probe="round-trip-usage", outcome="not_observed", detail="d"
                ),
            ),
            model_calls=0,
            total_cost_usd="0.000000",
        )
        assert receipt.passed is False
        assert receipt.unverified == ("round-trip-usage",)

    def test_the_rendered_receipt_carries_the_verdict(
        self, provider: _FakeProvider
    ) -> None:
        rendered = json.loads(render_receipt(self._receipt()))
        assert rendered["passed"] is True
        assert rendered["unverified"] == []
        assert len(rendered["probes"]) == len(SMOKE_PROBES)

    def test_the_receipt_never_carries_the_credential(
        self, provider: _FakeProvider, tmp_path: Path
    ) -> None:
        path = tmp_path / "cap06.json"
        self._receipt(receipt_path=path)
        assert "cap06-smoke-test-key" not in path.read_text(encoding="utf-8")

    def test_a_probe_that_raises_does_not_take_the_other_four_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One dead probe must still leave the rest of the evidence."""
        install(monkeypatch, _FakeProvider())
        original = _Messages.create
        calls = {"n": 0}

        def flaky(self: _Messages, **kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("the transport fell over")
            return original(self, **kwargs)

        monkeypatch.setattr(_Messages, "create", flaky)
        receipt = self._receipt()
        assert _probe_of(receipt, "round-trip-usage").outcome == "failed"
        assert "ValueError" in _probe_of(receipt, "round-trip-usage").detail
        assert _probe_of(receipt, "prompt-cache-buckets").outcome == "passed"
        assert _probe_of(receipt, "induced-4xx-request-id").outcome == "passed"


@pytest.mark.integration
class TestTheSmokeRestoresTheGateway:
    """Its recording client and its bindings do not outlive the run."""

    def test_the_memoised_client_is_the_caller_s_again(
        self, provider: _FakeProvider
    ) -> None:
        before = llm_module._client
        run_smoke(
            smoke_config(),
            approval_id="approval_cap06-smoke",
            cap_usd="1.000000",
            approval_backend=approval(),
        )
        assert llm_module._client is before

    def test_the_cost_cap_binding_is_released(self, provider: _FakeProvider) -> None:
        from src.observability.costs import effective_cost_cap

        run_smoke(
            smoke_config(),
            approval_id="approval_cap06-smoke",
            cap_usd="1.000000",
            approval_backend=approval(),
        )
        assert effective_cost_cap(99.0) == 99.0


# ---------------------------------------------------------------------------
# 4. The CLI verb
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTheSmokeVerb:
    """`python -m src.campaign smoke`, end to end through `main`."""

    def test_it_refuses_without_an_approval_id(
        self, provider: _FakeProvider, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["smoke", "--cap-usd", "1.000000"])
        assert code == EXIT_REFUSED
        assert "requires --approval-id" in capsys.readouterr().err
        assert not provider.requests

    def test_it_needs_no_campaign_id(
        self, provider: _FakeProvider, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The smoke is not a campaign; requiring one would invite a wrong record.

        Under the repository's zero-spend sentinel the verb refuses at
        the credential — which is the right door and the proof of this
        claim: a `--campaign-id` gate would have produced `EXIT_USAGE`
        and a message about the missing flag before the smoke ever ran.
        """
        code = main(["smoke", "--approval-id", "approval_cap06-smoke"])
        assert code == EXIT_REFUSED
        stderr = capsys.readouterr().err
        assert "local-preview-disabled" in stderr
        assert "--campaign-id" not in stderr
        assert not provider.requests

    def test_a_passing_smoke_prints_its_receipt_and_exits_zero(
        self,
        provider: _FakeProvider,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The happy path, with the approval read from a file as an operator's is.

        `_config()` is patched because the repository's own environment is
        the zero-spend sentinel — the very thing `run_smoke` refuses — so
        the verb can only reach its probes under a deployment that could
        pay. That is the deployment this asserts about.
        """
        from src.campaign import cli

        records = approval_file(tmp_path / "approvals.json")
        monkeypatch.setattr(cli, "_config", smoke_config)
        receipt_path = tmp_path / "cap06.json"
        code = main(
            [
                "smoke",
                "--approval-id",
                "approval_cap06-smoke",
                "--cap-usd",
                "1.000000",
                "--approval-records",
                str(records),
                "--receipt",
                str(receipt_path),
            ]
        )
        assert code == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["passed"] is True
        assert len(printed["probes"]) == len(SMOKE_PROBES)
        assert receipt_path.is_file()

    def test_a_failing_smoke_exits_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A receipt that did not pass is a non-zero exit, not a quiet one."""
        from src.campaign import cli

        install(monkeypatch, _FakeProvider(cache_buckets=False))
        records = approval_file(tmp_path / "approvals.json")
        monkeypatch.setattr(cli, "_config", smoke_config)
        code = main(
            [
                "smoke",
                "--approval-id",
                "approval_cap06-smoke",
                "--cap-usd",
                "1.000000",
                "--approval-records",
                str(records),
            ]
        )
        assert code == EXIT_REFUSED
        assert json.loads(capsys.readouterr().out)["unverified"] == [
            "prompt-cache-buckets"
        ]
