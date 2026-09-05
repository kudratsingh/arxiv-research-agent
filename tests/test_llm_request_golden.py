"""The exact request body `src/llm.py` sends, pinned to a fixture.

CAP-01 makes the gateway model-aware: sampling parameters, adaptive
thinking, `effort` and structured outputs each become conditional on a
capability row. Every one of those conditions defaults to "off", and
the claim the whole work order rests on is that *with the shipped
defaults nothing about the outgoing request changes* — the scripted
research tier's trajectory, the eval baselines and the cost table all
assume it.

A claim like that cannot be checked by reading a diff, because the
kwargs are assembled across three helpers and a `with` block. So it is
checked against a **fixture captured from the unmodified gateway** and
committed before the gateway was touched: `tests/fixtures/llm/
request_kwargs_golden.json`. The commit that introduces this file
changes no production code, which is what makes the fixture evidence
rather than a restatement of whatever the code happens to do now.

Recapturing it is a deliberate act, not a `--snapshot-update` away:
`REGENERATE = True` below, run the module, read the diff, and justify
every changed line in the PR body. A default-settings change to any of
these four bodies is a behaviour change for every deployment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src import llm as llm_module

pytestmark = [pytest.mark.unit, pytest.mark.contract]

#: Set to True, run this module once, and commit the regenerated file
#: *with the reason in the PR body*. Asserted False below so it cannot
#: be left on by accident — a snapshot test whose snapshot rewrites
#: itself on every run asserts nothing.
REGENERATE = False

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "llm" / "request_kwargs_golden.json"

#: How `anthropic.NOT_GIVEN` is spelled in the fixture. The sentinel is
#: not JSON-representable and it is not `None` either — the SDK omits
#: the field entirely for `NOT_GIVEN` and sends `"system": null` for
#: `None`, so collapsing the two would hide a real wire difference.
NOT_GIVEN_MARKER = "<NOT_GIVEN>"


class _Usage:
    input_tokens = 100
    output_tokens = 50
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str) -> None:
        self.content = [_TextBlock(text)]
        self.usage = _Usage()
        self.id = "msg_golden"
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
    def __init__(self, text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text
        self.with_raw_response = _RawMessages(self)

    def record(self, **kwargs: Any) -> _RawResponse:
        self.calls.append(kwargs)
        return _RawResponse(_Response(self._text))


class _Client:
    def __init__(self, text: str) -> None:
        self.messages = _Messages(text)


def _jsonable(value: Any) -> Any:
    """Render one kwarg as the fixture stores it.

    Only the shapes this gateway actually sends are handled, and
    anything else raises rather than being coerced: a kwarg the fixture
    cannot describe is a kwarg this test would have silently stopped
    checking.
    """
    if value is llm_module.anthropic.NOT_GIVEN:
        return NOT_GIVEN_MARKER
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    raise TypeError(f"golden fixture cannot describe {type(value).__name__}")


def _capture(monkeypatch: pytest.MonkeyPatch, case: str) -> dict[str, Any]:
    """Run one gateway call against a fake client and return its kwargs."""
    client = _Client('{"ok": true}')
    monkeypatch.setattr(llm_module, "_get_client", lambda: client)
    monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)

    if case == "text_with_system":
        llm_module.call_llm(
            "Summarise the attention mechanism.",
            system_prompt="You are terse.",
            max_tokens=1024,
        )
    elif case == "text_without_system":
        llm_module.call_llm("Summarise the attention mechanism.")
    elif case == "text_with_cached_system":
        llm_module.call_llm(
            "Summarise the attention mechanism.",
            system_prompt="You are terse.",
            max_tokens=1024,
            cache_system=True,
        )
    elif case == "json_with_system":
        llm_module.call_llm_json(
            "Plan this research question.",
            system_prompt="Return JSON only.",
            max_tokens=2048,
        )
    else:  # pragma: no cover - guarded by CASES below
        raise AssertionError(f"unknown golden case {case!r}")

    assert len(client.messages.calls) == 1
    return {key: _jsonable(value) for key, value in client.messages.calls[0].items()}


#: The four request shapes the shipped defaults can produce. `system`
#: has three distinct spellings (absent, plain string, cache-marked
#: block) and each one is a different wire body, so each is pinned.
CASES = (
    "text_with_system",
    "text_without_system",
    "text_with_cached_system",
    "json_with_system",
)


def _golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


class TestTheDefaultRequestBody:
    """With every CAP-01 setting at its default, these bodies are frozen."""

    def test_the_regenerate_switch_is_off(self) -> None:
        assert REGENERATE is False, (
            "REGENERATE is a one-shot capture switch. Left on, this "
            "module rewrites its own fixture and stops being a gate."
        )

    @pytest.mark.parametrize("case", CASES)
    def test_the_request_matches_the_captured_fixture(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        assert _capture(monkeypatch, case) == _golden()[case]

    def test_the_fixture_describes_every_case_and_no_others(self) -> None:
        """A case dropped from `CASES` must not leave a stale row behind.

        Equality both ways: an orphan row in the fixture is a shape
        nothing checks any more, and a case with no row would make the
        parametrized test above fail with a `KeyError` rather than a
        readable diff.
        """
        assert set(_golden()) == set(CASES)


def _regenerate() -> None:
    """Capture the four bodies and overwrite the fixture."""
    monkeypatch = pytest.MonkeyPatch()
    try:
        captured = {case: _capture(monkeypatch, case) for case in CASES}
    finally:
        monkeypatch.undo()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(captured, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":  # pragma: no cover - operator entry point
    _regenerate()
    print(f"wrote {GOLDEN_PATH}")
