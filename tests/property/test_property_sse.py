"""Invariants of the SSE wire format (ADR 0026, ADR 0038, ADR 0069).

`format_sse` is thirty characters of f-string and it is the only thing
standing between a graph node's output and a browser's `EventSource`.
The wire format has no framing beyond a blank line, so a payload that
contains one is not a malformed frame — it is *two* frames, the second
of which the client will try to parse as an event it does not know.
That failure is silent on the server and total on the client, which is
why the shape of the encoding is a property and not a docstring.

The event names are drawn from the closed set
`tests/test_contract_sse_events.py` pins, because that is the set a
client codes against.
"""

from __future__ import annotations

import json
import string
from typing import Any, Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.api.streaming import (
    PAUSE_EVENT_NAMES,
    STREAM_TIMEOUT_EVENT,
    TERMINAL_EVENT_NAMES,
    closes_stream,
    format_sse,
    is_terminal_event,
)

pytestmark = [pytest.mark.unit, pytest.mark.property, pytest.mark.contract]

#: The closed set, composed the way `test_contract_sse_events.py`
#: composes it. `job_started` and `node_completed` are the two frames
#: that are neither terminal nor a pause, and they carry the bulk of
#: the traffic.
EVENT_NAMES: Final[tuple[str, ...]] = tuple(
    sorted(
        TERMINAL_EVENT_NAMES
        | PAUSE_EVENT_NAMES
        | {STREAM_TIMEOUT_EVENT, "job_started", "node_completed"}
    )
)

#: JSON, and only JSON: `format_sse` calls `json.dumps` without a
#: default hook, so a payload it cannot serialise is a `TypeError` on
#: the response body, not a frame. NaN and infinity are excluded
#: because `json` emits them as bare `NaN`/`Infinity` literals, which
#: are not JSON and which no browser will parse.
_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=40),
)
_JSON = st.recursive(
    _SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=12), children, max_size=4),
    ),
    max_leaves=8,
)
PAYLOADS = st.dictionaries(st.text(max_size=16), _JSON, max_size=6)


def decode(frame: bytes) -> tuple[str, dict[str, Any]]:
    """Parse one SSE frame back into `(event, data)`.

    Written here rather than imported because there is nothing to
    import: the encoder is hand-rolled (no `sse-starlette`), so the
    decoder in this file plays the part the browser plays. A
    round-trip against the encoder's own inverse would prove only that
    the encoder agrees with itself.
    """
    text = frame.decode("utf-8")
    assert text.endswith("\n\n"), f"frame is not blank-line terminated: {text!r}"
    lines = text[:-2].split("\n")
    assert len(lines) == 2, f"frame is not exactly two lines: {lines!r}"
    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


@given(event=st.sampled_from(EVENT_NAMES), data=PAYLOADS)
def test_encoding_a_frame_and_reading_it_back_returns_what_went_in(
    event: str, data: dict[str, Any]
) -> None:
    """Encode-then-decode is the identity on every event in the closed set."""
    assert decode(format_sse(event, data)) == (event, data)


@given(event=st.sampled_from(EVENT_NAMES), data=PAYLOADS)
def test_one_call_produces_exactly_one_frame(
    event: str, data: dict[str, Any]
) -> None:
    """A frame contains one blank line, at its end, and no other newline.

    The blank line *is* the frame separator, so a payload carrying one
    splits the message in two: the client would deliver a truncated
    event and then try to route the remainder as a fresh one. The
    separators-and-`sort_keys` call to `json.dumps` is what prevents
    it — `indent=` would be a readability improvement that silently
    broke every stream.
    """
    frame = format_sse(event, data)

    assert frame.count(b"\n\n") == 1
    assert frame.endswith(b"\n\n")
    # Two newlines start the terminator; the third is the one between
    # the `event:` and `data:` lines. Any more came from the payload.
    assert frame.count(b"\n") == 3


@given(event=st.sampled_from(EVENT_NAMES), data=PAYLOADS)
def test_encoding_is_deterministic_for_a_given_payload(
    event: str, data: dict[str, Any]
) -> None:
    """The same `(event, data)` always encodes to the same bytes.

    `sort_keys=True` is what makes this true, and it is load-bearing
    beyond tidiness: the recorded SSE fixtures in
    `tests/fixtures/contracts` are compared byte-for-byte, so a frame
    whose key order followed dict insertion order would produce a
    contract diff on a payload that had not changed.
    """
    assert format_sse(event, data) == format_sse(event, dict(reversed(list(data.items()))))


@given(event=st.one_of(st.sampled_from(EVENT_NAMES), st.text(max_size=24)))
def test_a_terminal_event_always_closes_the_stream_but_not_the_reverse(
    event: str,
) -> None:
    """`closes_stream` is strictly wider than `is_terminal_event`, by exactly one name.

    The two questions are different — "did the job end?" and "should
    the server stop writing?" — and `stream_timeout` is the whole
    difference: it closes the connection while the job keeps running.
    A subscriber that collapsed the two would report a healthy job as
    finished, and one that separated them wrongly would leave a
    finished job's stream open forever. Asserted over arbitrary
    strings as well as the closed set, because the name reaching these
    predicates comes off a Redis channel as `str(frame.get("event"))`.
    """
    if is_terminal_event(event):
        assert closes_stream(event)

    if closes_stream(event) and not is_terminal_event(event):
        assert event == STREAM_TIMEOUT_EVENT

    # A pause frame is the one thing that must not stop the stream:
    # `plan_ready` and `turn_ready` are where a human acts, and a
    # closed connection at that moment costs a reconnect per turn.
    if event in PAUSE_EVENT_NAMES:
        assert not closes_stream(event)


#: Names built to carry a frame separator. `\r`, `\n` and `\r\n` are all
#: line terminators to an `EventSource` parser, so all three have to be
#: generated: a sanitiser that handled only `\n` would leave `\r` and
#: `\r\n` splitting frames, and `\r\n` is the one a naive `replace("\n",
#: "")` turns into a lone `CR` that still terminates the line.
INJECTED_NAMES = st.builds(
    lambda head, sep, tail: f"{head}{sep}{tail}",
    st.text(alphabet=string.ascii_lowercase + "_", max_size=12),
    st.sampled_from(["\n", "\r", "\r\n"]),
    st.text(alphabet=string.ascii_lowercase + "_: ", max_size=20),
)


@given(event=INJECTED_NAMES, data=PAYLOADS)
def test_a_newline_in_an_event_name_still_produces_exactly_one_frame(
    event: str, data: dict[str, Any]
) -> None:
    """The frame count is a property of the encoder, not of its callers.

    `test_one_call_produces_exactly_one_frame` above asks this question
    of the payload and answers it with `json.dumps`. The event name had
    no equivalent guard: `format_sse` interpolated it into the
    `event:` line verbatim, so a name carrying a blank line produced
    two frames — a truncated event, and a remainder the client would
    route as an event nobody defined. Silent on the server, total on
    the client.

    Unreachable from the runner today, because every name it emits comes
    from the closed set at the top of this file. That is the reason to
    pin it now rather than an argument against doing so: the day a name
    is derived from a job id, a tool name, or anything else a caller
    supplies, the encoder is where the injection would have landed.
    """
    frame = format_sse(event, data)

    assert frame.count(b"\n\n") == 1
    assert frame.endswith(b"\n\n")
    assert frame.count(b"\n") == 3
    # And the surviving name is the input minus its line terminators —
    # the sanitiser drops separators, it does not drop the routing key.
    decoded_event, decoded_data = decode(frame)
    assert decoded_event == event.replace("\r", "").replace("\n", "")
    assert decoded_data == data
