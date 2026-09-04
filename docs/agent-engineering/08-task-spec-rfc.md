# TaskSpec contract RFC

Status: **PROPOSED — IMPLEMENTATION NOT AUTHORIZED**

Snapshot date: **2026-09-04**

Target phase: **P0 / AE-000**

This RFC defines the normalized contract for one research or guided-learning
task. It is planning, not product code or approval to run a paid experiment.
Live model calls, paid evaluations, hosted resources, training, and deployment
still require explicit owner approval before cost is incurred.

## 1. Decision summary

Adopt one immutable, versioned `TaskSpec` at the boundary between validated
product input and workflow execution. The spec says what outcome is requested
and which constraints apply. It does not select an agent policy, reveal sealed
evaluation labels, contain raw private context, or authorize spending.

The same task spec must be reusable across every arm of the first policy
experiment and every statistical repeat of the selected case. Arm identity,
model routes, prompts, seeds, and resolved runtime
configuration belong in `RunManifest`; actions and observations belong in
`TrajectoryEvent`; benchmark-only rubrics and split metadata belong in the
benchmark/data registry.

All P0 contracts use the shared `agent-contract-json/v1` wire convention:
RFC 8785 canonical JSON, algorithm-prefixed digests, fixed-decimal money
strings, and RFC 3339 UTC timestamp strings. Immutable cross-contract objects
use the shared `{kind, id, revision, digest}` reference defined below; a
locator is transport metadata and is never part of object identity.

Normative words such as **MUST**, **MUST NOT**, **SHOULD**, and **MAY** carry
their usual requirements meaning in this document.

## 2. Problem

Today a research task enters the system mainly as `ResearchRequest.query`,
plus `hitl_bypass` and optional `conversation_id`. The query is copied into a
`Job` and then into `ResearchState`. Runtime settings supply global limits and
feature flags. That is enough to run the current graph, but it cannot answer
which deliverable, source boundary, rubric, freshness rule, autonomy ceiling,
or task-specific budget the run was meant to satisfy.

A guided-reading task has a richer but different path. `SessionCreateRequest`
selects a path, resource, and optional time budget; the route resolves content
and a learner profile, constructs `session_spec` and bounded Tier-1 context,
and stores both under `Job.input_payload`. The resulting contract is useful but
is neither shared with research nor independently versioned.

The eval lanes add a third representation. Research benchmark entries carry a
query, domain, expected topics, and notes. Learning scenarios carry a persona,
paper, declared minutes, scripted turns, and expectations. Without a canonical
task contract, comparisons can accidentally vary the task while claiming to
vary only the policy.

The missing boundary causes four concrete risks:

1. an agent can optimize a prompt interpretation that differs from the product
   or evaluator's intended outcome;
2. task requirements and runtime configuration become entangled, obscuring
   what changed between experiment arms;
3. sealed rubric content can leak into the agent-visible prompt or trajectory;
4. a numeric cost ceiling can be mistaken for permission to incur cost.

## 3. Goals and non-goals

### 3.1 Goals

`TaskSpec` v1 should:

- normalize product input into a typed, bounded, deny-by-default contract;
- express the objective, deliverables, agent-visible acceptance checks,
  source/freshness scope, tool boundary, execution limits, autonomy, human
  checkpoints, context references, and data-use restrictions;
- support both the research-report and guided-learning products without
  merging their policies or metrics;
- remain identical across experiment arms A–E and all repeats for a selected
  task-case revision;
- be immutable, content-addressable, and safe to reference from a manifest;
- preserve the approved focus on task-rubric success and supported claims,
  while keeping safety and reliability as non-regression gates;
- compile and validate without any network, model, or other paid call; and
- leave enough provenance to explain how an API request or benchmark record
  became the task the workflow received.

### 3.2 Non-goals

This RFC does not:

- implement `TaskSpec`, Arm C, Arm E, or any runtime graph change;
- define the full schemas for `RunManifest`, `TrajectoryEvent`, artifacts,
  evidence, verification, feedback, or the benchmark registry;
- choose a model, prompt, agent policy, test-time compute tier, or experiment
  winner;
- expose hidden benchmark answers, sealed rubrics, judge prompts, or labels;
- authorize model spend merely because a field contains a positive ceiling;
- define consent for training, which remains blocked on decision D8;
- grant agents new tools or external side-effect authority; or
- replace the existing API request models, `Job`, `ResearchState`, or
  `SessionState` in one migration.

## 4. Current-state mapping

| Concern | Research today | Guided learning today | v1 disposition |
|---|---|---|---|
| Task identity | `Job.job_id`, eval `query_id` | session `Job.job_id`, scenario id | Add stable `task_id` and immutable `task_spec_id` |
| User intent | `ResearchRequest.query` | selected path/resource plus profile goal | Compile a bounded `objective` and typed `task_kind` |
| Deliverable | Implicit research report | Implicit checkpointed tutoring session | Make deliverables explicit |
| Rubric | Eval `expected_topics`; critic prompt | Scenario expectations and learning metrics | Keep runtime-safe checks in the spec; keep hidden evaluator material in registry |
| Sources | Current graph is arXiv-centric; flags can add sources | Curated content entry and briefing companion | Compile an explicit source policy and immutable refs |
| Freshness | Implied by query text | Curated publication snapshot | Add typed freshness semantics |
| Tools | Global graph/config decides | Session graph and content store decide | Intersect task allowlist with platform policy |
| Time | Global API timeout | available minutes plus global timeouts | Distinguish user-facing target from hard execution ceiling |
| Spend | Global research/session cost caps | Separate global session cap | Record a task ceiling, but require external approval at admission |
| Human pause | Global HITL plus request bypass | Learner turns are intrinsic | Compile named checkpoints, preserving product semantics |
| Context | Optional prior-report text reaches planner | Tier-1 profile and `session_spec` stored in payload | Store immutable references, not raw private text |
| Runtime state | `ResearchState` | `SessionState` | State keeps mutable execution data; it references the immutable spec |

