"""Deterministic, fixture-driven judge responses for zero-spend campaigns.

This module is an execution harness, not a model simulator and not quality
evidence.  It lets the three LLM-as-judge metric paths execute under mock mode
without constructing a provider client.  Every response is derived from the
checked-in fixture and validated against a strict output model before the
metric sees it.

The surface is deliberately explicit and default-off.  Callers must construct
it through :func:`build_mock_judge_scorer`, which requires both mock data and
the repository's structural zero-spend sentinel.  The normal campaign scorer
continues to skip judges unless the operator selects this scorer.
"""

from __future__ import annotations

import contextlib
import importlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal

import pydantic
from pydantic import Field, StringConstraints, model_validator

from src.calibration.blinding import (
    HIDDEN_FROM_JUDGE,
    BlindingPlan,
    PairOrder,
    Presentation,
    assign_presentations,
    blind_item_id,
    leaked_identity_terms,
)
from src.calibration.fixtures import FIXTURE_SALT, load_pairwise
from src.campaign.errors import CampaignError
from src.campaign.execute import (
    PRIMARY_METRIC,
    EpisodeRun,
    EpisodeScores,
    deterministic_scorer,
)
from src.campaign.ledger import EpisodeScoreReceipt
from src.campaign.matrix import PlannedEpisode
from src.config import Settings
from src.contracts.kernel import ImmutableObjectRef, StrictContractModel, sha256_digest
from src.eval.benchmark_queries import BENCHMARK_QUERIES
from src.eval.metrics import (
    COMPLETENESS_RUBRIC_VERSION,
    COMPLETENESS_SYSTEM_PROMPT,
    FAITHFULNESS_RUBRIC_VERSION,
    FAITHFULNESS_SYSTEM_PROMPT,
    RETRIEVAL_RECALL_RUBRIC_VERSION,
    RETRIEVAL_RECALL_SYSTEM_PROMPT,
    ClaimSupportJudgement,
    CompletenessJudgeOutput,
    FaithfulnessJudgeOutput,
    RetrievalRecallJudgeOutput,
    TopicCoverageJudgement,
    TopicRetrievalJudgement,
)
from src.llm import LOCAL_PREVIEW_DISABLED_API_KEY

MOCK_JUDGE_FIXTURE_PATH: Final[Path] = Path(__file__).with_name(
    "mock_judge_fixture.json"
)
MOCK_JUDGE_SALT: Final[str] = "e1-mock-judge-public-fixture-salt"
MOCK_JUDGE_CREATED_AT: Final[str] = "2026-09-17T00:00:00Z"

_TOPICS_MARKER: Final[str] = "Topics expected to be covered:\n"
#: A dossier entry's opening line. The trailing letters accept the
#: disambiguating suffix ADR 0100 gives two cited papers that share a
#: surname and a year (`[Zhang, 2024a]`), and the required newline keeps
#: this anchored on the dossier rather than on a citation that happens
#: to start a line of the briefing quoted above it.
_CITED_SOURCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\[([^\]\n]+,\s*\d{4}[a-z]*)\]\n", re.MULTILINE
)
_PAPER_RE: Final[re.Pattern[str]] = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


class _TopicRule(StrictContractModel):
    """How the mock instrument decides one expected topic."""

    covered: bool
    reason: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class _FaithfulnessRule(StrictContractModel):
    """How the mock instrument decides claims, and where it abstains."""

    supported: bool
    reason: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    abstain_at: Annotated[int, Field(ge=1, le=100)]
    abstain_reason: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class _RetrievalRule(_TopicRule):
    """A topic rule that also names the papers the topic was found in."""

    paper_ids: tuple[Annotated[int, Field(ge=0)], ...]


