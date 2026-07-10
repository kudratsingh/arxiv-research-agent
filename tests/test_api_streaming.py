"""Unit tests for the SSE wire-format helpers."""

from __future__ import annotations

import json

import pytest

from src.api.streaming import (
    HEARTBEAT_INTERVAL_SEC,
    TERMINAL_EVENT_NAMES,
    format_heartbeat,
    format_sse,
    is_terminal_event,
)


class TestFormatSSE:
    def test_produces_valid_frame_structure(self) -> None:
        frame = format_sse("node_completed", {"node": "planner"})
        text = frame.decode()
        # Frame ends with two newlines to terminate the event.
        assert text.endswith("\n\n")
        # Event name and data lines both present.
        assert "event: node_completed\n" in text
        assert "data: " in text

    def test_data_line_is_valid_json(self) -> None:
        frame = format_sse("node_completed", {"node": "planner", "n": 3})
        text = frame.decode()
        data_line = next(
            line for line in text.splitlines() if line.startswith("data: ")
        )
        payload = json.loads(data_line[len("data: ") :])
        assert payload == {"n": 3, "node": "planner"}

    def test_json_keys_are_sorted_for_deterministic_serialization(self) -> None:
        # Deterministic serialization matters when a downstream is
        # diffing frames (regression tests, replay).
        a = format_sse("x", {"b": 1, "a": 2})
        b = format_sse("x", {"a": 2, "b": 1})
        assert a == b


class TestHeartbeat:
    def test_is_comment_frame(self) -> None:
        # SSE comment lines start with `:`; clients discard them.
        assert format_heartbeat().startswith(b":")
        assert format_heartbeat().endswith(b"\n\n")


class TestTerminalEvents:
    @pytest.mark.parametrize(
        "name",
        ["job_completed", "job_failed", "job_cancelled"],
    )
    def test_terminal_events_recognized(self, name: str) -> None:
        assert is_terminal_event(name)

    @pytest.mark.parametrize(
        "name",
        ["node_started", "node_completed", "heartbeat", ""],
    )
    def test_non_terminal_events_not_recognized(self, name: str) -> None:
        assert not is_terminal_event(name)

    def test_terminal_event_names_frozen(self) -> None:
        # Guards against accidental widening — the SSE endpoint uses
        # this set to decide when to close the stream.
        assert frozenset(
            {"job_completed", "job_failed", "job_cancelled"}
        ) == TERMINAL_EVENT_NAMES


def test_heartbeat_interval_is_conservative() -> None:
    # Reverse proxies typically close idle streams around 60s; the
    # heartbeat interval needs to stay well under that.
    assert 5.0 <= HEARTBEAT_INTERVAL_SEC <= 30.0