The compiler MUST preserve current behavior during shadow migration. It may
make an implicit current default visible, but it must not silently broaden a
source, tool, spend, data-use, or autonomy boundary.

## 5. Ownership boundaries

```text
validated request / benchmark entry
        |
        v
TaskSpec compiler ---- platform policy + immutable context metadata
        |
        v
immutable TaskSpec ---- benchmark registry evaluator overlay (eval only)
        |
        v
admission controller ---- external cost approval and effective limits
        |
        v
RunManifest ---- policy, models, prompts, tools, seed, code, budget receipt
        |
        v
workflow ---- TrajectoryEvent stream + versioned artifacts
```

The boundaries are deliberate:

- `TaskSpec` owns requested outcomes and maximum permissions.
- Platform policy owns the absolute ceiling; compilation takes the more
  restrictive intersection.
- Admission owns whether the task may begin and whether approved funding
  exists. The task cannot approve itself.
- `RunManifest` owns resolved execution identity. A policy change creates a
  different manifest, not a different task.
- The benchmark registry owns evaluator-only rubrics, source snapshots,
  labels, split access, and contamination controls.
- `TrajectoryEvent` owns what actually occurred. It MUST NOT restate the
  complete task spec in every event.

## 6. Normative v1 schema

The implementation SHOULD use strict Pydantic v2 models at trust boundaries
and emit JSON Schema for fixtures and non-Python consumers. The following is
the normative logical shape; exact module names are an implementation detail.

```python
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SemVer = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
MoneyUsd = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{6}$")]
Rfc3339Utc = Annotated[
    str,
    Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"),
]


class ImmutableObjectRef(StrictModel):
    kind: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    revision: SemVer
    digest: Digest


class TaskKind(StrEnum):
    RESEARCH_QUICK_ANSWER = "research.quick_answer"
    RESEARCH_FOCUSED_EVIDENCE_REVIEW = "research.focused_evidence_review"
    RESEARCH_LITERATURE_SURVEY = "research.literature_survey"
    RESEARCH_METHOD_COMPARISON = "research.method_comparison"
    RESEARCH_CONTRADICTION_ANALYSIS = "research.contradiction_analysis"
    LEARNING_GUIDED_READING = "learning.guided_reading"
    RESEARCH_LONG_HORIZON = "research.long_horizon"  # reserved; reject in v1 runtime


class ProductSurface(StrEnum):
    RESEARCH_API = "research_api"
    GUIDED_LEARNING_API = "guided_learning_api"
    RESEARCH_EVAL = "research_eval"
    LEARNING_EVAL = "learning_eval"


class DeliverableKind(StrEnum):
    ANSWER = "answer"
    RESEARCH_REPORT = "research_report"
    EVIDENCE_TABLE = "evidence_table"
    COMPARISON_MATRIX = "comparison_matrix"
    CONTRADICTION_MAP = "contradiction_map"
    GUIDED_SESSION = "guided_session"
    SESSION_SUMMARY = "session_summary"
    ASSESSMENT_RECORD = "assessment_record"


class DeliverableSpec(StrictModel):
    deliverable_id: Annotated[str, Field(pattern=r"^del_[a-z0-9_]{1,48}$")]
    kind: DeliverableKind
    required: bool = True
    media_type: Annotated[str, Field(max_length=100)]
    description: Annotated[str, Field(min_length=1, max_length=500)]


class CheckClass(StrEnum):
    PRIMARY_OUTCOME = "primary_outcome"
    NON_REGRESSION = "non_regression"
    DIAGNOSTIC = "diagnostic"


class VerificationMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    SOURCE_GROUNDED = "source_grounded"
    MODEL_JUDGE = "model_judge"
    HUMAN = "human"


class AcceptanceCheck(StrictModel):
    check_id: Annotated[str, Field(pattern=r"^chk_[a-z0-9_]{1,48}$")]
    check_class: CheckClass
    subject_deliverable_ids: tuple[str, ...]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    verification_method: VerificationMethod
    metric_key: Annotated[str, Field(min_length=1, max_length=100)]
    rubric_item_ref: ImmutableObjectRef | None = None
    threshold: Decimal | None = None
    required_evidence: bool = False


class CorpusMode(StrEnum):
    LIVE = "live"
    SNAPSHOT = "snapshot"
    SUPPLIED = "supplied"
    CURATED = "curated"


class SourceScope(StrictModel):
    policy_ref: ImmutableObjectRef
    corpus_mode: CorpusMode
    allowed_providers: tuple[str, ...]
    allowed_source_types: tuple[str, ...]
    snapshot_ref: ImmutableObjectRef | None = None
    supplied_corpus_refs: tuple[ImmutableObjectRef, ...] = ()
    publication_not_before: date | None = None
    publication_not_after: date | None = None
    minimum_distinct_sources: Annotated[int, Field(ge=0, le=100)] = 0
    primary_sources_preferred: bool = True


class FreshnessMode(StrEnum):
    NO_REQUIREMENT = "no_requirement"
    AS_OF = "as_of"
    LATEST_AVAILABLE = "latest_available"
    MAX_AGE_DAYS = "max_age_days"


class FreshnessRequirement(StrictModel):
    mode: FreshnessMode
    as_of: Rfc3339Utc | None = None
    max_age_days: Annotated[int | None, Field(ge=0, le=36_500)] = None


class ToolPolicy(StrictModel):
    policy_ref: ImmutableObjectRef
    allowed_agent_tools: tuple[str, ...]
    denied_action_ids: tuple[str, ...]
    network_access: Literal["none", "allowlisted"]
    external_side_effects: Literal["none"] = "none"


class WorkflowCostBoundary(StrictModel):
    chargeable_work: Literal[
        "forbidden", "requires_external_approval"
    ] = "forbidden"
    workflow_spend_ceiling_usd: MoneyUsd


class ExecutionLimits(StrictModel):
    target_latency_seconds: Annotated[int | None, Field(ge=1, le=86_400)] = None
    hard_timeout_seconds: Annotated[int, Field(ge=1, le=86_400)]
    max_tool_calls: Annotated[int, Field(ge=0, le=10_000)]
    max_model_calls: Annotated[int, Field(ge=0, le=10_000)]
    workflow_cost: WorkflowCostBoundary


class AutonomyTier(StrEnum):
    A0_DRAFT = "A0"
    A1_BOUNDED_TOOLS = "A1"
    A2_SANDBOXED_PLAN = "A2"
    A3_PROPOSE_SIDE_EFFECT = "A3"
    A4_REVERSIBLE_SIDE_EFFECT = "A4"


class HumanCheckpoint(StrictModel):
    checkpoint_id: Annotated[str, Field(pattern=r"^hcp_[a-z0-9_]{1,48}$")]
    kind: Literal[
        "plan_review", "learner_turn", "clarification", "spend_approval",
        "external_action_approval", "final_review"
    ]
    trigger: Literal["always", "on_condition"]
    condition_code: str | None = None
    blocking: bool = True


class AutonomyPolicy(StrictModel):
    maximum_tier: AutonomyTier
    human_checkpoints: tuple[HumanCheckpoint, ...] = ()


class ContextRef(StrictModel):
    object_ref: ImmutableObjectRef
    locator: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    kind: Literal[
        "conversation_summary", "supplied_corpus", "content_entry",
        "learner_profile_snapshot", "prior_session_summary", "prior_artifact"
    ]
    purpose: Annotated[str, Field(min_length=1, max_length=200)]


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    USER_CONFIDENTIAL = "user_confidential"
    LEARNER_SENSITIVE = "learner_sensitive"


class DataPolicy(StrictModel):
    policy_ref: ImmutableObjectRef
    data_class: DataClass
    processing_purposes: tuple[
        Literal["product_operation", "support", "aggregate_analytics"], ...
    ]
    training_use: Literal["prohibited"] = "prohibited"
    retention_policy_ref: ImmutableObjectRef


class BenchmarkOrigin(StrictModel):
    suite_ref: ImmutableObjectRef
    task_set_ref: ImmutableObjectRef
    task_case_ref: ImmutableObjectRef


class TaskProvenance(StrictModel):
    compiler_ref: ImmutableObjectRef
    source_kind: Literal["api_request", "benchmark_registry", "migration"]
    source_id: Annotated[str, Field(min_length=1, max_length=200)]
    compiled_at: Rfc3339Utc


class TaskSpecV1(StrictModel):
    schema_kind: Literal["task-spec"]
    schema_version: Literal["1.0.0"]
    task_spec_id: Annotated[str, Field(pattern=r"^tsp_[a-z0-9]{16,32}$")]
    task_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")]
    task_revision: Annotated[int, Field(ge=1)] = 1
    supersedes_task_spec_id: str | None = None
    task_kind: TaskKind
    product_surface: ProductSurface
    objective: Annotated[str, Field(min_length=1, max_length=8_000)]
    deliverables: Annotated[tuple[DeliverableSpec, ...], Field(min_length=1, max_length=12)]
    acceptance_checks: Annotated[
        tuple[AcceptanceCheck, ...], Field(min_length=1, max_length=64)
    ]
    source_scope: SourceScope
    freshness: FreshnessRequirement
    tool_policy: ToolPolicy
    execution_limits: ExecutionLimits
    autonomy: AutonomyPolicy
    context_refs: Annotated[tuple[ContextRef, ...], Field(max_length=64)] = ()
    data_policy: DataPolicy
    benchmark_origin: BenchmarkOrigin | None = None
    provenance: TaskProvenance


# Owned and serialized by RunManifest, never embedded in TaskSpecV1.
class TaskSpecRef(StrictModel):
    task_spec_id: str
    schema_kind: Literal["task-spec"]
    schema_version: Literal["1.0.0"]
    task_revision: int
    full_digest: Digest
    semantic_digest: Digest
    artifact_ref: ImmutableObjectRef
    artifact_locator: str | None = None
    effective_data_class: DataClass
```

