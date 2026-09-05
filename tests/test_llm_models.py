"""The capability table is complete, cited, and never guesses upward.

`src/llm_models.py` is a table of claims about someone else's API, so
the tests that matter are not "does the lookup work" — they are the
three ways a table like this rots:

- **It falls behind the price table.** A model priced but not described
  is a model the gateway sends the most conservative request shape to,
  silently, while the operator believes their `LLM_EFFORT` took effect.
  It is also the reason no WARNING is missed here: with the two tables
  coupled, `unknown_model_pricing_fallback` fires for exactly the
  population an unknown-capability warning would have (ADR 0077
  follow-up 2).
- **A row loses its provenance.** A capability with no cited source is
  a capability nobody can re-check when the provider changes.
- **A guess guesses upward.** Every fallback row in this module exists
  to answer for an id nobody has verified, and the whole argument for
  the design is that guessing low costs a feature while guessing high
  costs an HTTP 400 on every call.
"""

from __future__ import annotations

import pytest

from src.llm_models import (
    ALL_EFFORT,
    FAMILY_CAPABILITIES,
    MODEL_CAPABILITIES,
    UNKNOWN_MODEL_CAPABILITIES,
    ModelCapabilities,
    capabilities_for,
    is_described,
    undescribed_models,
)
from src.observability.costs import PRICES_USD_PER_MILLION

pytestmark = pytest.mark.unit


class TestTheTableCoversWhatTheRepositoryPricesA:
    """Coupling to the price table, in both directions."""

    def test_every_priced_model_has_a_capability_row(self) -> None:
        """The load-bearing one, and ADR 0077's substitute for a warning.

        `unpriced_models` warns once per process for an id with no
        price row. With this holding, an id that reaches the
        conservative capability row is also an id with no price row —
        so the existing warning names it. Drop this test and the
        undescribed-model signal silently stops existing.
        """
        missing = sorted(set(PRICES_USD_PER_MILLION) - set(MODEL_CAPABILITIES))
        assert not missing, (
            f"priced but undescribed: {missing}. Add a row to "
            "MODEL_CAPABILITIES in src/llm_models.py — until you do, the "
            "gateway sends these models no temperature, no thinking, no "
            "effort and no structured outputs."
        )

    def test_the_table_describes_nothing_the_repository_cannot_bill(self) -> None:
        """The other direction, so the table cannot grow into folklore.

        A capability row for a model with no price would let
        `max_cost_usd` be enforced at the Sonnet fallback rate for a
        model the operator was actively encouraged to route to.
        """
        extra = sorted(set(MODEL_CAPABILITIES) - set(PRICES_USD_PER_MILLION))
        assert not extra, (
            f"described but unpriced: {extra}. Add the row to "
            "PRICES_USD_PER_MILLION as well (ADR 0044)."
        )

    def test_every_row_cites_a_source(self) -> None:
        rowless = sorted(
            model
            for model, caps in {**MODEL_CAPABILITIES, **FAMILY_CAPABILITIES}.items()
            if not caps.source.strip()
        )
        assert not rowless


class TestTheDocumentedMatrix:
    """The four rows CAP-01's acceptance criteria name, spelled out.

    Transcribed from Anthropic's thinking/effort matrix rather than
    derived from the module, which is the point: a test that recomputed
    the table from the table would pass on any table.
    """

    @pytest.mark.parametrize(
        ("model", "sampling", "thinking", "effort_levels"),
        [
            # The shipped default. The last generation that accepts
            # sampling parameters, and the reason the 400 this module
            # prevents has never been seen in production.
            ("claude-sonnet-4-6", True, True, {"low", "medium", "high", "max"}),
            # Sampling accepted, thinking only in the budget_tokens form
            # this gateway does not send, effort rejected outright.
            ("claude-haiku-4-5", True, False, set()),
            # Sampling removed; thinking on by default; all five levels.
            ("claude-opus-5", False, True, ALL_EFFORT),
            ("claude-sonnet-5", False, True, ALL_EFFORT),
            ("claude-opus-4-8", False, True, ALL_EFFORT),
            ("claude-fable-5", False, True, ALL_EFFORT),
        ],
    )
    def test_a_named_model_accepts_what_the_matrix_says(
        self,
        model: str,
        sampling: bool,
        thinking: bool,
        effort_levels: set[str],
    ) -> None:
        caps = capabilities_for(model)
        assert caps.sampling_params is sampling
        assert caps.adaptive_thinking is thinking
        assert set(caps.effort_levels) == effort_levels
        assert caps.effort is bool(effort_levels)

    def test_sonnet_4_6_rejects_xhigh_specifically(self) -> None:
        """The case a boolean `effort` capability could not express.

        `xhigh` arrived with Opus 4.7. A table that only knew "effort:
        yes" would have made `LLM_EFFORT=xhigh` on the *default model* a
        runtime 400 that no load-time check could catch.
        """
        caps = capabilities_for("claude-sonnet-4-6")
        assert caps.effort is True
        assert not caps.supports_effort("xhigh")
        assert caps.supports_effort("high")


