"""Invariants of settings validation (ADR 0069).

`src/config.py` carries 39 numerically-bounded fields and 12 `Literal`
fields, and every one of them is a promise made to an operator editing
an environment file: a value outside the declared range dies at
settings load, before traffic, rather than three hours later as an
unexplained behaviour change. `tests/test_config.py` checks a handful
of those fields by hand.

The bounds are read off `Settings.model_fields` rather than restated,
so a field added tomorrow is covered the day it lands and a field
whose bounds are *widened* is checked against the new range rather
than a copy of the old one. That is the whole point of deriving them:
a hand-maintained list of ranges is a second source of truth, and the
second source is the one that goes stale.
"""

from __future__ import annotations

from typing import Any, Final, Literal, get_args, get_origin

import annotated_types
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from src.config import EFFORT_AGENTS, Settings
from src.llm_models import MODEL_CAPABILITIES, ModelCapabilities

pytestmark = [pytest.mark.unit, pytest.mark.property]

#: Per-field example budget. This module's sweeps are parametrized
#: over every field rather than sampling one, and a `Settings()`
#: construction costs about a millisecond, so the profile's full
#: budget here would spend a sixth of the tier's 60-second target in
#: one file. Twenty is enough because Hypothesis tries the endpoints
#: of an integer range first, and the endpoints are what a bound is.
FIELD_EXAMPLES: Final = 20

#: Fields a `model_validator` couples to a second field: each has a
#: valid range of its own, and values inside both ranges can still
#: combine into a rejected pair. The generic sweeps would therefore fail
#: on a value that is individually correct, so each pair gets its own
#: property below — which is the better test anyway, since the coupling
#: is the interesting part.
#:
#: The chunker pair joined the list when WO-A17 added
#: `_check_chunker_budget_invariant`. This file's sweeps are what found
#: the missing check: `overlap=500` with `max=100` satisfied both Fields
#: and drove `_split_by_budget` into one chunk per character.
#:
#: `research_policy` joined it with CAP-02: its `fixed_verify_repair`
#: member is a declared value of the field that a *default* `Settings`
#: refuses, because arm C is defined by three companion flags as well as
#: by the selector (ADR 0076). The member-acceptance sweep below assumes
#: the opposite, so the coupling is asserted where it belongs —
#: `tests/test_research_policy.py` enumerates the whole 2x2x2 of
#: companion flags rather than sampling it.
COUPLED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "job_lease_ttl_sec",
        "job_lease_refresh_sec",
        "chunker_max_tokens",
        "chunker_overlap_tokens",
        "research_policy",
    }
)


def numeric_bounds(field: FieldInfo) -> tuple[float, float] | None:
    """The `[low, high]` a field accepts, or `None` if it declares none.

    `gt`/`lt` are nudged inward by one unit rather than handled as a
    separate case: every exclusive bound in this model is on a float
    field with a `0.0` floor, and "the smallest value that is not
    zero" is not a thing a settings file can express anyway.
    """
    low: float | None = None
    high: float | None = None
    for constraint in field.metadata:
        if isinstance(constraint, annotated_types.Ge):
            low = float(constraint.ge)  # type: ignore[arg-type]
        elif isinstance(constraint, annotated_types.Gt):
            low = float(constraint.gt) + 1.0  # type: ignore[operator]
        elif isinstance(constraint, annotated_types.Le):
            high = float(constraint.le)  # type: ignore[arg-type]
        elif isinstance(constraint, annotated_types.Lt):
            high = float(constraint.lt) - 1.0  # type: ignore[operator]
    if low is None or high is None:
        return None
    return low, high


def _bounded(annotation: type) -> list[str]:
    """Names of the fields of `annotation` type that declare both bounds."""
    return sorted(
        name
        for name, field in Settings.model_fields.items()
        if field.annotation is annotation
        and name not in COUPLED_FIELDS
        and numeric_bounds(field) is not None
    )


#: `Literal` fields whose *valid* members depend on `anthropic_model`
#: (CAP-01, ADR 0077). `LLM_EFFORT=xhigh` is a declared member and a
#: load-time refusal on the default model, because `xhigh` arrived with
#: Opus 4.7 and the shipped default is Sonnet 4.6 — so the
#: one-field-at-a-time sweep below cannot judge them, for the same
#: reason `COUPLED_FIELDS` exists. They keep their *rejection* sweep,
#: which only ever builds non-members, and gain a paired property that
#: checks the coupling itself.
MODEL_COUPLED_LITERALS: Final[frozenset[str]] = frozenset(
    {"llm_thinking", "llm_effort", *(f"{agent}_effort" for agent in EFFORT_AGENTS)}
)