The implementation MAY use narrower per-product discriminated unions, but its
serialized form MUST preserve the fields and invariants below.

## 7. Field semantics

| Field | Required | Meaning and owner |
|---|---:|---|
| `schema_kind` | yes | Contract family, exactly `task-spec` |
| `schema_version` | yes | Semantic schema version, exactly `1.0.0` |
| `task_spec_id` | yes | Unique id for this immutable revision; never reused |
| `task_id` | yes | Stable logical task id across retries, arms, and spec revisions |
| `task_revision` | yes | Monotonic integer revision within a logical task |
| `supersedes_task_spec_id` | no | Prior immutable revision when clarification changes the task |
| `task_kind` | yes | Product/outcome taxonomy; not the workflow or policy selector |
| `product_surface` | yes | Intake surface used to select compiler and default policy ceiling |
| `objective` | yes | Normalized user or benchmark objective; not a hidden answer key |
| `deliverables` | yes | Required output artifacts and media types |
| `acceptance_checks` | yes | Agent-visible outcome and integrity checks only |
| `source_scope` | yes | Maximum admissible corpus/provider boundary |
| `freshness` | yes | Temporal interpretation of source selection and claims |
| `tool_policy` | yes | Requested allowlist further restricted by platform policy |
| `execution_limits` | yes | User/product target plus hard bounds; no authority grant |
| `autonomy` | yes | Maximum agent authority and named blocking checkpoints |
| `context_refs` | no | Typed immutable references to context; locator kept separate from identity |
| `data_policy` | yes | Permitted handling; v1 always prohibits training use |
| `benchmark_origin` | no | Exact suite/task-set/task-case lineage; control-plane only for restricted cases |
| `provenance` | yes | Compiler identity and non-secret source pointer |

`TaskSpecRef` is not a field in the stored task. It is a `RunManifest`-owned
reference to the stored task and contains `task_spec_id`, schema kind/version,
`task_revision`, full and semantic digests, the immutable artifact ref, and the
optional transport locator plus effective data class. The locator is not object
identity and is excluded from equivalence. This avoids a self-referential task
digest.

