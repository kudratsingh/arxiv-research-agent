"""What the gateway actually sends, per model and per flag (ADR 0077).

`tests/test_llm_request_golden.py` pins the one body that must never
move. This module is the other half: what changes when a setting is
turned on, and — the part that is the whole point — what *does not*
change because the model would refuse it.

The acceptance criteria CAP-01 was written against are the four
`TestTheAcceptanceMatrix` cases. Each one is a deployment somebody
could have today:

| Model | temperature | thinking | effort |
|---|---|---|---|
| `claude-sonnet-4-6` (the default) | sent | sent | sent |
| `claude-opus-5` | **not** sent | sent | sent |
| `claude-haiku-4-5` | sent | **not** sent | **not** sent |
| an unrecognised id | **not** sent | **not** sent | **not** sent |

The middle row is the bug this work order exists for: `temperature` on
Opus 5 is an HTTP 400 on every call, and before ADR 0077 it was sent
unconditionally.

Everything here runs against a fake client through the harness. No
network, no key, no spend — and the request body is read out of the
fake's recorded kwargs, which is the only place a claim about the wire
can be checked without a live call. Whether the *provider* accepts
each shape is CAP-06's funded smoke, not this file.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src import llm as llm_module
from src.agents.schemas import PlannerOutput
from src.config import Settings
from src.errors import UpstreamModelOutput
from src.observability import costs as costs_module

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Doubles. Shaped like `tests/test_llm.py`'s, plus the two things this
# module needs that predate nothing: a response with a `thinking` block
# in it, and a response whose text is schema-shaped JSON.
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, output_tokens: int = 50) -> None:
        self.input_tokens = 100
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class _Block:
    """One content block. `thinking` blocks carry no `text` attribute.

    Deliberately: the SDK's `ThinkingBlock` has `thinking` and
    `signature` and no `text`, so a gateway that reached for `.text`
    before checking `.type` would raise here rather than quietly
    returning the reasoning as the answer.
    """

    def __init__(self, block_type: str, body: str) -> None:
        self.type = block_type
        if block_type == "text":
            self.text = body
        else:
            self.thinking = body
            self.signature = "sig"


class _Response:
    def __init__(self, blocks: list[_Block], usage: _Usage) -> None:
        self.content = blocks
        self.usage = usage
        self.id = "msg_fake"
        self.model = "claude-sonnet-4-6"
        self.stop_reason = "end_turn"


class _RawResponse:
    def __init__(self, parsed: _Response) -> None:
        self._parsed = parsed
        self.retries_taken = 0

    def parse(self) -> _Response:
        return self._parsed


class _RawMessages:
    def __init__(self, parent: _Messages) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _RawResponse:
        return self._parent.record(**kwargs)


class _Messages:
    def __init__(self, blocks: list[_Block], usage: _Usage) -> None:
        self.calls: list[dict[str, Any]] = []
        self._blocks = blocks
        self._usage = usage
        self.with_raw_response = _RawMessages(self)

    def record(self, **kwargs: Any) -> _RawResponse:
        self.calls.append(kwargs)
        return _RawResponse(_Response(self._blocks, self._usage))


class _Client:
    def __init__(
        self, blocks: list[_Block] | None = None, usage: _Usage | None = None
    ) -> None:
        self.messages = _Messages(
            blocks if blocks is not None else [_Block("text", '{"ok": true}')],
            usage or _Usage(),
        )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    blocks: list[_Block] | None = None,
    usage: _Usage | None = None,
    **overrides: Any,
) -> _Client:
    """Bind a fake client and a `Settings` carrying `overrides`."""
    client = _Client(blocks, usage)
    monkeypatch.setattr(llm_module, "_get_client", lambda: client)
    monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)
    monkeypatch.setattr(llm_module, "settings", Settings(**overrides))
    return client


@pytest.fixture(autouse=True)
def _no_cost_accumulator() -> Any:
    """No run bound, so the spend ceiling has nothing to measure."""
    token = costs_module._current_costs.set(None)
    try:
        yield
    finally:
        costs_module._current_costs.reset(token)


def _sent(client: _Client) -> dict[str, Any]:
    assert len(client.messages.calls) == 1
    return client.messages.calls[0]


#: Every setting this work order added, at a non-default value that the
#: default model accepts. "Flags on" below means exactly this.
ALL_FLAGS_ON: dict[str, Any] = {
    "llm_thinking": "adaptive",
    "llm_effort": "high",
    "enable_structured_outputs": True,
    "llm_temperature": 0.7,
}


class TestTheAcceptanceMatrix:
    """One row per deployment CAP-01's acceptance criteria name."""

    def test_flags_off_send_none_of_the_new_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default deployment. Byte-identical is proved by the
        golden fixture; this states the same thing field by field, so a
        failure says *which* field arrived rather than "the dict
        differs"."""
        client = _install(monkeypatch)

        llm_module.call_llm("u")

        sent = _sent(client)
        assert sent["temperature"] == 0.3
        assert "thinking" not in sent
        assert "output_config" not in sent

    def test_flags_on_with_the_default_model_send_all_three(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, **ALL_FLAGS_ON)

        llm_module.call_llm("u")

        sent = _sent(client)
        assert sent["temperature"] == 0.7
        assert sent["thinking"] == {"type": "adaptive"}
        assert sent["output_config"] == {"effort": "high"}

    def test_opus_5_gets_thinking_and_effort_but_no_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The row this work order exists for.

        Mutation-check: restoring the unconditional `temperature=` in
        `call_llm` puts the key back and fails the first assertion —
        which is the HTTP 400 this test stands in for, since the suite
        may not reach a provider.
        """
        client = _install(monkeypatch, **ALL_FLAGS_ON)

        llm_module.call_llm("u", model_name="claude-opus-5")

        sent = _sent(client)
        assert "temperature" not in sent
        assert sent["thinking"] == {"type": "adaptive"}
        assert sent["output_config"] == {"effort": "high"}

    def test_haiku_gets_temperature_but_no_thinking_and_no_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Haiku 4.5 takes sampling, has no adaptive mode, errors on effort.

        Routed through `model_name` rather than `ANTHROPIC_MODEL`
        because the settings validator refuses that combination at load
        — which is the other half of the same guarantee, asserted in
        `tests/test_config.py`. A `model_name` passed at a call site is
        the case no settings check has ever seen, and it is why
        `resolve_profile` re-checks.
        """
        client = _install(monkeypatch, **ALL_FLAGS_ON)

        llm_module.call_llm("u", model_name="claude-haiku-4-5")

        sent = _sent(client)
        assert sent["temperature"] == 0.7
        assert "thinking" not in sent
        assert "output_config" not in sent

    def test_an_unknown_id_gets_nothing_optional_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, **ALL_FLAGS_ON)

        llm_module.call_llm("u", model_name="some-proxy-model")

        sent = _sent(client)
        assert set(sent) == {"model", "max_tokens", "system", "messages"}

    def test_sonnet_5_is_opus_5_shaped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, **ALL_FLAGS_ON)

        llm_module.call_llm("u", model_name="claude-sonnet-5")

        sent = _sent(client)
        assert "temperature" not in sent
        assert sent["thinking"] == {"type": "adaptive"}