def _literals() -> list[str]:
    """Names of the fields typed as a `Literal[...]` of strings.

    Coupled fields are excluded here for the same reason `_bounded`
    excludes them: a member this sweep would assert is accepted can be
    one a second field legitimately refuses, and the rejection sweep
    below stays correct either way (an undeclared string is still an
    undeclared string).
    """
    return sorted(
        name
        for name, field in Settings.model_fields.items()
        if get_origin(field.annotation) is Literal
        and name not in COUPLED_FIELDS
    )


def members(name: str) -> tuple[str, ...]:
    """The declared members of a `Literal` field."""
    return tuple(get_args(Settings.model_fields[name].annotation))


BOUNDED_INT_FIELDS: Final = _bounded(int)
BOUNDED_FLOAT_FIELDS: Final = _bounded(float)
LITERAL_FIELDS: Final = _literals()

# A sweep that silently swept nothing would pass. These three assert
# the derivation still finds fields at all, at import, so a change to
# pydantic's metadata shape fails loudly instead of quietly emptying
# the parametrization.
assert BOUNDED_INT_FIELDS, "no bounded int fields found in Settings"
assert BOUNDED_FLOAT_FIELDS, "no bounded float fields found in Settings"
assert LITERAL_FIELDS, "no Literal fields found in Settings"

#: The subset the accept-sweep can judge on its own.
INDEPENDENT_LITERAL_FIELDS: Final = [
    name for name in LITERAL_FIELDS if name not in MODEL_COUPLED_LITERALS
]
assert INDEPENDENT_LITERAL_FIELDS, "no independent Literal fields found"
assert set(LITERAL_FIELDS) >= MODEL_COUPLED_LITERALS, MODEL_COUPLED_LITERALS


def build(name: str, value: Any) -> Settings:
    """Construct `Settings` overriding exactly one field."""
    return Settings(**{name: value})