class MockJudgeFixture(StrictContractModel):
    """The complete checked-in instruction set for the mock instrument."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    fixture_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    completeness: _TopicRule
    faithfulness: _FaithfulnessRule
    retrieval_recall: _RetrievalRule
    position_seed: Annotated[int, Field(ge=0)]
    pairwise_case_ids: tuple[
        Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")], ...
    ]

    @model_validator(mode="after")
    def pairwise_ids_are_unique(self) -> MockJudgeFixture:
        if len(set(self.pairwise_case_ids)) != len(self.pairwise_case_ids):
            raise ValueError("pairwise_case_ids must be unique")
        return self


# The synthetic instrument validates its readings against the *same*
# models the live judges are asked for (`src.eval.metrics`, ADR 0100).
# They used to be a second, stricter set defined here, which meant the
# mock could satisfy a shape the real judge was never asked for — the
# one thing an execution harness must not be able to do. The old names
# stay as aliases because they are the imported surface.
MockTopicDecision = TopicCoverageJudgement
MockCompletenessOutput = CompletenessJudgeOutput
MockClaimDecision = ClaimSupportJudgement
MockFaithfulnessOutput = FaithfulnessJudgeOutput
MockRetrievalDecision = TopicRetrievalJudgement
MockRetrievalOutput = RetrievalRecallJudgeOutput


class MockJudgeCall(StrictContractModel):
    """One schema-validated synthetic instrument reading."""

    record_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")]
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    fixture_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    rubric_name: Annotated[
        str, StringConstraints(pattern=r"^(completeness|faithfulness|retrieval_recall)$")
    ]
    rubric_version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    schema_name: Annotated[
        str,
        StringConstraints(
            pattern=(
                r"^(CompletenessJudgeOutput|FaithfulnessJudgeOutput"
                r"|RetrievalRecallJudgeOutput)$"
            )
        ),
    ]
    response: Mapping[str, Any]
    abstention_count: Annotated[int, Field(ge=0)] = 0
    leaked_identity_terms: tuple[str, ...] = ()


def load_mock_judge_fixture(
    path: Path = MOCK_JUDGE_FIXTURE_PATH,
) -> MockJudgeFixture:
    """Load and strictly validate the checked-in mock instrument fixture."""
    return MockJudgeFixture.model_validate_json(path.read_text(encoding="utf-8"))


def _topics(prompt: str) -> tuple[str, ...]:
    """The expected topics a completeness prompt lists, if it lists any."""
    if _TOPICS_MARKER not in prompt:
        return ()
    block = prompt.rsplit(_TOPICS_MARKER, 1)[1]
    return tuple(line[2:].strip() for line in block.splitlines() if line.startswith("- "))


def _citations(prompt: str) -> tuple[str, ...]:
    """The cited sources a faithfulness prompt quotes back."""
    return tuple(f"[{match}]" for match in _CITED_SOURCE_RE.findall(prompt))


@dataclass
class MockJudgeSurface:
    """A callable installed over ``src.eval.metrics.call_llm_json``."""

    fixture: MockJudgeFixture
    blinded_item_id: str
    forbidden_identity_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        self.calls: list[MockJudgeCall] = []

    def __call__(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model_name: str,
        max_tokens: int,
        schema: type[pydantic.BaseModel] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Answer one judge call from the fixture, refusing a prompt that leaked.

        `schema` and `temperature` are accepted and discarded: this
        surface stands in for the gateway, and ADR 0100 has the metrics
        pass both on every judge call. Refusing them here would make the
        mock path diverge from the live one at the signature, which is
        the one place a harness must agree with what it replaces.
        """
        del model_name, max_tokens, schema, temperature
        leaked = leaked_identity_terms(prompt, self.forbidden_identity_terms)
        if leaked:
            raise CampaignError(
                "mock judge input breached blinding; leaked identity terms: "
                + ", ".join(leaked)
            )

        if system_prompt == COMPLETENESS_SYSTEM_PROMPT:
            output: pydantic.BaseModel = MockCompletenessOutput(
                coverage=tuple(
                    MockTopicDecision(
                        topic=topic,
                        covered=self.fixture.completeness.covered,
                        reason=self.fixture.completeness.reason,
                    )
                    for topic in _topics(prompt)
                )
            )
            rubric = "completeness"
            version = COMPLETENESS_RUBRIC_VERSION
            abstentions = 0
        elif system_prompt == FAITHFULNESS_SYSTEM_PROMPT:
            claims: list[MockClaimDecision] = []
            cited = _citations(prompt) or ("[Mock, 2000]",)
            for index, cite in enumerate(cited, start=1):
                abstains = index == self.fixture.faithfulness.abstain_at
                claims.append(
                    MockClaimDecision(
                        claim=f"Synthetic fixture claim {index} for {cite}",
                        cite=cite,
                        supported=None if abstains else self.fixture.faithfulness.supported,
                        reason=(
                            self.fixture.faithfulness.abstain_reason
                            if abstains
                            else self.fixture.faithfulness.reason
                        ),
                    )
                )
            output = MockFaithfulnessOutput(claims=tuple(claims))
            rubric = "faithfulness"
            version = FAITHFULNESS_RUBRIC_VERSION
            abstentions = sum(item.supported is None for item in claims)
        elif system_prompt == RETRIEVAL_RECALL_SYSTEM_PROMPT:
            paper_count = len(_PAPER_RE.findall(prompt.split(_TOPICS_MARKER, 1)[0]))
            ids = tuple(
                paper_id
                for paper_id in self.fixture.retrieval_recall.paper_ids
                if paper_id < paper_count
            )
            output = MockRetrievalOutput(
                coverage=tuple(
                    MockRetrievalDecision(
                        topic=topic,
                        covered=self.fixture.retrieval_recall.covered,
                        paper_ids=ids,
                        reason=self.fixture.retrieval_recall.reason,
                    )
                    for topic in _topics(prompt)
                )
            )
            rubric = "retrieval_recall"
            version = RETRIEVAL_RECALL_RUBRIC_VERSION
            abstentions = 0
        else:
            raise CampaignError("mock judge received an unregistered rubric prompt")

        response = output.model_dump(mode="json")
        call = MockJudgeCall(
            record_id=f"{self.blinded_item_id}.{rubric}",
            blinded_item_id=self.blinded_item_id,
            fixture_id=self.fixture.fixture_id,
            rubric_name=rubric,
            rubric_version=version,
            schema_name=type(output).__name__,
            response=response,
            abstention_count=abstentions,
            leaked_identity_terms=leaked,
        )
        self.calls.append(call)
        return response