class TestTheProfileIsTheConjunction:
    """Enabled *and* supported — neither half alone sends anything."""

    def test_supported_but_not_enabled_sends_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch)  # Opus 5 supports all of it.

        llm_module.call_llm("u", model_name="claude-opus-5")

        sent = _sent(client)
        assert "thinking" not in sent
        assert "output_config" not in sent

    def test_the_profile_reports_what_it_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_module, "settings", Settings(**ALL_FLAGS_ON))

        assert llm_module.resolve_profile("claude-opus-5") == llm_module.RequestProfile(
            model="claude-opus-5",
            temperature=None,
            adaptive_thinking=True,
            effort="high",
            structured_outputs=True,
        )

    def test_a_profile_cannot_be_edited_after_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_module, "settings", Settings())
        profile = llm_module.resolve_profile("claude-sonnet-4-6")
        with pytest.raises(AttributeError):
            profile.temperature = 0.9  # type: ignore[misc]


class TestPerAgentEffort:
    """`<agent>_effort` reaches the wire when the caller names the agent."""

    def test_an_agent_override_beats_the_global_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, llm_effort="low", planner_effort="max")

        llm_module.call_llm("u", agent="planner")

        assert _sent(client)["output_config"] == {"effort": "max"}

    def test_an_empty_override_inherits_the_global_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, llm_effort="low")

        llm_module.call_llm("u", agent="planner")

        assert _sent(client)["output_config"] == {"effort": "low"}

    def test_off_opts_one_agent_out_of_an_inherited_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The only expression of "global effort, except the reader".

        Without it, `LLM_EFFORT=high` plus ADR 0021's recommended
        `READER_MODEL=claude-haiku-4-5` is a configuration that cannot
        boot and cannot be fixed, because an empty override inherits.
        """
        client = _install(
            monkeypatch,
            llm_effort="high",
            reader_model="claude-haiku-4-5",
            reader_effort="off",
        )

        llm_module.call_llm("u", model_name="claude-haiku-4-5", agent="reader")

        assert "output_config" not in _sent(client)


class TestThinkingBlocksInTheResponse:
    """The reason enabling thinking is safe at all."""

    def test_thinking_blocks_are_skipped_and_the_text_blocks_join(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`[thinking, text, text]` is the shape adaptive thinking returns.

        Mutation-check: reading `content[0].text` raises
        `AttributeError` on the thinking block; dropping the `type`
        filter puts the reasoning in the answer.
        """
        client = _install(
            monkeypatch,
            blocks=[
                _Block("thinking", "let me work through this"),
                _Block("text", "first half "),
                _Block("text", "second half"),
            ],
        )

        assert llm_module.call_llm("u") == "first half second half"
        assert _sent(client)  # the call really happened

    def test_a_thinking_only_response_raises_instead_of_returning_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure that used to look like a successful empty answer.

        Before ADR 0077 this returned `""`, and every caller treated
        the silence as content: the planner fell back to the raw query,
        the critic approved with a zero score, and the run finished
        `succeeded` having been told nothing.
        """
        _install(monkeypatch, blocks=[_Block("thinking", "…")])

        with pytest.raises(UpstreamModelOutput) as raised:
            llm_module.call_llm("u")

        assert raised.value.code == "upstream_model_output"
        assert "thinking" in str(raised.value)

    def test_the_billed_call_is_still_recorded_when_the_text_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anthropic bills a thinking-only answer like any other.

        Cost is recorded before the refusal, so a run that burned its
        budget on unusable answers still reports what it spent.
        """
        client = _Client([_Block("thinking", "…")], _Usage())
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        monkeypatch.setattr(llm_module, "settings", Settings())
        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(
            llm_module, "record_llm_call", lambda **kw: seen.append(kw)
        )

        with pytest.raises(UpstreamModelOutput):
            llm_module.call_llm("u")

        assert len(seen) == 1
        assert seen[0]["output_tokens"] == 50

    def test_an_empty_text_block_is_still_an_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that answers with empty text has answered.

        The refusal above is about a response with no text block at
        all. Conflating the two would turn a legitimate — if useless —
        empty completion into a job failure, which is a behaviour
        change on the default path.
        """
        _install(monkeypatch, blocks=[_Block("text", "")])

        assert llm_module.call_llm("u") == ""

    def test_thinking_text_never_reaches_the_returned_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            blocks=[_Block("thinking", "SECRET-REASONING"), _Block("text", "answer")],
        )

        assert "SECRET-REASONING" not in llm_module.call_llm("u")


class TestTheStructuredPath:
    """`output_config.format`, and what happens when the answer misses."""

    _VALID = json.dumps(
        {"sub_questions": ["a", "b"], "search_queries": ["q1", "q2"]}
    )

    def test_the_schema_is_sent_as_output_config_format(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(
            monkeypatch,
            blocks=[_Block("text", self._VALID)],
            enable_structured_outputs=True,
        )

        llm_module.call_llm_json("u", schema=PlannerOutput)

        fmt = _sent(client)["output_config"]["format"]
        assert fmt["type"] == "json_schema"
        assert fmt["schema"]["required"] == ["sub_questions", "search_queries"]
        assert fmt["schema"]["additionalProperties"] is False

    def test_the_schema_carries_no_class_docstring_to_the_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A docstring in the schema is prompt text arriving sideways.

        `src/agents/schemas.py` talks about `planner_agent`'s fallback
        and ADR numbers; pydantic would ship all of it as
        `description`, and this work order does not move prompt wording
        (ADR 0070).
        """
        client = _install(
            monkeypatch,
            blocks=[_Block("text", self._VALID)],
            enable_structured_outputs=True,
        )

        llm_module.call_llm_json("u", schema=PlannerOutput)

        wire = json.dumps(_sent(client)["output_config"]["format"])
        assert "planner_agent" not in wire
        assert "ADR" not in wire

    def test_a_valid_response_returns_the_validated_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            blocks=[_Block("text", self._VALID)],
            enable_structured_outputs=True,
        )

        assert llm_module.call_llm_json("u", schema=PlannerOutput) == {
            "sub_questions": ["a", "b"],
            "search_queries": ["q1", "q2"],
        }

    def test_a_schema_violation_raises_the_taxonomy_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid JSON, wrong shape. `json.loads` would have accepted it.

        The stable code is what the runner records and what the
        frontend has a sentence for (ADR 0064) — so the assertion is on
        `code`, not on the class.
        """
        _install(
            monkeypatch,
            blocks=[_Block("text", '{"sub_questions": "not a list"}')],
            enable_structured_outputs=True,
        )

        with pytest.raises(UpstreamModelOutput) as raised:
            llm_module.call_llm_json("u", schema=PlannerOutput)

        assert raised.value.code == "upstream_model_output"
        assert "PlannerOutput" in str(raised.value)

    def test_the_violation_detail_does_not_echo_the_model_s_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing structured answer is the most likely thing to be
        long, and to be quoting the user's own query back."""
        _install(
            monkeypatch,
            blocks=[_Block("text", '{"sub_questions": "USER-CONTENT-HERE"}')],
            enable_structured_outputs=True,
        )

        with pytest.raises(UpstreamModelOutput) as raised:
            llm_module.call_llm_json("u", schema=PlannerOutput)

        assert "USER-CONTENT-HERE" not in str(raised.value)

    def test_the_flag_off_leaves_the_free_text_path_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same wrong-shaped body, with the flag off, still parses.

        This is the guarantee the four consumers rest on: passing a
        schema changes nothing until an operator turns the flag on.
        """
        client = _install(
            monkeypatch, blocks=[_Block("text", '{"sub_questions": "not a list"}')]
        )

        assert llm_module.call_llm_json("u", schema=PlannerOutput) == {
            "sub_questions": "not a list"
        }
        assert "output_config" not in _sent(client)

    def test_an_unsupporting_model_falls_back_rather_than_failing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structured outputs degrade; that is why they are not refused
        at settings load the way thinking and effort are."""
        client = _install(
            monkeypatch,
            blocks=[_Block("text", '{"sub_questions": "not a list"}')],
            enable_structured_outputs=True,
        )

        parsed = llm_module.call_llm_json(
            "u", model_name="some-proxy-model", schema=PlannerOutput
        )

        assert parsed == {"sub_questions": "not a list"}
        assert "output_config" not in _sent(client)

    def test_no_schema_means_no_format_even_with_the_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(monkeypatch, enable_structured_outputs=True)

        llm_module.call_llm_json("u")

        assert "output_config" not in _sent(client)

    def test_effort_and_format_share_one_output_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two unrelated things live under the same key in the API."""
        client = _install(
            monkeypatch,
            blocks=[_Block("text", self._VALID)],
            enable_structured_outputs=True,
            llm_effort="medium",
        )

        llm_module.call_llm_json("u", schema=PlannerOutput)

        output_config = _sent(client)["output_config"]
        assert output_config["effort"] == "medium"
        assert output_config["format"]["type"] == "json_schema"

    def test_the_free_text_control_character_fallback_still_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`strict=False` is the retry ADR 0041's callers depend on."""
        _install(monkeypatch, blocks=[_Block("text", '{"a": "line\nbreak"}')])

        assert llm_module.call_llm_json("u") == {"a": "line\nbreak"}


class TestTheSpanStillDescribesTheRequest:
    def test_the_temperature_attribute_follows_the_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`gen_ai.request.temperature` reports what was sent (ADR 0066).

        The half this test cannot make: the attribute should be
        *absent* on a model that receives no temperature.
        `llm_span` takes a required `float`
        (`src/observability/tracing.py:642`) and sets it unconditionally
        (`:676`), and that package is fenced — so on Opus 5 the span
        still carries the configured-but-unsent value. Recorded as
        follow-up 1 in ADR 0077; when the signature takes `float |
        None`, this test grows an `is None` case.
        """
        seen: list[float] = []

        class _NullSpan:
            def set_attribute(self, *_: Any) -> None:
                return None

        def fake_span(**kwargs: Any) -> Any:
            seen.append(kwargs["temperature"])

            class _Ctx:
                def __enter__(self) -> Any:
                    return _NullSpan()

                def __exit__(self, *_: Any) -> bool:
                    return False

            return _Ctx()

        _install(monkeypatch, llm_temperature=0.55)
        monkeypatch.setattr(llm_module, "llm_span", fake_span)

        llm_module.call_llm("u")

        assert seen == [0.55]
