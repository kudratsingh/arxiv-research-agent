"""Every model a deployment can route to is a model the table describes.

`src/observability/costs.resolved_model_ids` derives the set of ids a
`Settings` can bill against — the base model plus every non-empty
`<agent>_model` override. ADR 0076 adds a second question about the
same set: is each of those ids *described*, or does it fall through to
the conservative row where every opt-in request feature is silently
off?

The property is that the answer is always yes for any deployment built
out of the models this repository ships. A specific test could check
the default; only a property can check the ~10^10 routings an operator
can express with ten routing fields and eleven model ids, and the
generated cases are exactly where a table falls behind — one field left
on an id somebody added to the price table and nowhere else.

`tests/test_llm_models.py` holds the two tables coupled at the set
level. This holds the coupling through the *routing*, which is the
layer that actually decides what a call sends.
"""

from __future__ import annotations

from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.config import Settings
from src.llm_models import (
    MODEL_CAPABILITIES,
    UNKNOWN_MODEL_CAPABILITIES,
    capabilities_for,
    undescribed_models,
)
from src.observability.costs import PRICES_USD_PER_MILLION, resolved_model_ids

pytestmark = [pytest.mark.unit, pytest.mark.property]

#: Every `<agent>_model` routing field, derived rather than listed so a
#: tenth agent is covered the day its field lands.
ROUTING_FIELDS: Final[tuple[str, ...]] = tuple(
    sorted(
        name
        for name in Settings.model_fields
        if name.endswith("_model") and name != "anthropic_model"
    )
)
assert ROUTING_FIELDS, "no per-agent routing fields found in Settings"

#: The ids an operator can route to and expect to be billed correctly.
PRICED_IDS: Final[tuple[str, ...]] = tuple(sorted(PRICES_USD_PER_MILLION))


#: The one `<agent>_model`-shaped field that is not an override.
#: `eval_judge_model` names the grader outright and rejects the empty
#: string, because falling back to `anthropic_model` is the defect ADR
#: 0070 closed — upgrading the product model would silently change the
#: ruler. `resolved_model_ids` counts it all the same, so it is drawn
#: here, just never empty.
NEVER_EMPTY: Final = "eval_judge_model"


@st.composite
def routings(draw: st.DrawFn) -> dict[str, str]:
    """A `Settings` kwargs dict routing agents across the priced ids.

    `""` is drawn alongside the ids because empty is the shipped
    default and means "inherit the base model" — a routing that is all
    empties is the default deployment, and it has to satisfy the
    property too.
    """
    kwargs: dict[str, str] = {"anthropic_model": draw(st.sampled_from(PRICED_IDS))}
    for field in ROUTING_FIELDS:
        choices = PRICED_IDS if field == NEVER_EMPTY else ("", *PRICED_IDS)
        kwargs[field] = draw(st.sampled_from(choices))
    return kwargs


@given(kwargs=routings())
def test_every_routed_model_resolves_to_a_real_capability_row(
    kwargs: dict[str, str],
) -> None:
    """No routing of priced models can reach the conservative fallback.

    Mutation-check: deleting any row from `MODEL_CAPABILITIES` fails
    this within a handful of examples, because the deleted id is still
    drawable from the price table.
    """
    config = Settings(**kwargs)
    assert undescribed_models(resolved_model_ids(config)) == set()


@given(kwargs=routings())
def test_no_routed_model_answers_with_the_fallback_row_object(
    kwargs: dict[str, str],
) -> None:
    """The same claim by identity rather than through the helper.

    Two statements of one property, because `undescribed_models` is the
    function under test in the first and would report an empty set for
    any input if it were broken to return one.
    """
    config = Settings(**kwargs)
    for model in resolved_model_ids(config):
        assert capabilities_for(model) is not UNKNOWN_MODEL_CAPABILITIES


@given(
    base=st.sampled_from(PRICED_IDS),
    suffix=st.from_regex(r"\A20[0-9]{6}\Z", fullmatch=True),
)
def test_a_dated_snapshot_of_any_priced_model_keeps_its_capabilities(
    base: str, suffix: str
) -> None:
    """Anthropic ships dated ids, and the price table already carries one.

    A snapshot that lost its base model's row would silently stop
    sending `temperature` on a model that takes it, or stop offering
    `effort` on one that lists it — a routing that looks like a version
    pin and behaves like a downgrade.
    """
    assert capabilities_for(f"{base}-{suffix}") is capabilities_for(base)


@given(
    model=st.sampled_from(PRICED_IDS),
    level=st.sampled_from(("low", "medium", "high", "xhigh", "max")),
)
def test_a_level_a_model_accepts_is_a_level_settings_accepts(
    model: str, level: str
) -> None:
    """The table and the validator agree, in the direction that boots.

    The reverse — the validator refusing what the table allows — is
    covered by the paired property in
    `tests/property/test_property_config.py`. This one is the
    availability half: a level the row lists must not be refusable, or
    the table is documenting a capability nobody can reach.
    """
    if level not in MODEL_CAPABILITIES[model].effort_levels:
        return
    config = Settings(
        anthropic_model=model, eval_judge_model=model, llm_effort=level
    )
    assert config.effort_for() == level