### Shared reference and wire rules

- Every `ImmutableObjectRef` has exactly `kind`, `id`, semantic `revision`, and
  algorithm-prefixed `digest`. Its optional locator is carried by the resolver
  or a containing binding, never used as identity, and never hashed as a
  substitute for referenced content.
- `agent-contract-json/v1` means UTF-8 RFC 8785 canonical JSON. Reference
  digests are lowercase SHA-256 in `sha256:<64 hex>` form.
- `TaskSpecRef.full_digest` hashes the complete stored `TaskSpecV1` canonical
  object. `semantic_digest` hashes the behavior/evaluation-bearing projection,
  excluding `task_spec_id`, `task_revision`, `supersedes_task_spec_id`, and
  `provenance`; it is for equivalence analysis, not a substitute for exact
  artifact verification.
- All timestamps are RFC 3339 UTC strings ending in `Z`. Date-only publication
  bounds remain ISO 8601 calendar dates.
- USD limits are fixed six-decimal strings. Floats are invalid in canonical
  contract artifacts; actual cost events use the same representation.
- The shared `DataClass` order is `public < internal < user_confidential <
  learner_sensitive`. Admission records the most restrictive applicable class
  in `TaskSpecRef.effective_data_class`.

### 7.1 Task kinds and minimum deliverables

| Task kind | Minimum required deliverable | Primary product outcome | Maximum initial tier |
|---|---|---|---|
| `research.quick_answer` | `answer` | concise supported answer | A1 |
| `research.focused_evidence_review` | `research_report`, `evidence_table` | supported claims and evidence coverage | A1 |
| `research.literature_survey` | `research_report`, `evidence_table` | rubric coverage with admissible sources | A1 |
| `research.method_comparison` | `research_report`, `comparison_matrix` | supported comparison across named axes | A1 |
| `research.contradiction_analysis` | `research_report`, `contradiction_map` | faithful disagreement and uncertainty | A1 |
| `learning.guided_reading` | `guided_session`, `session_summary` | pedagogical fit and honest learning evidence | A1 |
| `research.long_horizon` | not executable in v1 | future project success | reserved; reject |

The taxonomy describes user intent. Arms A–E are policies, not task kinds.
Adaptive tiers T0–T2 are execution choices, not task kinds. Keeping those
axes separate is required for the approved causal comparisons.

### 7.2 Acceptance checks and the approved scorecard

Every executable spec MUST contain at least one `primary_outcome` check and
the product's common `non_regression` checks. Checks MUST remain separate;
the compiler MUST NOT replace them with one weighted agent score.

For the first research-policy experiment, every task uses:

- task-specific rubric success and supported-claim precision as distinct
  primary checks;
- prompt/source isolation, citation validity, completion, privacy/principal
  scoping, and budget adherence as non-regression checks; and
- cost, latency, human preference, edit burden, verifier calibration, and
  action efficiency as diagnostics or frontier dimensions outside a blended
  promotion score.

`acceptance_checks` contains only instructions safe for the policy to know. A
candidate-visible registry rubric item may be linked by `rubric_item_ref`; the
local `check_id` remains stable within the task and is not silently equated to
the registry's independently revisioned `rubric_item_id`.
Expected paper ids, exact source spans, withheld rubric items, judge prompts,
human labels, validation/canary split membership, and pass thresholds used only
for promotion MUST stay in the registry's evaluator overlay. Grader-profile,
label, hidden-rubric, and split refs never belong in `TaskSpec`. For restricted
cases, the runtime projection MUST also omit `benchmark_origin`; the evaluation
control plane retains the full stored spec and its lineage.

`allowed_agent_tools` names capabilities the policy can choose to invoke.
Internal components such as a parser, chunker, or ranker are recorded and
hashed in `RunManifest`, but are not additional task permissions unless the
agent can invoke them independently. Tool ids and `denied_action_ids` come from
one controlled vocabulary shared with the manifest's effective policy; aliases
such as `write_repository` and `repository_write` are not interchangeable.

### 7.3 Source and freshness rules

- The platform MUST reject a provider not allowed by both the task and the
  deployed platform policy.
- `snapshot_ref` is required for `corpus_mode=snapshot`; supplied corpus refs
  are required for `supplied`; neither is permitted for unrelated modes.
- A registry `SourceSnapshot` owns the immutable content. `TaskSpec` declares
  the maximum admissible source policy and, for a controlled task, its required
  snapshot ref. The campaign locks the effective ref and `RunManifest` pins it.
  Admission requires the manifest ref to equal the task's required snapshot or
  be a permitted narrowing when the task declares only a policy boundary.
- `as_of` is required only for `freshness.mode=as_of`; `max_age_days` is
  required only for `max_age_days`.
- `publication_not_before` MUST be no later than `publication_not_after`.
- Access time, source identity, and actual retrieval provenance belong in the
  trajectory/artifact layer. The task records the requested boundary.
- The first five-arm controlled comparison SHOULD use one immutable source
  snapshot where practical; a live-retrieval robustness sweep is separate.

### 7.4 Cost and authority rules

A positive `workflow_spend_ceiling_usd` is a limit, never an approval receipt.
It covers task/workflow execution only. Evaluator, campaign, paid-dataset,
sandbox, GPU, and hosted-resource ceilings are separate `RunManifest` or
campaign-manifest concerns.

- `chargeable_work=forbidden` requires a zero ceiling and admission MUST reject
  any model/tool route that can incur external cost.
- `chargeable_work=requires_external_approval` means admission MUST find a
  separate, valid approval record whose cap is at least the effective campaign
  or episode allocation before making a chargeable call.
- The effective workflow cap is the minimum of task, platform, campaign, provider,
  and approval ceilings. `RunManifest` records those inputs and the resolved
  cap; `TaskSpec` does not contain credentials or an approval token.
- Compilation, schema validation, fixture replay, mocked policy-shape tests,
  and dry-run matrix generation MUST remain no-cost.
