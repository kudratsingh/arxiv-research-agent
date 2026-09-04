"""Invariants of the request schemas at the API edge (ADR 0042, ADR 0069).

These models are the boundary between a client and an executor thread
the job timeout cannot cancel, which is why `Plan`'s list bounds exist
at all: each search query costs one arXiv call plus a hard three-second
politeness sleep, so an unbounded revised plan is a resource-exhaustion
vector rather than merely bad input (ADR 0042).

Two properties therefore matter more than the individual bounds. A
plan inside the bounds must survive a round trip through JSON, because
that is how it reaches the runner. And a plan outside them — or a
payload that is not a plan at all — must be refused with a
`ValidationError` and nothing else: the route handler turns that one
exception type into a 422, so any other exception escaping the
validator is a 500 on input the client could have been told about.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from src.api.schemas import (
    MAX_PLAN_ITEM_LEN,
    MAX_PLAN_ITEMS,
    MAX_QUERY_LEN,
    Plan,
    ResearchRequest,
    ReviewRequest,
)

pytestmark = [pytest.mark.unit, pytest.mark.property]

#: The three verbs `ReviewRequest.action` declares in its pattern.
REVIEW_ACTIONS = ("approve", "revise", "cancel")

#: `codec="utf-8"` rather than the default alphabet: a plan item is
#: serialised with `model_dump_json`, and a lone surrogate is a
#: `UnicodeEncodeError` at that point rather than anything the schema
#: has an opinion about.
_TEXT = st.text(alphabet=st.characters(codec="utf-8"))

_PLAN_ITEM = _TEXT.map(lambda s: s[:MAX_PLAN_ITEM_LEN])
_PLAN_ITEMS = st.lists(_PLAN_ITEM, max_size=MAX_PLAN_ITEMS)

#: Arbitrary JSON-shaped input, for the "never raises anything else"
#: property. Deliberately includes the wrong types in the right keys,
#: which is what a client bug actually looks like.
_ANY_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=10), children, max_size=3),
    max_leaves=6,
)


@given(sub_questions=_PLAN_ITEMS, search_queries=_PLAN_ITEMS)
def test_a_plan_inside_its_bounds_survives_a_json_round_trip(
    sub_questions: list[str], search_queries: list[str]
) -> None:
    """A plan serialised and parsed back is the plan that went in.

    The HITL loop persists a plan, shows it to a human, takes an
    edited copy back and resumes the graph from it, so the plan
    crosses the JSON boundary at least twice per review. A field that
    did not survive that would change the run a human approved into a
    different run.
    """
    plan = Plan(sub_questions=sub_questions, search_queries=search_queries)

    assert Plan.model_validate_json(plan.model_dump_json()) == plan
    assert Plan.model_validate(plan.model_dump()) == plan


@given(data=st.data())
def test_a_plan_over_either_bound_is_refused(data: st.DataObject) -> None:
    """Too many items, or one item too long, is a `ValidationError`.

    Both bounds in one property because they defend the same thing
    from two directions: the cost of a plan is `items x work per
    item`, and a cap on only one of the two factors caps nothing.
    """
    field = data.draw(st.sampled_from(["sub_questions", "search_queries"]))
    oversized = data.draw(
        st.one_of(
            st.lists(
                st.text(max_size=8),
                min_size=MAX_PLAN_ITEMS + 1,
                max_size=MAX_PLAN_ITEMS + 4,
            ),
            st.lists(
                st.text(min_size=MAX_PLAN_ITEM_LEN + 1, max_size=MAX_PLAN_ITEM_LEN + 8),
                min_size=1,
                max_size=2,
            ),
        )
    )

    with pytest.raises(ValidationError):
        Plan(**{field: oversized})


@given(payload=_ANY_JSON)
def test_validating_arbitrary_json_as_a_plan_raises_only_validation_error(
    payload: Any,
) -> None:
    """`Plan.model_validate` either returns a plan or raises `ValidationError`.

    The route handler maps that one type to a 422 and everything else
    to a 500, so "which exception" is the difference between telling a
    client what it got wrong and telling it the server is broken.
    """
    try:
        plan = Plan.model_validate(payload)
    except ValidationError:
        return

    for item in (*plan.sub_questions, *plan.search_queries):
        assert isinstance(item, str)
        assert len(item) <= MAX_PLAN_ITEM_LEN
    assert len(plan.sub_questions) <= MAX_PLAN_ITEMS
    assert len(plan.search_queries) <= MAX_PLAN_ITEMS


@given(action=st.text(max_size=16))
def test_only_the_three_declared_review_actions_are_accepted(action: str) -> None:
    """`ReviewRequest.action` admits exactly `approve`, `revise` and `cancel`.

    Stated as an equivalence over arbitrary strings because the field
    is guarded by a regex, and a regex whose anchors are wrong accepts
    `"approve\\n"` — which the handler's own `if action == "approve"`
    would then not match, leaving a job parked at its breakpoint with
    a 202 already returned to the client.
    """
    if action in REVIEW_ACTIONS:
        assert ReviewRequest(action=action).action == action
        return

    with pytest.raises(ValidationError):
        ReviewRequest(action=action)


@given(query=_TEXT)
def test_a_research_query_is_accepted_exactly_inside_its_length_bounds(
    query: str,
) -> None:
    """A query is valid iff it is non-empty and at most `MAX_QUERY_LEN` characters.

    The lower bound is the one with teeth: an empty query reaches the
    planner, which spends a model call deciding it has nothing to
    decompose.
    """
    if 1 <= len(query) <= MAX_QUERY_LEN:
        assert ResearchRequest(query=query).query == query
        return

    with pytest.raises(ValidationError):
        ResearchRequest(query=query)


@given(sub_questions=_PLAN_ITEMS, search_queries=_PLAN_ITEMS)
def test_a_review_carries_its_plan_through_unchanged(
    sub_questions: list[str], search_queries: list[str]
) -> None:
    """A plan nested inside a `revise` review is the plan that was reviewed.

    `ReviewRequest` is where an edited plan re-enters the system, and
    the nesting is the only place the two models meet: a coercion
    applied at the outer level that was not applied at the inner one
    would resume the graph from something the human did not approve.
    """
    plan = Plan(sub_questions=sub_questions, search_queries=search_queries)

    request = ReviewRequest.model_validate(
        {"action": "revise", "plan": plan.model_dump()}
    )

    assert request.plan == plan
