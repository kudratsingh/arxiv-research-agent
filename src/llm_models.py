"""What each Claude model will accept in a request (ADR 0077).

The gateway used to send one request shape to every model: `temperature`
on every call, no `thinking`, no `effort`, no structured outputs. That
worked because the shipped default is `claude-sonnet-4-6`, which accepts
sampling parameters — and it breaks the day the model id moves, because
Opus 4.7 and later, Opus 5, Sonnet 5 and the Fable/Mythos tier **reject**
`temperature` with an HTTP 400. The failure is not subtle and it is not
recoverable at runtime: every call fails, on every node, for the whole
deployment.

So model quirks get one home. This module is the whole of it: a pure
table from a model id to what that model accepts, with a cited source
per row. `src/llm.py` asks it what to send and sends only that;
`src/config.py` asks it at settings load whether an enabled feature is
supported and refuses to start if it is not. Neither of them carries a
model name of its own, which is the property that makes adding a model
a one-line change here rather than a hunt.

Three resolution steps, in order:

1. **Exact id.** Every id the price table in
   `src/observability/costs.py` knows has a row, so a fully-priced
   deployment is also a fully-described one.
2. **Longest known-id prefix.** A dated snapshot
   (`claude-haiku-4-5-20251001`) is the model it is a snapshot of, and
   deriving that beats maintaining a row per date.
3. **Family prefix**, then the conservative row. Both of these are
   guesses, so both guess *downwards*: an unrecognised member of a
   known family gets that family's current sampling answer and none of
   the opt-in features, and an id from no known family gets nothing at
   all. The cost of guessing low is a call that works without a
   feature; the cost of guessing high is a 400 on every call. Those are
   not comparable, so the table never guesses high.

Nothing here logs, and `undescribed_models` explains why that is a
boundary rather than an oversight.

Sources for the rows below, current as of `CAPABILITIES_LAST_VERIFIED`:
Anthropic's thinking/effort model matrix (which models take
`thinking: {"type": "adaptive"}`, which reject `budget_tokens`, which
reject sampling parameters, and which effort levels each accepts) and
the structured-outputs documentation. The per-row comments cite which
part of that matrix the row comes from. There is a live
`GET /v1/models/{id}` capability endpoint, and this table is
deliberately *not* built from it: a network call cannot be made at
settings-load time, the suite is offline by construction
(`tests/conftest.py`), and a request shape that depends on a
provider round-trip fails differently every time it is wrong.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

#: The date the rows below were last checked against Anthropic's
#: published model behaviour. Bump it whenever the table is
#: re-verified, even if nothing changed — the same tripwire ADR 0044
#: puts on the price table, for the same reason.
CAPABILITIES_LAST_VERIFIED: Final = "2026-09-05"

#: Every `output_config.effort` level the API defines.
ALL_EFFORT: Final[frozenset[str]] = frozenset(
    {"low", "medium", "high", "xhigh", "max"}
)
#: `xhigh` arrived with Opus 4.7; the 4.6 generation has the other four.
EFFORT_WITHOUT_XHIGH: Final[frozenset[str]] = ALL_EFFORT - {"xhigh"}
#: Opus 4.5 accepts the original three and no more.
EFFORT_LOW_MEDIUM_HIGH: Final[frozenset[str]] = frozenset(
    {"low", "medium", "high"}
)
#: A model that rejects `output_config.effort` outright.
NO_EFFORT: Final[frozenset[str]] = frozenset()


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """What one model will accept, and where that claim comes from.

    Frozen because a row is a fact about a provider's API, not state:
    a caller that could mutate one would change what every later call
    sends, from anywhere in the process.
    """

    #: Whether `temperature` / `top_p` / `top_k` may be sent at all.
    #: False means the model answers a request carrying them with a 400.
    sampling_params: bool
    #: Whether `thinking={"type": "adaptive"}` is accepted. The older
    #: `{"type": "enabled", "budget_tokens": N}` form is deliberately
    #: not modelled: it is deprecated where it still works and rejected
    #: everywhere else, and this gateway does not send it.
    adaptive_thinking: bool
    #: The `output_config.effort` values this model accepts. Empty means
    #: the field must not be sent.
    effort_levels: frozenset[str]
    #: Whether `output_config.format` (structured outputs) is accepted.
    structured_outputs: bool
    #: Why this row says what it says. Free text, read by humans at
    #: review time; every row carries one and `tests/test_llm_models.py`
    #: asserts it.
    source: str

    @property
    def effort(self) -> bool:
        """Whether `output_config.effort` may be sent at all."""
        return bool(self.effort_levels)

    def supports_effort(self, level: str) -> bool:
        """Whether this model accepts `level` as an effort value."""
        return level in self.effort_levels


# ---------------------------------------------------------------------------
# The table.
# ---------------------------------------------------------------------------
#
# Ordered by tier, matching `PRICES_USD_PER_MILLION` in
# `src/observability/costs.py`, so the two tables read side by side and
# a model added to one is visibly missing from the other.

_FRONTIER = ModelCapabilities(
    # Fable/Mythos tier: thinking is always on and cannot be configured
    # off, sampling parameters and `budget_tokens` are both removed
    # (400), and all five effort levels are accepted.
    sampling_params=False,
    adaptive_thinking=True,
    effort_levels=ALL_EFFORT,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Fable 5 / Mythos 5 row",
)

_OPUS_5 = ModelCapabilities(
    # Opus 5: thinking on by default, `{"type": "adaptive"}` equivalent
    # to omitting it; sampling parameters removed (400); all five
    # effort levels.
    sampling_params=False,
    adaptive_thinking=True,
    effort_levels=ALL_EFFORT,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Claude Opus 5 row",
)

_OPUS_4_7_PLUS = ModelCapabilities(
    # Opus 4.8 / 4.7: adaptive is the only on-mode, `{"type":
    # "disabled"}` is accepted, sampling parameters removed (400),
    # `xhigh` introduced here.
    sampling_params=False,
    adaptive_thinking=True,
    effort_levels=ALL_EFFORT,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Opus 4.8 / 4.7 row",
)

_GEN_4_6 = ModelCapabilities(
    # Opus 4.6 / Sonnet 4.6: the last generation that still *accepts*
    # sampling parameters, which is why the shipped default model has
    # never hit the 400 this table exists to prevent. Adaptive thinking
    # is supported and recommended; effort predates `xhigh`.
    sampling_params=True,
    adaptive_thinking=True,
    effort_levels=EFFORT_WITHOUT_XHIGH,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Opus 4.6 / Sonnet 4.6 row",
)

_SONNET_5 = ModelCapabilities(
    # Sonnet 5: adaptive is the only on-mode; sampling parameters
    # removed (400); all five effort levels.
    sampling_params=False,
    adaptive_thinking=True,
    effort_levels=ALL_EFFORT,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Claude Sonnet 5 row",
)

_OPUS_4_5 = ModelCapabilities(
    # Opus 4.5: pre-adaptive — thinking is the `budget_tokens` form,
    # which this gateway does not send, so adaptive is False rather
    # than "thinking is impossible". Sampling parameters are accepted
    # and effort exists at three levels only.
    sampling_params=True,
    adaptive_thinking=False,
    effort_levels=EFFORT_LOW_MEDIUM_HIGH,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Opus 4.5 (effort, no xhigh)",
)

_HAIKU_4_5 = ModelCapabilities(
    # Haiku 4.5: sampling parameters accepted, thinking only in the
    # `budget_tokens` form, and `output_config.effort` errors outright.
    sampling_params=True,
    adaptive_thinking=False,
    effort_levels=NO_EFFORT,
    structured_outputs=True,
    source="Anthropic thinking/effort matrix — Haiku 4.5 row (effort errors)",
)

#: Exact model id -> capabilities. Every id in
#: `src.observability.costs.PRICES_USD_PER_MILLION` appears here;
#: `tests/property/test_property_llm_models.py` proves it over the
#: settings model, and `tests/test_llm_models.py` proves it over the
#: price table itself.
MODEL_CAPABILITIES: Final[dict[str, ModelCapabilities]] = {
    # Frontier tier.
    "claude-fable-5": _FRONTIER,
    "claude-mythos-5": _FRONTIER,
    # Opus tier.
    "claude-opus-5": _OPUS_5,
    "claude-opus-4-8": _OPUS_4_7_PLUS,
    "claude-opus-4-7": _OPUS_4_7_PLUS,
    "claude-opus-4-6": _GEN_4_6,
    "claude-opus-4-5": _OPUS_4_5,
    # Sonnet tier.
    "claude-sonnet-5": _SONNET_5,
    "claude-sonnet-4-6": _GEN_4_6,
    # Haiku tier. The dated id is in the price table because ADR 0021
    # recommends it as the reader's override; it resolves through the
    # prefix rule as well, and having both is not a contradiction.
    "claude-haiku-4-5": _HAIKU_4_5,
    "claude-haiku-4-5-20251001": _HAIKU_4_5,
}

#: Family prefix -> capabilities, for a model id from a known family
#: that this table has never seen. Every one of these keeps the
#: family's *current* sampling answer and switches every opt-in feature
#: off, because an unknown family member is only ever a guess: a wrong
#: "off" costs a feature, a wrong "on" costs a 400 on every call. An
#: operator who wants thinking or effort on a new model adds its row
#: above — the same one-line change ADR 0044 already asks for on the
#: price table.
#:
#: Longest prefix wins, so `claude-opus-` never shadows a more specific
#: entry. Older families (`claude-3-opus-...`) match nothing here and
#: fall through to the conservative row, which is correct: they are not
#: members of these families and share none of their behaviour.
FAMILY_CAPABILITIES: Final[dict[str, ModelCapabilities]] = {
    "claude-fable-": ModelCapabilities(
        sampling_params=False,
        adaptive_thinking=False,
        effort_levels=NO_EFFORT,
        structured_outputs=False,
        source="family guess — Fable tier rejects sampling parameters",
    ),
    "claude-mythos-": ModelCapabilities(
        sampling_params=False,
        adaptive_thinking=False,
        effort_levels=NO_EFFORT,
        structured_outputs=False,
        source="family guess — Mythos tier rejects sampling parameters",
    ),
    "claude-opus-": ModelCapabilities(
        sampling_params=False,
        adaptive_thinking=False,
        effort_levels=NO_EFFORT,
        structured_outputs=False,
        source="family guess — Opus 4.7 and later reject sampling parameters",
    ),
    "claude-sonnet-": ModelCapabilities(
        sampling_params=False,
        adaptive_thinking=False,
        effort_levels=NO_EFFORT,
        structured_outputs=False,
        source="family guess — Sonnet 5 rejects sampling parameters",
    ),
    "claude-haiku-": ModelCapabilities(
        sampling_params=True,
        adaptive_thinking=False,
        effort_levels=NO_EFFORT,
        structured_outputs=False,
        source="family guess — Haiku tier accepts sampling parameters",
    ),
}

#: What an id from no known family resolves to. Nothing is sent that
#: the provider could refuse, which makes an unrecognised id a *working*
#: deployment with no opt-in features rather than a broken one.
UNKNOWN_MODEL_CAPABILITIES: Final = ModelCapabilities(
    sampling_params=False,
    adaptive_thinking=False,
    effort_levels=NO_EFFORT,
    structured_outputs=False,
    source="conservative fallback — this id is not in the table",
)

def _longest_prefix_match(
    model: str,
    table: dict[str, ModelCapabilities],
    *,
    on_segment_boundary: bool,
) -> ModelCapabilities | None:
    """The value whose key is the longest prefix of `model`, if any.

    Longest rather than first so a table can hold both a family and a
    specific member of it without the iteration order deciding which
    one answers.

    Args:
        model: The id being resolved.
        table: Keys to test as prefixes.
        on_segment_boundary: When True, the match must end on a `-`
            segment boundary. `claude-opus-5` describes
            `claude-opus-5-1` and a dated `claude-opus-5-20260401`; it
            says nothing about a hypothetical `claude-opus-50`, and a
            bare `startswith` cannot tell those apart. The family table
            passes False because its keys already end in `-`.
    """
    best_key = ""
    for key in table:
        if not model.startswith(key) or len(key) <= len(best_key):
            continue
        if on_segment_boundary and not model[len(key) :].startswith("-"):
            continue
        best_key = key
    return table[best_key] if best_key else None


def capabilities_for(model: str) -> ModelCapabilities:
    """Return what `model` will accept in a request.

    Args:
        model: A Claude model id, exactly as it will be sent as the
            request's `model` field.

    Returns:
        The exact row when there is one, else the row for the longest
        known id `model` extends — a dated snapshot
        (`claude-haiku-4-5-20251001`) or a point release
        (`claude-opus-5-1`), both of which carry their base model's
        request surface — else the row for its family, else
        `UNKNOWN_MODEL_CAPABILITIES`.
    """
    exact = MODEL_CAPABILITIES.get(model)
    if exact is not None:
        return exact
    snapshot = _longest_prefix_match(
        model, MODEL_CAPABILITIES, on_segment_boundary=True
    )
    if snapshot is not None:
        return snapshot
    family = _longest_prefix_match(
        model, FAMILY_CAPABILITIES, on_segment_boundary=False
    )
    if family is not None:
        return family
    return UNKNOWN_MODEL_CAPABILITIES


def is_described(model: str) -> bool:
    """Whether `model` resolves to a real row rather than the fallback.

    The question `unpriced_models` asks about the price table, asked
    about this one. False for a routed id means the deployment sends
    the most conservative request shape there is — which works, but
    silently forgoes every feature the operator may think they enabled.
    """
    return capabilities_for(model) is not UNKNOWN_MODEL_CAPABILITIES


def undescribed_models(model_ids: Iterable[str]) -> set[str]:
    """Which of `model_ids` fall through to the conservative row.

    The counterpart to `src.observability.costs.unpriced_models`, and
    deliberately *silent* where that one warns.

    The work order this module implements asked for one WARNING per
    process naming an undescribed id. It is not emitted here, and the
    reason is a boundary rather than a judgment: ADR 0067 keeps a
    closed registry of log event names in `src/observability/logging.py`
    (`KNOWN_EVENTS`), `tests/test_log_contract.py` fails on any name the
    source emits that the registry does not list, and
    `src/observability/**` is fenced for another lane's work orders. A
    new event name therefore cannot land with this change, and the two
    ways around it — a logger variable named to slip past the scanner,
    or borrowing an event name that means something else — are both
    worse than not logging.

    What covers the gap in the meantime is the coupling between the two
    tables. `tests/test_llm_models.py` asserts that every id in
    `PRICES_USD_PER_MILLION` has a row here, so an id that reaches the
    conservative row is also an id with no price row — and *that*
    already emits `unknown_model_pricing_fallback` at WARNING, once per
    process, naming the id, with "add a row" as its action. An operator
    who sees that line has to visit both tables.

    Args:
        model_ids: The ids to check — `resolved_model_ids(settings)`
            for the question "is this deployment fully described?".

    Returns:
        The subset with no row of their own. Empty when every id is
        described.
    """
    return {model for model in model_ids if not is_described(model)}