@contextlib.contextmanager
def mock_judge_surface(surface: MockJudgeSurface) -> Iterator[None]:
    """Install a mock responder at the metric module's bound judge seam."""
    metrics_module: Any = importlib.import_module("src.eval.metrics")
    original = metrics_module.call_llm_json
    metrics_module.call_llm_json = surface
    try:
        yield
    finally:
        metrics_module.call_llm_json = original


def _blinding_plan(fixture: MockJudgeFixture) -> BlindingPlan:
    """The blinding plan the position control is run under."""
    return BlindingPlan(
        plan_id="e1-mock-judge-position-control",
        revision=fixture.schema_version,
        salt_ref=ImmutableObjectRef(
            kind="blinding_salt",
            id="e1-mock-judge-public-fixture-salt",
            revision="1.0.0",
            digest=sha256_digest({"salt": MOCK_JUDGE_SALT}),
        ),
        hidden_fields=tuple(sorted(HIDDEN_FROM_JUDGE)),
        seed=fixture.position_seed,
        presentation=Presentation.PAIRWISE,
        both_orders=True,
        judge_sees_reference=False,
        created_at=MOCK_JUDGE_CREATED_AT,
    )


def _position_control(fixture: MockJudgeFixture) -> dict[str, Any]:
    """Read the fixture's pairwise cases in both orders, as scheduled."""
    by_id = {case.case_id: case for case in load_pairwise()}
    missing = sorted(set(fixture.pairwise_case_ids) - set(by_id))
    if missing:
        raise CampaignError(f"mock judge fixture names unknown pairwise cases: {missing}")
    selected = [by_id[case_id] for case_id in fixture.pairwise_case_ids]
    plan = _blinding_plan(fixture)
    schedule = assign_presentations(
        [blind_item_id(FIXTURE_SALT, case.case_id) for case in selected], plan=plan
    )
    real_by_blinded = {case.blinded_item_id: case for case in selected}
    readings = []
    for assignment in schedule:
        case = real_by_blinded[assignment.blinded_item_id]
        order = assignment.order
        assert order is not None
        decision = (
            case.expected_ab_verdict if order is PairOrder.AB else case.expected_ba_verdict
        )
        readings.append(
            {
                "sequence": assignment.sequence,
                "blinded_item_id": assignment.blinded_item_id,
                "presentation_order": order.value,
                "decision": decision,
            }
        )
    return {
        "plan": plan.model_dump(mode="json"),
        "readings": readings,
        "both_orders_per_pair": True,
    }