class TestResolution:
    def test_an_exact_id_wins(self) -> None:
        assert capabilities_for("claude-opus-5") is MODEL_CAPABILITIES["claude-opus-5"]

    def test_a_dated_snapshot_inherits_its_base_model(self) -> None:
        """`claude-haiku-4-5-20251001` is Haiku 4.5 and answers like it.

        The price table already carries this exact id, so the
        assertion is also that both resolution paths agree.
        """
        assert capabilities_for("claude-haiku-4-5-20260401") is capabilities_for(
            "claude-haiku-4-5"
        )

    def test_a_point_release_inherits_its_base_model(self) -> None:
        assert capabilities_for("claude-opus-5-1") is capabilities_for("claude-opus-5")

    def test_a_prefix_that_is_not_a_segment_boundary_does_not_match(self) -> None:
        """`claude-opus-50` is not a version of `claude-opus-5`.

        Mutation-check: dropping the boundary condition from
        `_longest_prefix_match` makes this resolve to the Opus 5 row,
        which would hand an unrelated id all five effort levels.
        """
        caps = capabilities_for("claude-opus-50")
        assert caps is not capabilities_for("claude-opus-5")
        assert caps is FAMILY_CAPABILITIES["claude-opus-"]

    def test_an_unknown_family_member_gets_the_family_row(self) -> None:
        caps = capabilities_for("claude-opus-9")
        assert caps is FAMILY_CAPABILITIES["claude-opus-"]

    def test_an_id_from_no_known_family_gets_the_conservative_row(self) -> None:
        assert capabilities_for("gpt-9-turbo") is UNKNOWN_MODEL_CAPABILITIES
        assert capabilities_for("claude-3-opus-20240229") is UNKNOWN_MODEL_CAPABILITIES

    def test_the_longest_family_prefix_wins_over_a_shorter_one(self) -> None:
        assert capabilities_for("claude-haiku-9") is FAMILY_CAPABILITIES[
            "claude-haiku-"
        ]


class TestEveryGuessGuessesDownward:
    """The design argument, asserted rather than described.

    A fallback row exists to answer for an id nobody verified. If one
    of them ever said "yes" to an opt-in feature, the first deployment
    to point at a new model id would discover it as a 400 on every
    call — which is the exact failure this module was written to end.
    """

    @pytest.mark.parametrize(
        "caps",
        [*FAMILY_CAPABILITIES.values(), UNKNOWN_MODEL_CAPABILITIES],
        ids=[*FAMILY_CAPABILITIES, "unknown"],
    )
    def test_no_fallback_row_enables_an_opt_in_feature(
        self, caps: ModelCapabilities
    ) -> None:
        assert caps.adaptive_thinking is False
        assert caps.effort_levels == frozenset()
        assert caps.structured_outputs is False

    def test_the_conservative_row_sends_nothing_at_all(self) -> None:
        assert UNKNOWN_MODEL_CAPABILITIES.sampling_params is False

    def test_a_family_row_keeps_only_that_family_s_sampling_answer(self) -> None:
        """Haiku still takes sampling; the frontier families do not."""
        assert FAMILY_CAPABILITIES["claude-haiku-"].sampling_params is True
        for prefix in ("claude-opus-", "claude-sonnet-", "claude-fable-"):
            assert FAMILY_CAPABILITIES[prefix].sampling_params is False


class TestUndescribedModels:
    def test_the_shipped_ids_are_all_described(self) -> None:
        assert undescribed_models(PRICES_USD_PER_MILLION) == set()

    def test_it_names_the_ids_that_fell_through(self) -> None:
        assert undescribed_models(
            ["claude-opus-5", "gpt-9-turbo", "claude-opus-9"]
        ) == {"gpt-9-turbo"}

    def test_a_family_match_counts_as_described(self) -> None:
        """It is a real row with a cited guess, not the fallback.

        The distinction matters for the ADR 0077 follow-up: an
        undescribed id is one an operator has to add a row for, and a
        family member already has one.
        """
        assert is_described("claude-opus-9") is True
        assert is_described("gpt-9-turbo") is False


class TestTheRowIsImmutable:
    def test_a_row_cannot_be_edited_in_place(self) -> None:
        """One mutated row would change every later call in the process."""
        with pytest.raises(AttributeError):
            capabilities_for("claude-opus-5").sampling_params = True  # type: ignore[misc]