- The approved five-arm design did not authorize Arm C or E implementation,
  a paid smoke test, the full campaign, or policy promotion.

### 7.5 Data and context rules

- Context refs MUST point to immutable, access-controlled objects and include a
  digest. The compiler MUST NOT embed raw PDF text, conversation text, learner
  messages, profile notes, secrets, or credentials in a `TaskSpec`.
- A principal id is access-control context, not research content. It stays in
  authenticated job ownership metadata and MUST NOT be exported in public
  experiment artifacts.
- Learner context defaults to `learner_sensitive`; research conversation
  context defaults to `user_confidential`; benchmark public corpora may be
  `public`.
- Registry permitted evaluation uses and TaskSpec `processing_purposes` are
  separate axes. The first governs whether a suite may support development,
  regression, calibration, or promotion; the second governs handling of the
  task's data. Admission enforces both and cannot broaden either.
- v1 fixes `training_use=prohibited`. D8 must be approved and a later schema
  revision must define consent, retraction, deletion, and lineage before any
  task data becomes training material.
- Data policy can narrow the platform's retention and use policy but cannot
  broaden it.

## 8. Complete research example

This example represents one method-comparison task shared by arms A–E. It
requires external approval before any chargeable execution; the object itself
does not establish that approval.

```json
{
  "schema_kind": "task-spec",
  "schema_version": "1.0.0",
  "task_spec_id": "tsp_01k4x9q7d4m2n8pv",
  "task_id": "research-policy-v1:lora-vs-full-finetune",
  "task_revision": 1,
  "supersedes_task_spec_id": null,
  "task_kind": "research.method_comparison",
  "product_surface": "research_eval",
  "objective": "Compare LoRA and full fine-tuning for domain adaptation, including quality, compute and memory cost, and failure modes.",
  "deliverables": [
    {
      "deliverable_id": "del_report",
      "kind": "research_report",
      "required": true,
      "media_type": "text/markdown",
      "description": "A concise comparative report with claim-level citations."
    },
    {
      "deliverable_id": "del_comparison",
      "kind": "comparison_matrix",
      "required": true,
      "media_type": "application/json",
      "description": "A comparison across quality, memory, compute, and adaptation risks."
    }
  ],
  "acceptance_checks": [
    {
      "check_id": "chk_task_rubric",
      "check_class": "primary_outcome",
      "subject_deliverable_ids": ["del_report", "del_comparison"],
      "description": "Satisfy the agent-visible comparison requirements with admissible evidence.",
      "verification_method": "source_grounded",
      "metric_key": "task_rubric_success",
      "rubric_item_ref": {
        "kind": "rubric_item",
        "id": "task-rubric-success",
        "revision": "1.0.0",
        "digest": "sha256:1111111111111111111111111111111111111111111111111111111111111111"
      },
      "threshold": null,
      "required_evidence": true
    },
    {
      "check_id": "chk_supported_claims",
      "check_class": "primary_outcome",
      "subject_deliverable_ids": ["del_report", "del_comparison"],
      "description": "Every material factual claim is supported, qualified, removed, or explicitly marked unresolved.",
      "verification_method": "source_grounded",
      "metric_key": "supported_claim_precision",
      "rubric_item_ref": {
        "kind": "rubric_item",
        "id": "supported-claim-precision",
        "revision": "1.0.0",
        "digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222"
      },
      "threshold": null,
      "required_evidence": true
    },
    {
      "check_id": "chk_citations_valid",
      "check_class": "non_regression",
      "subject_deliverable_ids": ["del_report"],
      "description": "Every citation resolves to an admissible source and accurately identifies it.",
      "verification_method": "deterministic",
      "metric_key": "citation_validity",
      "rubric_item_ref": {
        "kind": "rubric_item",
        "id": "citation-validity",
        "revision": "1.0.0",
        "digest": "sha256:3333333333333333333333333333333333333333333333333333333333333333"
      },
      "threshold": "1.0",
      "required_evidence": true
    }
  ],
  "source_scope": {
    "policy_ref": {
      "kind": "source_policy",
      "id": "arxiv-snapshot-readonly",
      "revision": "1.0.0",
      "digest": "sha256:4444444444444444444444444444444444444444444444444444444444444444"
    },
    "corpus_mode": "snapshot",
    "allowed_providers": ["arxiv"],
    "allowed_source_types": ["paper", "paper_metadata"],
    "snapshot_ref": {
      "kind": "source_snapshot",
      "id": "research-policy-v1-corpus",
      "revision": "1.0.0",
      "digest": "sha256:5555555555555555555555555555555555555555555555555555555555555555"
    },
    "supplied_corpus_refs": [],
    "publication_not_before": null,
    "publication_not_after": "2026-09-04",
    "minimum_distinct_sources": 2,
    "primary_sources_preferred": true
  },
  "freshness": {
    "mode": "as_of",
    "as_of": "2026-09-04T00:00:00Z",
    "max_age_days": null
  },
  "tool_policy": {
    "policy_ref": {
      "kind": "tool_policy",
      "id": "research-arxiv-readonly",
      "revision": "1.0.0",
      "digest": "sha256:6666666666666666666666666666666666666666666666666666666666666666"
    },
    "allowed_agent_tools": ["arxiv_search", "pdf_reader"],
    "denied_action_ids": ["repository_write", "external_publish", "deploy", "send_message"],
    "network_access": "allowlisted",
    "external_side_effects": "none"
  },
  "execution_limits": {
    "target_latency_seconds": 300,
    "hard_timeout_seconds": 900,
    "max_tool_calls": 50,
    "max_model_calls": 40,
    "workflow_cost": {
      "chargeable_work": "requires_external_approval",
      "workflow_spend_ceiling_usd": "2.000000"
    }
  },
  "autonomy": {
    "maximum_tier": "A1",
    "human_checkpoints": []
  },
  "context_refs": [],
  "data_policy": {
    "policy_ref": {
      "kind": "data_policy",
      "id": "eval-public-no-training",
      "revision": "1.0.0",
      "digest": "sha256:7777777777777777777777777777777777777777777777777777777777777777"
    },
    "data_class": "public",
    "processing_purposes": ["product_operation", "aggregate_analytics"],
    "training_use": "prohibited",
    "retention_policy_ref": {
      "kind": "retention_policy",
      "id": "eval-artifacts",
      "revision": "1.0.0",
      "digest": "sha256:8888888888888888888888888888888888888888888888888888888888888888"
    }
  },
  "benchmark_origin": {
    "suite_ref": {
      "kind": "benchmark_suite",
      "id": "research-policy-v1",
      "revision": "1.0.0",
      "digest": "sha256:9999999999999999999999999999999999999999999999999999999999999999"
    },
    "task_set_ref": {
      "kind": "task_set",
      "id": "research-policy-tasks",
      "revision": "1.0.0",
      "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    },
    "task_case_ref": {
      "kind": "task_case",
      "id": "lora-vs-full-finetune",
      "revision": "1.0.0",
      "digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  },
  "provenance": {
    "compiler_ref": {
      "kind": "task_compiler",
      "id": "default-task-compiler",
      "revision": "0.1.0",
      "digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    },
    "source_kind": "benchmark_registry",
    "source_id": "research-policy-v1:lora-vs-full-finetune",
    "compiled_at": "2026-09-04T12:00:00Z"
  }
}
```