class MockJudgeScorer:
    """Score all five research metrics with three synthetic judge calls."""

    def __init__(self, fixture: MockJudgeFixture) -> None:
        self.fixture = fixture
        self.queries = {query["query_id"]: query for query in BENCHMARK_QUERIES}
        self.position_control = _position_control(fixture)

    def __call__(self, episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
        """Score one episode's metrics from the synthetic instrument's readings."""
        from src.eval.metrics import (
            measure_completeness,
            measure_faithfulness,
            measure_retrieval_recall,
        )

        query = self.queries.get(episode.case_id)
        if query is None:
            raise CampaignError(f"mock judge has no benchmark query for {episode.case_id}")
        blinded_id = blind_item_id(MOCK_JUDGE_SALT, episode.run_id)
        surface = MockJudgeSurface(
            fixture=self.fixture,
            blinded_item_id=blinded_id,
            forbidden_identity_terms=(episode.run_id, f"arm-{episode.arm_id}"),
        )
        papers = list(run.state.get("papers") or [])
        citations = list(run.state.get("citations") or [])
        with mock_judge_surface(surface):
            completeness = measure_completeness(run.report, query["expected_topics"])
            faithfulness = measure_faithfulness(run.report, papers, citations)
            retrieval = measure_retrieval_recall(papers, query["expected_topics"])

        if len(surface.calls) != 3:
            raise CampaignError(
                f"mock judge expected three rubric calls; observed {len(surface.calls)}"
            )
        free = deterministic_scorer(episode, run)
        detail = dict(free.detail)
        detail.update(
            {
                "judges_run": True,
                "judge_rubrics_skipped": [],
                "mock_judge": True,
                "mock_judge_calls": len(surface.calls),
                "metrics": {
                    "citation_resolution": detail.get("citation_resolution_rate"),
                    "supported_claim_precision": free.primary_score,
                    "completeness": completeness,
                    "faithfulness": faithfulness,
                    "retrieval_recall": retrieval,
                },
                "judge_records": [
                    call.model_dump(mode="json") for call in surface.calls
                ],
                "judge_abstentions": sum(call.abstention_count for call in surface.calls),
                "calibration_position_control": self.position_control,
            }
        )
        return EpisodeScores(
            receipt=EpisodeScoreReceipt(
                run_id=episode.run_id,
                primary_metric_available=free.receipt.primary_metric_available,
                null_reason=free.receipt.null_reason,
            ),
            primary_metric=PRIMARY_METRIC,
            primary_score=free.primary_score,
            detail=detail,
            judge_cost_usd="0.000000",
            judge_model_calls=0,
        )


def build_mock_judge_scorer(config: Settings) -> MockJudgeScorer:
    """Construct the opt-in scorer only on the structurally free path."""
    if not config.use_mock_data:
        raise CampaignError("mock judge scoring requires USE_MOCK_DATA=true")
    key = config.anthropic_api_key.get_secret_value()
    if key != LOCAL_PREVIEW_DISABLED_API_KEY:
        raise CampaignError(
            "mock judge scoring requires ANTHROPIC_API_KEY=local-preview-disabled"
        )
    return MockJudgeScorer(load_mock_judge_fixture())


__all__ = [
    "MOCK_JUDGE_FIXTURE_PATH",
    "MockCompletenessOutput",
    "MockFaithfulnessOutput",
    "MockJudgeCall",
    "MockJudgeFixture",
    "MockJudgeScorer",
    "MockJudgeSurface",
    "MockRetrievalOutput",
    "build_mock_judge_scorer",
    "load_mock_judge_fixture",
    "mock_judge_surface",
]
