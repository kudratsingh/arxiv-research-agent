"""The compute controller's decision table, row by row (ADR 0085).

`src/policies/compute.py` is the only place in this repository that
decides how much compute a run may spend, and it decides it from a
table. A table is worth having precisely because it can be enumerated,
so this module enumerates it: every rule fires when it should and does
*not* fire one step short of its threshold, the two decisive rules
outrank the escalations they contradict, and the tier that comes out
carries limits the compiled graph can actually keep.

Three properties beyond the rows, because they are the ones a later
change is most likely to break quietly:

- **Total.** Every input a `Job` can carry produces a decision. A
  feature extractor that raised would fail a run at the moment it has
  produced nothing, so `src/api/runner.py::_compute_decision` deliberately
  contains no `try`.
- **Pure.** The same features always produce the same tier, and the
  decision never reads settings, a clock or the network — which is what
  lets the same decision be re-derived from a trajectory during analysis.
- **Bounded.** `decide_tier` cannot name a tier this repository cannot
  execute. T2 arrives with CAP-03 and T3 is refused by the trajectory
  contract itself.

Nothing here compiles a graph or touches settings; the wiring lives in
`tests/test_compute_controller.py` and the trajectories in
`tests/e2e/test_compute_controller.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.policies.compute import (
    COMPUTE_TIERS,
    DEFAULT_REASON,
    LONG_QUERY_TOKENS,
    MAX_DECIDABLE_TIER,
    MULTI_ENTITY_THRESHOLD,
    PLAN_SEARCH_QUERY_THRESHOLD,
    PLAN_SUB_QUESTION_THRESHOLD,
    REASON_CODES,
    TIER_LIMITS,
    TIER_RULES,
    ComputeFeatures,
    decide_tier,
    extract_features,
)

pytestmark = pytest.mark.unit


def features(**overrides: Any) -> ComputeFeatures:
    """A T0 feature vector, with exactly the named fields moved.

    The base is deliberately the *quietest* possible run — a short
    query, no entities, no cues — so a test that changes one field is
    asserting that field's rule and nothing else.
    """
    base: dict[str, Any] = {
        "query_tokens": 4,
        "entity_count": 0,
        "comparative_cue": False,
        "freshness_cue": False,
    }
    base.update(overrides)
    return ComputeFeatures(**base)


class TestTheFeatureExtractor:
    """What the controller can see before a run has done anything."""

    def test_the_token_count_is_the_whitespace_count(self) -> None:
        assert extract_features("why do LLMs hallucinate?").query_tokens == 4

    def test_an_empty_query_is_a_feature_vector_and_not_an_error(self) -> None:
        """Totality, asserted on the input most likely to break it.

        The API refuses an empty query, but `_compute_decision` is
        reached by the redriver and by programmatic callers too, and a
        decision that raised there would fail a job before its first
        node.
        """
        empty = extract_features("")
        assert empty.query_tokens == 0
        assert empty.entity_count == 0
        assert decide_tier(empty).tier == "T0"

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("compare GPT-4 and BERT", 2),
            # Case-folded, so one system named twice is one entity.
            ("GPT-4 versus gpt-4", 1),
            # Sentence case is not an entity: "What" and "Compare" open
            # half the corpus, and counting them would make this feature
            # a proxy for "the query is a sentence".
            ("What Are Retrieval Systems", 0),
            # All-caps acronyms, internal capitals and digit-bearing
            # tokens are the three shapes that do count.
            ("RAG for arXiv at 4-bit", 3),
            # A bare year has no letter in it.
            ("papers from 2019", 0),
        ],
    )
    def test_entity_counting_is_case_shaped_not_capitalisation_shaped(
        self, query: str, expected: int
    ) -> None:
        assert extract_features(query).entity_count == expected

    @pytest.mark.parametrize(
        "query",
        [
            "transformers vs state space models",
            "Compare two retrieval strategies",
            "the trade-off between recall and latency",
            "what is the difference here",
            "pros and cons of distillation",
        ],
    )
    def test_a_comparison_word_sets_the_comparative_cue(self, query: str) -> None:
        assert extract_features(query).comparative_cue is True

    @pytest.mark.parametrize(
        "query",
        [
            # `vs` must not fire on a word that merely starts with it.
            "versatile embedding models",
            "differential privacy for embeddings",
            "how do transformers work",
        ],
    )
    def test_an_unrelated_word_does_not_set_the_comparative_cue(
        self, query: str
    ) -> None:
        assert extract_features(query).comparative_cue is False

    @pytest.mark.parametrize(
        "query",
        [
            "the latest work on retrieval",
            "state of the art in summarisation",
            "recently published quantisation results",
            "current SOTA for long context",
        ],
    )
    def test_a_recency_word_sets_the_freshness_cue(self, query: str) -> None:
        assert extract_features(query).freshness_cue is True

    def test_a_year_alone_is_not_a_freshness_cue(self) -> None:
        """"The 1998 LSTM paper" is the opposite of a freshness request."""
        assert extract_features("the 1998 LSTM paper").freshness_cue is False

    def test_the_optional_fields_default_to_unknown(self) -> None:
        """Three features no surface carries yet are `None`, not zero.

        `0` would be a claim — "this plan has no sub-questions" — and
        `_plan_breadth` would have to treat it as a quiet plan rather
        than as an unanswered question.
        """
        snapshot = extract_features("q")
        assert snapshot.requested_depth is None
        assert snapshot.task_kind is None
        assert snapshot.sub_question_count is None
        assert snapshot.search_query_count is None

    def test_the_snapshot_carries_no_query_text(self) -> None:
        """The digest and the snapshot are counts, cues and nothing else.

        This is what lets the decision ride on a
        `product_operation_only` run's trajectory while D8's retained-
        content question is open (ADR 0083).
        """
        snapshot = extract_features("why do LLMs hallucinate about Napoleon?")
        assert "Napoleon" not in repr(snapshot.as_dict())
        assert all(
            isinstance(value, (int, bool, type(None)))
            for value in snapshot.as_dict().values()
        )

    def test_the_digest_is_stable_and_discriminating(self) -> None:
        first = extract_features("why do LLMs hallucinate?")
        same = extract_features("what do LLMs invent?")
        different = extract_features("compare GPT-4 and BERT")
        assert first.digest().startswith("sha256:")
        # Same feature vector, different words: the digest is over the
        # features, which is the whole reason it can be published.
        assert first.as_dict() == same.as_dict()
        assert first.digest() == same.digest()
        assert first.digest() != different.digest()


class TestEveryRuleFiresInBothDirections:
    """One row of the table per test, and its neighbour one step short."""

    def test_a_quiet_short_query_stays_at_t0_for_the_default_reason(self) -> None:
        decision = decide_tier(features())
        assert decision.tier == "T0"
        assert decision.reasons == (DEFAULT_REASON,)

    def test_a_comparative_cue_escalates(self) -> None:
        assert decide_tier(features(comparative_cue=True)).tier == "T1"
        assert decide_tier(features(comparative_cue=False)).tier == "T0"

    def test_a_freshness_cue_escalates(self) -> None:
        assert decide_tier(features(freshness_cue=True)).tier == "T1"
        assert decide_tier(features(freshness_cue=False)).tier == "T0"

    def test_the_entity_threshold_is_the_boundary_it_declares(self) -> None:
        at = decide_tier(features(entity_count=MULTI_ENTITY_THRESHOLD))
        below = decide_tier(features(entity_count=MULTI_ENTITY_THRESHOLD - 1))
        assert (at.tier, below.tier) == ("T1", "T0")
        assert "multi_entity" in at.reasons

    def test_the_query_length_threshold_is_the_boundary_it_declares(self) -> None:
        at = decide_tier(features(query_tokens=LONG_QUERY_TOKENS))
        below = decide_tier(features(query_tokens=LONG_QUERY_TOKENS - 1))
        assert (at.tier, below.tier) == ("T1", "T0")
        assert "long_query" in at.reasons

    def test_plan_breadth_fires_on_either_count_and_never_on_unknown(self) -> None:
        """Both halves of one rule, and the `None` that is not zero."""
        by_sub_questions = features(
            sub_question_count=PLAN_SUB_QUESTION_THRESHOLD, search_query_count=1
        )
        by_queries = features(
            sub_question_count=1, search_query_count=PLAN_SEARCH_QUERY_THRESHOLD
        )
        narrow = features(
            sub_question_count=PLAN_SUB_QUESTION_THRESHOLD - 1,
            search_query_count=PLAN_SEARCH_QUERY_THRESHOLD - 1,
        )
        assert decide_tier(by_sub_questions).tier == "T1"
        assert decide_tier(by_queries).tier == "T1"
        assert decide_tier(narrow).tier == "T0"
        # Unknown counts are the pre-run case, and must not escalate.
        assert decide_tier(features()).tier == "T0"

    def test_an_explicit_quick_request_outranks_every_escalation(self) -> None:
        """The decisive half of the table, in the direction that costs.

        A caller who asked for cheap gets cheap even when four cues
        disagree — otherwise the depth field is a suggestion, and a
        suggestion is not something an experiment can hold fixed.
        """
        loud = features(
            requested_depth="quick",
            comparative_cue=True,
            freshness_cue=True,
            entity_count=5,
            query_tokens=80,
        )
        decision = decide_tier(loud)
        assert decision.tier == "T0"
        assert decision.reasons == ("depth_quick",)

    def test_an_explicit_deep_request_escalates_a_query_nothing_else_would(
        self,
    ) -> None:
        decision = decide_tier(features(requested_depth="deep"))
        assert decision.tier == "T1"
        assert decision.reasons == ("depth_deep",)

    def test_standard_depth_defers_to_the_cues(self) -> None:
        """`standard` is not a third decisive answer — it is "no opinion"."""
        assert decide_tier(features(requested_depth="standard")).tier == "T0"
        assert (
            decide_tier(features(requested_depth="standard", freshness_cue=True)).tier
            == "T1"
        )

    def test_every_matching_escalation_is_reported_in_table_order(self) -> None:
        """The reasons are the audit trail, so all of them are kept.

        Reporting only the first would make two structurally different
        escalations indistinguishable in the record — which is exactly
        the question arm E asks of it.
        """
        decision = decide_tier(
            features(comparative_cue=True, freshness_cue=True, entity_count=3)
        )
        assert decision.reasons == ("comparative_cue", "freshness_cue", "multi_entity")


class TestTheTableAndTheTiersAgree:
    def test_the_reason_codes_are_exactly_the_table_plus_the_default(self) -> None:
        """A rule added without a reason code, or the reverse, fails here."""
        assert set(REASON_CODES) == {rule.rule_id for rule in TIER_RULES} | {
            DEFAULT_REASON
        }
        assert len(REASON_CODES) == len(set(REASON_CODES))

    def test_no_rule_can_name_a_tier_the_controller_cannot_execute(self) -> None:
        assert MAX_DECIDABLE_TIER == "T1"
        assert set(COMPUTE_TIERS) == {"T0", "T1"}
        assert {rule.tier for rule in TIER_RULES} <= set(COMPUTE_TIERS)
        assert set(TIER_LIMITS) == set(COMPUTE_TIERS)

    def test_the_decision_carries_the_limits_of_the_tier_it_chose(self) -> None:
        quiet = decide_tier(features())
        loud = decide_tier(features(comparative_cue=True))
        assert quiet.limits is TIER_LIMITS["T0"]
        assert loud.limits is TIER_LIMITS["T1"]
        # T0 has no verification stage at all, which is the structural
        # difference between the two graphs and not a budget choice.
        assert (quiet.limits.max_verifications, quiet.limits.max_repairs) == (0, 0)
        assert (loud.limits.max_verifications, loud.limits.max_repairs) == (2, 1)

    def test_the_decision_keeps_the_features_it_was_taken_on(self) -> None:
        snapshot = extract_features("compare GPT-4 and BERT on long context")
        assert decide_tier(snapshot).features is snapshot

    def test_the_decision_is_deterministic_across_repeated_calls(self) -> None:
        snapshot = extract_features("the latest quantisation work on Llama-3")
        first = decide_tier(snapshot)
        second = decide_tier(extract_features("the latest quantisation work on Llama-3"))
        assert (first.tier, first.reasons) == (second.tier, second.reasons)
        assert first.features.digest() == second.features.digest()