Production API tasks omit `benchmark_origin`. A guided-reading
spec uses `learning.guided_reading`, `guided_session` plus `session_summary`, a
curated `content_entry` context ref, an access-controlled
`learner_profile_snapshot` ref, learner-turn checkpoints, the declared minutes
as the user-facing target, and `learner_sensitive` data handling. It never
copies the profile or transcript into the spec.

## 9. Compilation and lifecycle

### 9.1 Lifecycle

1. **Validate intake.** Existing API/registry models validate bounded input and
   authenticate ownership before compilation.
2. **Resolve references.** The compiler resolves only metadata required to
   bind content/profile/conversation refs and hashes. It does not execute an
   agent or call a model.
3. **Apply product defaults.** A product-specific, versioned compiler supplies
   explicit defaults for implicit current behavior.
4. **Intersect policies.** Source, tools, autonomy, timeout, cost, and data use
   are narrowed against platform policy.
5. **Validate semantics.** Cross-field rules, unique ids, references, bounds,
   executable task-kind support, and hidden-rubric separation are checked.
6. **Canonicalize and persist.** Serialize through `agent-contract-json/v1`,
   compute the full and semantic digests, store the immutable object, and write
   a bounded pre-run `TaskCompilationReceipt`. Compilation is not part of the
   trajectory because no run exists yet.
7. **Admit and bind.** Admission verifies authorization, available
   infrastructure, source snapshot, and effective limits. Paid approval happens
   outside the spec. `RunManifest` writes `TaskSpecRef`, resolved limits,
   policy/configuration, and approval receipt metadata, then seals atomically.
8. **Start the trajectory.** Only after manifest sealing succeeds may the
   orchestrator append the first `TrajectoryEvent` carrying the run and
   manifest identity. No compilation event is backfilled into the trajectory.
9. **Execute and evaluate.** The workflow reads an agent-safe projection; the
   evaluator separately resolves its registry overlay.
10. **Retain or expire.** The data policy controls references and artifacts;
    audit metadata retains no raw private content.

### 9.2 Immutability and revision

Once persisted, a spec MUST NOT be updated in place. A clarification, changed
deliverable, source expansion, or changed limit produces a new
`task_spec_id`, increments `task_revision`, and sets
`supersedes_task_spec_id`. Retries, experiment arms, and statistical repeats
reuse the same stored spec unless the intended task changed. Recompiling
identical source material MAY produce a new id outside a locked campaign, but
its semantic digest SHOULD match.

Schema evolution changes `schema_version` under the constant
`schema_kind=task-spec`. Readers MUST reject unsupported major versions rather
than ignore unknown fields. Additive compatible fields use a schema minor;
validator-only clarifications use a patch. A compiler implementation change
updates `provenance.compiler_ref` independently.

### 9.3 Semantic validation rules

The validator MUST reject:

- duplicate deliverable, check, checkpoint, or context ids;
- acceptance checks that reference missing deliverables;
- no primary outcome or missing product non-regression checks;
- a task kind whose required deliverables are absent;
- the reserved long-horizon kind in the initial runtime;
- source/freshness combinations that violate section 7.3;
- tools, side effects, or autonomy beyond the platform ceiling;
- `A0` with tool calls, or current A0–A2 tasks with external side effects;
- a zero-call task whose required deliverable needs model/tool execution;
- `chargeable_work=forbidden` with a nonzero workflow ceiling;
- benchmark origin refs that do not exactly resolve to the selected suite,
  task set, and task case;
- raw context embedded where an immutable ref is required;
- training use other than `prohibited`; and
- a non-UTC timestamp or a reference whose digest cannot be resolved at
  admission.

## 10. Product-specific compilation

### 10.1 Research API

Initial shadow compilation maps current fields as follows:

- `ResearchRequest.query` becomes `objective` without model rewriting;
- the conservative default kind is `research.focused_evidence_review`, unless
  an explicit future API field selects another supported kind;
- the current report becomes the required `research_report` deliverable;
- current arXiv-only behavior becomes an explicit source/tool policy;
- `conversation_id` becomes an access-checked, hash-bound
  `conversation_summary` ref, not copied prior-report prose;
- HITL configuration becomes a `plan_review` checkpoint. `hitl_bypass` is an
  execution/admission override recorded in the manifest, not a new task; and
- global time and cost settings supply upper bounds. They do not grant paid
  authorization.

No LLM should classify the task kind in v1. Use an explicit API field when the
product exposes multiple kinds; until then, use deterministic surface defaults
and preserve the original query.

### 10.2 Guided-learning API

Compilation occurs after authenticated resolution of path, entry, learner
profile, and available minutes:

- `path_id` and `resource_id` become a curated `content_entry` ref;
- the bounded Tier-1 block becomes a `learner_profile_snapshot` ref;
- any previous session memory becomes a `prior_session_summary` ref;
- the task kind is `learning.guided_reading`;
- deliverables include the interactive session and closing summary;
- learner turns are mandatory human checkpoints, not optional HITL reviews;
- `available_minutes` is a product target; server session timeout and maximum
  turns remain hard effective limits in the manifest; and
- the task uses the session cost ceiling and `learner_sensitive` data policy.

Research acceptance checks MUST NOT be reused as pedagogy rewards. Guided
learning keeps separate plan-fit, misconception, assessment, continuity, and
honest-abstention metrics.

## 11. Experiment applicability

For each selected task-case revision in the approved first policy experiment:

1. compile or load exactly one stored task spec before expanding arms/repeats;
2. bind its same id, full digest, and semantic digest into every manifest for
   arms A, B, C, D, and E across all repeats;
3. vary only the policy/configuration declared by the experimental matrix;
4. keep query refinement and reader recovery disabled in all arms;
5. retain the fixed graph as control and fallback; and
6. fail the episode before execution if any arm or repeat's task ref differs.

The registry compiles one task contract per selected task-case revision and
applies it to every planned arm/repeat episode for that case. Repeat identity,
seed, and attempt lineage belong to `RunManifest`. This keeps all repeats in
one replicate group even though each has a new `run_id`.

Arm B's evidence path does not change `required_evidence`; all arms are judged
against the same intended outcome even if Arm A lacks typed evidence support.
Arm C's bounded repair and Arm E's adaptive tier are manifest/policy facts.
They MUST NOT be represented by changing the task's autonomy or limits unless
that change is itself a separately designed experiment.

The checked-in 20-query suite is a visible development benchmark. Its task
specs may carry agent-visible comparison requirements, while exact expected
topics and scoring overlays remain registry-controlled. Later validation and
canary specs follow the same contract with stricter access controls.

## 12. Cross-contract integrations

### 12.1 `RunManifest`

The manifest MUST include the complete `TaskSpecRef`: task-spec id, schema
kind/version, integer task revision, full digest, semantic digest, immutable
artifact ref, and effective data class. It resolves policy selector, graph shape,
model routes, prompt/tool versions, code commit, source snapshot, seed,
effective budgets, environment, and cost approval receipt. The manifest must
prove that all effective permissions are equal to or narrower than the spec.

### 12.2 `TrajectoryEvent`

Every event links to `run_id`; the run manifest supplies the task relation.
Events SHOULD use deliverable/check/context ids when relevant. They record
policy decisions, costs, observations, failures, abstentions, and stop reasons,
but MUST NOT duplicate raw context, evaluator overlays, secrets, or hidden
labels. Task compilation produces a pre-run `TaskCompilationReceipt`, not a
trajectory event. The first trajectory event is appended only after the
manifest has been sealed and contains its manifest digest.

### 12.3 Benchmark/data registry

Registry entries own suite/task-case lineage, split, licenses, source snapshots,
evaluator overlays, judge versions, human labels, and contamination canaries.
The TaskSpec compiler owns the logical task id and stored TaskSpec artifact;
`benchmark_origin` records the exact registry inputs. The runtime receives only
an agent-safe task-spec projection.
Access to validation/canary overlays is limited to the evaluation control
plane, and the candidate policy cannot modify them.

### 12.4 Artifacts and evidence

Deliverable ids become stable subjects for artifact lineage. Acceptance checks
refer to deliverable ids; verification results refer to both. Context refs use
the future `ArtifactRef` contract. Candidate revisions create new artifacts
and parent links rather than overwrite prior drafts.

## 13. Migration and backfill

### Phase M0 — schema and compiler fixtures

- implement strict models, semantic validators, canonical serialization, and
  product compiler interfaces behind no runtime flag;
- add static fixtures for one research request, one conversation follow-up,
  one guided session, and several invalid/adversarial inputs; and
- generate JSON Schema and document compatibility policy.

### Phase M1 — shadow compilation

- compile a spec at research/session intake but do not change graph inputs;
- compare deterministic projections against the current `Job`, state, global
  limits, session spec, and eval inputs;
- record only bounded ids/digests in local test artifacts; and
- reject no production request solely because shadow compilation failed until
  the error rate and mappings have been reviewed.

### Phase M2 — dual persistence and manifest binding

- persist the immutable spec and add nullable `task_spec_id`/digest fields to
  new jobs/manifests;
- continue writing `query` and `input_payload` for old workers and rollback;
- teach Redis serialization and migration tooling to round-trip the new refs;
  and
- make mismatch detection observable before enforcing it.

### Phase M3 — canonical runtime input

- construct `ResearchState` and `SessionState` from validated task projections;
- retain compatibility adapters for resumable legacy jobs;
- enforce spec/manifest/policy intersection at admission; and
- remove duplicate implicit defaults only after all entry points use the same
  compiler.

### Legacy backfill

Historical jobs cannot be made fully reproducible after the fact. Backfill MAY
create `task-spec/v0-derived` records from stored `Job.query`, kind,
`input_payload`, timestamps, and known deployment defaults, but each record
MUST be labeled `source_kind=migration`, list unknown fields, and MUST NOT claim
the original prompt, model, source snapshot, cost authorization, or policy is
known. Existing rows and resumable checkpoints remain readable without a spec.

Backfill is additive. It must not rewrite or delete checkpoint, job, learner,
conversation, or evaluation data in place.

## 14. No-cost test plan

All tests in this section use static fixtures, mocks, recorded references, or
property-based generation. They make no network or provider call.

### Schema and invariant tests

- accept one canonical fixture for every executable task kind and both product
  lanes;
- reject unknown fields, invalid enums, overlong values, duplicate ids, broken
  references, invalid timestamps, and inconsistent freshness/source modes;
- prove JSON round-trips and canonical hashes are stable across processes;
- prove revision and supersession constraints; and
- property-test that policy intersection never broadens task permissions.