@pytest.mark.parametrize("name", BOUNDED_INT_FIELDS)
@settings(max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_an_int_field_accepts_and_round_trips_every_value_in_its_range(
    name: str, data: st.DataObject
) -> None:
    """A value inside a declared range is stored exactly as given."""
    low, high = numeric_bounds(Settings.model_fields[name])  # type: ignore[misc]
    value = data.draw(st.integers(min_value=int(low), max_value=int(high)))

    assert getattr(build(name, value), name) == value


@pytest.mark.parametrize("name", BOUNDED_INT_FIELDS)
@settings(max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_an_int_field_rejects_every_value_outside_its_range(
    name: str, data: st.DataObject
) -> None:
    """A value outside a declared range fails at load, not at use.

    The failure mode this prevents is not a crash — it is a settings
    object that carries a nonsense value all the way to the code that
    trusts it, where the symptom no longer names the setting.
    """
    low, high = numeric_bounds(Settings.model_fields[name])  # type: ignore[misc]
    value = data.draw(
        st.one_of(
            st.integers(max_value=int(low) - 1),
            st.integers(min_value=int(high) + 1),
        )
    )

    with pytest.raises(ValidationError):
        build(name, value)


@pytest.mark.parametrize("name", BOUNDED_FLOAT_FIELDS)
@settings(max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_a_float_field_accepts_and_round_trips_every_value_in_its_range(
    name: str, data: st.DataObject
) -> None:
    """A float inside a declared range is stored exactly as given."""
    low, high = numeric_bounds(Settings.model_fields[name])  # type: ignore[misc]
    value = data.draw(
        st.floats(
            min_value=low,
            max_value=high,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    assert getattr(build(name, value), name) == value


@pytest.mark.parametrize("name", BOUNDED_FLOAT_FIELDS)
@settings(max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_a_float_field_rejects_every_value_outside_its_range(
    name: str, data: st.DataObject
) -> None:
    """A float outside a declared range fails at load."""
    low, high = numeric_bounds(Settings.model_fields[name])  # type: ignore[misc]
    value = data.draw(
        st.one_of(
            st.floats(max_value=low - 1.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=high + 1.0, allow_nan=False, allow_infinity=False),
        )
    )

    with pytest.raises(ValidationError):
        build(name, value)


@pytest.mark.parametrize("name", INDEPENDENT_LITERAL_FIELDS)
def test_a_literal_field_accepts_every_member_it_declares(name: str) -> None:
    """Each declared member of a `Literal` field round-trips.

    Not a generated property — the member set is finite and this
    enumerates it — but it is the half that stops the rejection
    property below from being satisfied by a field that rejects
    everything.
    """
    for member in members(name):
        assert getattr(build(name, member), name) == member


@pytest.mark.parametrize("name", LITERAL_FIELDS)
@settings(max_examples=FIELD_EXAMPLES, suppress_health_check=[HealthCheck.too_slow])
@given(value=st.text(max_size=20))
def test_a_literal_field_rejects_every_string_it_does_not_declare(
    name: str, value: str
) -> None:
    """A typo in an enum-valued environment variable dies at settings load.

    This is the reason `src/config.py:27` types these fields as
    `Literal` rather than `str` in the first place: a typo'd
    `JOB_STORE=redsi` silently selecting the in-memory store is a job
    queue that loses work on restart and never says so.
    """
    declared = members(name)
    # `log_level` normalises case before validation, so a lowercase
    # spelling of a member is a member.
    assume(value not in declared and value.upper() not in declared)

    with pytest.raises(ValidationError):
        build(name, value)


@given(
    ttl=st.integers(min_value=10, max_value=3_600),
    refresh=st.integers(min_value=5, max_value=1_800),
)
@settings(max_examples=FIELD_EXAMPLES * 5)
def test_the_lease_pair_is_accepted_exactly_when_three_refreshes_fit(
    ttl: int, refresh: int
) -> None:
    """`Settings` loads iff `refresh * 3 <= ttl`, in both directions.

    Stated as an equivalence rather than as "a bad pair is rejected",
    because half of this invariant is that the check does not
    over-reject: `_check_lease_invariant` refuses a configuration an
    operator wrote deliberately, so a margin that crept upward would
    reject working deployments at start-up. Both fields are inside
    their individual ranges by construction here — the whole question
    is the coupling.
    """
    fits = refresh * 3 <= ttl

    if fits:
        loaded = Settings(job_lease_ttl_sec=ttl, job_lease_refresh_sec=refresh)
        assert loaded.job_lease_ttl_sec == ttl
        assert loaded.job_lease_refresh_sec == refresh
    else:
        with pytest.raises(ValidationError):
            Settings(job_lease_ttl_sec=ttl, job_lease_refresh_sec=refresh)


@given(
    max_tokens=st.integers(min_value=100, max_value=4_000),
    overlap=st.integers(min_value=0, max_value=500),
)
@settings(max_examples=FIELD_EXAMPLES * 5)
def test_the_chunker_pair_is_accepted_exactly_when_the_overlap_fits(
    max_tokens: int, overlap: int
) -> None:
    """`Settings` loads iff `overlap < max_tokens`, in both directions.

    An equivalence, like the lease property above, because the
    over-rejection half is the half that breaks working deployments:
    the shipped defaults are `max=800, overlap=100`, and every pair with
    an overlap under its budget must still load.

    The rejected half is the defect this tier found. Both fields are
    inside their individual ranges by construction here — `overlap` can
    reach 500 and `max_tokens` can be as low as 100 — so a pair like
    `(100, 500)` is exactly what an operator can write into an
    environment file today. `_split_by_budget` answers it by advancing
    its window one character at a time, which is not an error anyone
    sees: it is a paper turned into tens of thousands of chunks, ranked
    and partly sent to a model.
    """
    fits = overlap < max_tokens

    if fits:
        loaded = Settings(
            chunker_max_tokens=max_tokens, chunker_overlap_tokens=overlap
        )
        assert loaded.chunker_max_tokens == max_tokens
        assert loaded.chunker_overlap_tokens == overlap
    else:
        with pytest.raises(ValidationError):
            Settings(chunker_max_tokens=max_tokens, chunker_overlap_tokens=overlap)


def _member_is_supported(name: str, member: str, caps: ModelCapabilities) -> bool:
    """Whether `member` on field `name` is legal for a model with `caps`.

    Deliberately re-derived from the capability row rather than from
    `Settings`' own validator: a property that asked the validator what
    it allows and then asserted the validator allows it would pass on
    any validator.
    """
    if member in ("", "off"):
        return True
    if name == "llm_thinking":
        return member != "adaptive" or caps.adaptive_thinking
    return member in caps.effort_levels


@pytest.mark.parametrize("name", sorted(MODEL_COUPLED_LITERALS))
def test_a_model_coupled_literal_is_accepted_exactly_when_the_model_takes_it(
    name: str,
) -> None:
    """The coupling CAP-01 added, over every (member, model) pair.

    Two failure modes, and this catches both. A validator that refused
    too much would make a legal `LLM_EFFORT=xhigh` on Opus 5
    unbootable; one that refused too little would let
    `LLM_EFFORT=xhigh` reach Sonnet 4.6 and 400 on every call. The
    exclusivity — accepted *exactly when* the row allows it — is what
    neither direction alone would say.

    Not a generated property: the member set is finite, the model set
    is the shipped table, and the cross product is small enough to
    enumerate. Enumerating it is stronger than sampling it.
    """
    for member in members(name):
        for model, caps in MODEL_CAPABILITIES.items():
            # `eval_judge_model` moves with the base model because it is
            # a routed id in its own right (ADR 0070) and a global
            # `llm_effort` would reach the judges like any other call.
            # Leaving it at its default would make every case fail on
            # the judge rather than on the field under test.
            fixed = {"anthropic_model": model, "eval_judge_model": model}
            if _member_is_supported(name, member, caps):
                built = Settings(**fixed, **{name: member})
                assert getattr(built, name) == member
            else:
                with pytest.raises(ValidationError):
                    Settings(**fixed, **{name: member})