### Compiler parity tests

- research query, conversation, and HITL fixtures map deterministically;
- guided path/resource/profile/minutes fixtures map deterministically without
  copying private text;
- eval benchmark entries produce stable task ids and registry refs;
- all current entry points compile the same task for semantically equivalent
  input; and
- compiler changes intentionally update golden semantic digests.

### Privacy, security, and approval tests

- inject secrets, raw PDF prompt injection, learner prose, and principal ids;
  verify no prohibited value reaches the serialized spec;
- prove an evaluator-only overlay is absent from the runtime projection and
  trajectory fixtures;
- prove a positive spend ceiling without an external approval record fails
  admission before the first chargeable action;
- prove `chargeable_work=forbidden` selects only no-cost mock/replay routes;
- prove A0/A1 tasks cannot request external side effects; and
- prove expired or digest-mismatched context refs fail closed.

### Experiment contract tests

- generate the five-arm dry-run matrix with one identical task id/digest per
  query/repeat block;
- assert only manifest policy/config fields differ across declared contrasts;
- assert Arm C cannot be approximated by enabling the current supervisor-only
  verifier flag under the fixed graph;
- assert query refiner and reader recovery remain off in A–E;
- preserve failures, timeouts, budget stops, and null judge scores; and
- run recorded-trajectory replay to test plumbing, explicitly labeling it
  counterfactual when changed actions would alter observations.

### Migration tests

- old Redis/job payloads deserialize with a null task-spec ref;
- new payloads round-trip ids/digests without changing current fields;
- legacy derived specs expose unknown provenance rather than invent it; and
- rollback to old readers leaves jobs and checkpoints resumable.

## 15. Observability and failure behavior

Compilation and admission should expose bounded metrics and reason codes:

- compile success/failure by product surface and schema version;
- semantic validation failure code, never raw input;
- task kind and policy-intersection denials;
- missing, expired, or digest-mismatched refs;
- approval missing/expired/cap-insufficient;
- spec/manifest digest mismatch; and
- legacy job without a task spec.

Invalid input fails before job creation. A transient immutable-store failure
returns a retryable intake error. A missing approval refuses only chargeable
execution and must not be retried automatically into a paid call. A manifest
mismatch stops the episode and preserves artifacts already written. Logs use
ids and reason codes rather than objectives, profile data, or context content.

## 16. Open questions

1. Should the first public research API expose `task_kind`, or should v1 retain
   one deterministic default until Quick/Verified/Deep product contracts are
   approved under D4 and D14?
2. Which acceptance checks are safe and useful to show the research agent,
   versus existing only in an evaluator overlay?
3. What are the first approved source and tool policy ids under D5 and D6?
4. Which retention profiles and non-training uses are allowed for research
   conversations and learner data under D8?
5. Should a user clarification preserve `task_id` with a new revision or begin
   a new logical task when the requested deliverable changes substantially?
6. Should the shared fixed six-decimal USD representation remain the storage
   format, or should a later schema use integer micros?
7. Which store owns immutable task specs initially: existing job persistence,
   an artifact store, or the future registry?
8. What exact threshold and non-inferiority representation should be added
   after baseline/human calibration without leaking promotion labels?

## 17. Decision log

| Id | Decision | Status |
|---|---|---|
| D1 | Optimize claim support and evidence completeness first | Approved 2026-09-04 |
| D2 | Use separate primary, non-regression, and frontier dimensions | Approved 2026-09-04 |
| D3 | Fixed graph remains control and fallback; compare five ordered arms | Approved 2026-09-04 |
| TS-01 | Separate immutable task intent from resolved run configuration | Proposed by this RFC |
| TS-02 | Use the task-kind taxonomy in section 7.1 | Proposed; AE-000 ratification required |
| TS-03 | Keep evaluator-only overlays out of agent-visible `TaskSpec` | Proposed by this RFC |
| TS-04 | A cost ceiling is never a spend authorization | Required existing owner boundary |
| TS-05 | Prohibit training use in v1 until D8 is approved | Proposed conservative default |
| TS-06 | Reserve but reject long-horizon task execution in v1 | Proposed pending D13/D14 |

## 18. Acceptance criteria

This RFC is ready to become an ADR and bounded work orders when reviewers agree
that:

- every current research and guided-learning intake field has an explicit
  mapping or an explicit reason to remain outside `TaskSpec`;
- task kinds, minimum deliverables, primary outcomes, source/tool boundaries,
  and maximum autonomy are ratified for the initial executable set;
- hidden benchmark rubrics cannot reach agent prompts, tools, or trajectories;
- schema and semantic validators fail closed on permission, privacy, source,
  freshness, and funding inconsistencies;
- a task can be reused unchanged across all five experiment arms;
- `RunManifest`, `TrajectoryEvent`, artifact, and registry ownership boundaries
  are non-overlapping and cross-references are sufficient;
- research and guided learning share infrastructure without sharing rewards;
- legacy jobs/checkpoints remain readable and migration never invents missing
  provenance;
- every test in section 14 can run without model, network, GPU, or cloud spend;
  and
- implementation, paid evaluation, deployment, training, and promotion remain
  separately authorized actions.

## 19. Proposed implementation work-order split

No work order below is authorized by this RFC.

1. **TS-WO1 — models and canonicalization:** strict nested models, JSON Schema,
   semantic validators, canonical digest, and golden fixtures.
2. **TS-WO2 — product compilers:** deterministic research and guided-learning
   compilers plus runtime-safe projection.
3. **TS-WO3 — persistence and compatibility:** immutable store interface,
   nullable job refs, Redis round-trip, and legacy adapter.
4. **TS-WO4 — admission integration:** platform-policy intersection, context
   reference checks, manifest binding, and external cost-approval gate.
5. **TS-WO5 — eval integration:** registry overlay isolation, five-arm task
   identity checks, dry-run matrix, and artifact reporting.

Each work order should be independently reviewable, rollback-safe, and complete
its no-cost test slice before any request for funded execution.
