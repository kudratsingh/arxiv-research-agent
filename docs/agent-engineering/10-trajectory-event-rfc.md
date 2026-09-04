# Canonical trajectory-event RFC

Status: **PROPOSED — IMPLEMENTATION NOT AUTHORIZED**

Planning date: **2026-09-04**

This RFC specifies the append-only event contract needed to inspect, replay,
evaluate, and improve agent runs. It is an implementation-ready proposal, not
authority to change the runtime, collect new user data, run a live model, or
spend money. Real Anthropic calls, paid evaluations, hosted infrastructure,
training, and deployment remain separately approval-gated.

The contract supports the approved D1–D3 direction:

- optimize claim support and evidence completeness first;
- use task-rubric success and supported claims as separate primary outcomes,
  with safety, citation validity, and completion as non-regression gates;
- keep the fixed graph as the control and production fallback;
- distinguish all five arms in
  [`07-first-policy-experiment.md`](07-first-policy-experiment.md), including
  one bounded repair in Arm C and candidate lineage in Arm E.

## 1. Decision requested

Adopt one canonical `TrajectoryEvent` envelope and an append-only event store
for research and guided-learning episodes. Producers write small, typed events;
large or sensitive values live in immutable artifacts referenced by hash.
Derived views reconstruct timelines, cost, candidate lineage, claim support,
repair outcomes, and evaluation exports without mutating the source log.

This RFC intentionally does **not** approve a storage vendor, retention period,
training-data use, or production collection of additional user content. Those
choices depend on D8 and later implementation ADRs.

## 2. Why a new contract is needed

The repository already records several useful but different kinds of state:

| Existing surface | What it does well | Why it is not the canonical trajectory |
|---|---|---|
| LangGraph checkpoint | Resumes the current workflow state and supports HITL | It is mutable execution state, backend-shaped, and does not explain every transition or preserve sibling candidates |
| API/SSE events | Gives clients `job_started`, `node_completed`, pause, and terminal updates | Delivery is best-effort for intermediate frames, payloads are presentation-oriented, and Redis pub/sub is not durable history |
| Structured logs and OTel spans | Supports operations, errors, latency, and cumulative cost diagnostics | Sampling, exporter retention, and log schemas are not an episode data contract |
| `ProgressEvent` ledger | Records evidence-linked learner progress with principal scoping and append-only semantics | It describes product outcomes about a learner, not every agent action; it must not absorb prompts, tools, or hidden agent state |
| `ResearchState` | Defines the graph's current typed working state | Lists and draft fields can be replaced; it cannot identify causal transitions, retries, branches, or artifact versions |
| Eval output files | Preserve per-campaign metrics and reports | Current outputs do not guarantee one common, replayable transition format across runtime policies |

The canonical trajectory is therefore an additional source of record. It may
project selected events into SSE, logs, checkpoints, or progress events, but
those projections do not become alternate writers to trajectory history.

## 3. Goals and non-goals

### 3.1 Goals

The v1 contract must:

1. identify the task, run, policy, actor, action, and resulting observation;
2. impose one durable order on concurrent appends without claiming wall-clock
   order is causal order;
3. preserve plan, branch, candidate, verifier, and repair lineage;
4. account for tokens, estimated cost, duration, retries, and budget decisions
   as deltas that can be reconciled to a run total;
5. reference evidence, claims, reports, tool results, and checkpoints without
   copying unbounded content into the event row;
6. survive duplicate delivery, worker retries, cancellation, and resume;
7. support exact historical reconstruction and honestly labeled
   counterfactual policy replay;
8. preserve principal boundaries, consent scope, redaction status, and
   prompt-injection trust labels;
9. evolve through additive schemas and reader upcasters without rewriting
   historical events; and
10. export the same episode shape for Arms A–E and both product lanes.

### 3.2 Non-goals

V1 does not:

- store private chain-of-thought or hidden reasoning tokens;
- make arbitrary model calls deterministic;
- turn a recorded tool result into proof that a different tool action would
  have produced the same result;
- replace LangGraph checkpoints, API job rows, product progress events, logs,
  or traces;
- choose a reward function or blend the D2 scorecard into one scalar;
- authorize feedback for training or infer consent from product use;
- let an agent edit its trajectory, benchmark labels, evaluators, budgets,
  policy registry, or promotion decision; or
- allow a candidate policy to declare its own run successful.

## 4. Terms and invariants

### 4.1 Terms

- **Task**: the normalized user objective and acceptance contract identified by
  an immutable `task_spec_id` and `task_revision`, with `task_id` retained only
  as the stable logical identity across explicit task revisions.
- **Run**: one logical episode sample under one immutable `RunManifest`. A run
  keeps the same `run_id` across safe process restarts and checkpoint resumes.
  A statistical repeat or terminal rerun is a new run.
- **Process attempt**: one process lease that advances a run, including the
  initial start or one safe resume. Every process attempt has a new
  `attempt_id` and cannot reset accumulated cost or sampling identity.
- **Event**: one accepted fact about a run, stored once in committed order.
- **Action**: an intended state-changing or information-seeking operation.
- **Observation**: data returned by an action, tool, model, human, or system.
- **Artifact**: immutable content addressed outside the event row.
- **Branch**: a causally separate line of work within one run.
- **Candidate**: a versioned plan, outline, answer, report, or other selectable
  output on a branch.
- **Action attempt**: one execution try for an action, tool, model call, or
  verifier. Retries receive new `action_attempt_id` values but remain children
  of the same logical action and process `attempt_id`.
- **Projection**: a view or delivery message computed from canonical events.

### 4.2 Required invariants

1. **Append only.** No update or single-row delete API exists. Privacy erasure
   is a separately authorized principal-level operation or cryptographic
   deletion, with a non-content audit tombstone outside the user event stream.
2. **Manifest first.** A valid, immutable `RunManifest` is sealed before the
   store accepts the run's first event. The first event is `run.admitted` and
   binds its digest. The next executable lifecycle event is `attempt.started`.
   Task compilation is a pre-run receipt referenced by the manifest, not a
   trajectory event.
3. **One committed order.** Every event receives a unique positive `run_seq`
   allocated by the store. `(run_id, run_seq)` is the timeline key.
4. **Causality is explicit.** `parent_event_id` and `caused_by_event_id`, not
   timestamps or adjacent sequence numbers, represent relationships.
5. **Content is bounded.** An inline event, after canonical JSON encoding, is
   at most 32 KiB in v1. Larger content requires `ArtifactRef`.
6. **Deltas are additive.** Usage and cost fields describe the event's own
   completed work. Run totals are derived and reconciled, never copied into
   every event.
7. **No silent success.** Verifier abstention, timeout, cancellation, malformed
   output, missing artifacts, and budget stops are typed outcomes.
8. **No overwrite by revision.** Revised plans, drafts, evidence links, and
   candidates receive new artifact and candidate ids with parent links.
9. **No raw secrets or private reasoning.** Redaction occurs before append;
   secret-bearing writes are rejected rather than repaired after persistence.
10. **Training is denied by default.** A trajectory is ineligible for training
    unless an external consent and data-policy decision explicitly promotes
    it. An event cannot grant that permission itself.

## 5. Canonical envelope

### 5.1 V1 shape

Field names below are normative. JSON uses snake case, UTF-8, and RFC 3339 UTC
timestamps with a `Z` suffix. Optional fields are omitted rather than set to an
ambiguous empty string.

```json
{
  "schema_kind": "trajectory-event",
  "schema_version": "1.0.0",
  "event_type": "verification.completed",
  "event_type_version": "1.0.0",
  "event_id": "01992d7d-32f1-7ca8-a7a4-bc11c9bd8312",
  "idempotency_key": "verify:cand-report-02:faithfulness:aatt-01",
  "run_id": "run_01K4...",
  "attempt_id": "att_01K4...",
  "run_seq": 41,
  "task_spec_id": "tsp_01k4x9q7d4m2n8pv",
  "task_revision": 1,
  "task_spec_full_digest": "sha256:3f8...",
  "manifest_digest": "sha256:91a...",
  "principal_key_id": "pk_7f4...",
  "occurred_at": "2026-09-04T17:22:31.123456Z",
  "recorded_at": "2026-09-04T17:22:31.141002Z",
  "duration_ms": 8421,
  "actor": {
    "kind": "agent",
    "name": "verifier",
    "instance_id": "worker-2",
    "version_ref": "agent-verifier@sha256:2e1..."
  },
  "policy_ref": {
    "policy_id": "fixed_verify_repair",
    "policy_version": "1",
    "policy_digest": "sha256:7b2..."
  },
  "parent_event_id": "01992d7b-d03a-7f46-89bf-7a6114edb21f",
  "caused_by_event_id": "01992d79-c642-7e05-a957-811d50d46d2e",
  "trace_ref": {
    "trace_id": "e0f...",
    "span_id": "bf3..."
  },
  "branch_id": "branch_main",
  "candidate_id": "cand_report_02",
  "action_attempt_id": "aatt_verify_01",
  "status": "abstained",
  "reason_codes": ["insufficient_source_span"],
  "payload": {
    "check_kind": "claim_support",
    "subject_ref": "artifact:sha256:71c...",
    "verdict": "abstain",
    "unsupported_claim_count": 0,
    "missing_evidence_count": 1,
    "suggested_repair_kind": "retrieve_missing_evidence"
  },
  "artifact_refs": [
    {
      "artifact_id": "artifact:sha256:2a7...",
      "role": "verification_report",
      "digest": "sha256:2a7...",
      "media_type": "application/json",
      "byte_length": 1824,
      "schema_ref": "verification-report/1",
      "storage_uri": "cas://sha256/2a7...",
      "trust_class": "system_generated",
      "data_class": "internal",
      "retention_policy_ref": "evaluation-artifact-policy/pending"
    }
  ],
  "usage_delta": {
    "provider": "anthropic",
    "model_id": "resolved-by-run-manifest",
    "input_tokens": 940,
    "output_tokens": 182,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "llm_calls": 1,
    "retries": 0,
    "estimated_cost_usd": "0.005550",
    "price_table_ref": "anthropic-prices/2026-09-04"
  },
  "data_governance": {
    "content_class": "derived_summary",
    "effective_data_class": "internal",
    "consent_scope": "product_operation_only",
    "redaction_status": "passed",
    "contains_user_content": false,
    "training_eligible": false
  },
  "replay": {
    "origin": "live",
    "source_run_id": null,
    "observation_status": "observed"
  },
  "prev_event_hash": "sha256:8ba...",
  "event_hash": "sha256:f55..."
}
```

### 5.2 Envelope field rules

| Field | Required | Rule |
|---|---:|---|
| `schema_kind` | yes | Contract family, exactly `trajectory-event` |
| `schema_version` | yes | Semantic envelope version; readers reject unknown major versions |
| `event_type` | yes | Registered lower-case dotted name from section 8 |
| `event_type_version` | yes | Semantic payload schema version for that event type |
| `event_id` | yes | Globally unique opaque id; UUIDv7 is proposed, but ordering never depends on it |
| `idempotency_key` | yes | Stable for one producer intent and retry, unique within a run; maximum 256 bytes |
| `run_id` | yes | One logical episode sample; foreign key to the immutable `RunManifest` and stable across safe resumes |
| `attempt_id` | conditional | Process attempt advancing the run; required after admission, including resume validation events for the proposed next attempt |
| `run_seq` | store | Positive, gap-tolerant, unique sequence allocated only on accepted append |
| `task_spec_id` | yes | Immutable compiled task revision bound by the run manifest; never inferred only from logical `task_id` |
| `task_revision` | yes | Positive revision matching the sealed `TaskSpec` and run manifest |
| `task_spec_full_digest` | yes | Algorithm-prefixed full digest of the bound `TaskSpec` |
| `manifest_digest` | yes | Algorithm-prefixed digest of the sealed control-plane `RunManifest` |
| `principal_key_id` | conditional | Required for product/user runs; synthetic evals use a declared non-human synthetic principal |
| `occurred_at` | yes | Producer-observed time; diagnostic only, never the canonical order |
| `recorded_at` | store | Store commit time in UTC |
| `duration_ms` | conditional | Non-negative elapsed duration for completed/timed-out work; absent on instantaneous facts |
| `actor` | yes | Typed producer identity; not an authorization credential |
| `policy_ref` | yes | Policy id/version/digest; must match the sealed run manifest without copying its full configuration |
| `parent_event_id` | conditional | Structural parent within the same run and with a lower committed `run_seq` |
| `caused_by_event_id` | conditional | Earlier event whose result triggered this event; may differ from structural parent |
| `trace_ref` | no | Correlation only; OTel is not the source of record |
| `branch_id` | yes | `branch_main` for unbranched runs; immutable once assigned |
| `candidate_id` | conditional | Required for events that produce, verify, repair, score, or select a candidate |
| `action_attempt_id` | conditional | Required for an executable action/tool/model/verifier try; distinct from process `attempt_id` |
| `status` | yes | One of section 5.4's values, further restricted per event type |
| `reason_codes` | yes | Bounded registered codes; use `[]` when no reason applies |
| `payload` | yes | Event-specific schema; object only, bounded and redacted |
| `artifact_refs` | yes | Zero or more immutable references; never inline artifact bodies |
| `usage_delta` | conditional | Required for any provider/model/tool work that consumed billable or metered resources |
| `data_governance` | yes | Orthogonal content class plus effective sensitivity; required even for synthetic data; training eligibility defaults false |
| `replay` | yes | Distinguishes observed, replayed, held-constant, simulated, and counterfactual records |
| `prev_event_hash` | store | Hash of the previous committed event in this run; null only at `run_seq=1` |
| `event_hash` | store | Tamper-evident hash described in section 12 |

### 5.3 Shared contract encoding

`TrajectoryEvent`, `TaskSpec`, `RunManifest`, registry references, receipts,
and artifacts use the shared `agent-contract-json/v1` profile:

- UTF-8 JSON with strict schemas and unknown keys rejected at write boundaries;
- RFC 8785 JSON Canonicalization Scheme for content hashing;
- RFC 3339 UTC timestamps with a `Z` suffix and microsecond precision;
- algorithm-prefixed lowercase digests such as `sha256:<64 hex characters>` at
  every reference site—bare digest strings are invalid;
- fixed-decimal money strings with six fractional digits and explicit ISO 4217
  currency; and
- immutable typed references shaped as `kind`, `id`, semantic `revision`, and
  `digest` rather than an untyped string whose meaning must be inferred.

An event may carry only policy-visible or operationally safe registry
references. Full manifest, benchmark case, split, label, hidden rubric, grader,
approval, and evaluator objects remain in the control plane. Their existence
may be proven by an opaque receipt ref and digest when the event type permits
it, but their contents are never copied into trajectory payloads or artifacts.

### 5.4 Shared enums

`status` is one of:

```text
requested | started | succeeded | failed | abstained | skipped |
interrupted | timed_out | cancelled | budget_stopped | rejected
```

Not every status is legal for every type. For example,
`verification.completed` accepts `succeeded`, `failed`, or `abstained`, while
`run.completed` accepts only `succeeded`.

`actor.kind` is one of:

```text
system | policy | agent | tool | model | human
```

`data_governance.content_class` is one of:

```text
none | metadata | user_input_summary | source_summary | derived_summary |
artifact_reference | synthetic
```

Content class describes what an event row contains; it is not a sensitivity
decision. `data_governance.effective_data_class` and every artifact's
`data_class` use the shared `DataClass` vocabulary:

```text
public | internal | user_confidential | learner_sensitive
```

The effective event class is the most restrictive class inherited from the
bound `TaskSpec`, referenced artifacts, and allowed inline payload. A metadata
event can therefore have `content_class=metadata` and
`effective_data_class=learner_sensitive`. No producer may downgrade it.

`replay.origin` is one of:

```text
live | fixture | observational_replay | decision_replay | simulation
```

`replay.observation_status` is one of:

```text
observed | recorded | held_constant_after_divergence | simulated |
not_applicable
```

### 5.5 Usage and money

Money follows `agent-contract-json/v1`: a fixed-decimal string with six
fractional digits plus explicit currency, never a binary float. `usage_delta`
may also carry provider-specific meters in a bounded `meter_deltas` object, but
the standard token fields remain stable.

Rules:

- one completed provider request records usage once, even when its enclosing
  action later fails;
- each provider retry has a distinct `action_attempt_id` and usage delta while
  preserving the process `attempt_id`;
- cache-read and cache-creation tokens remain separate because they have
  different prices;
- a price-table reference is required for non-zero estimated cost;
- runtime verifier/selector cost is labeled with `cost_scope: product`;
  post-run evaluator/judge cost belongs to a control-plane evaluation receipt,
  not the policy trajectory, and scorecards report both scopes separately;
- budget reservations are not cost and must not be added to spend;
- a final `budget.reconciled` event compares summed deltas with the existing
  `RunCosts` snapshot and fails closed on an unexplained difference above the
  approved rounding tolerance; and
- neither this RFC nor experiment-design approval authorizes paid usage.

## 6. Identity, order, causality, and lineage

### 6.1 Store-assigned order

The append API accepts an event without `run_seq`, `recorded_at`,
`prev_event_hash`, or `event_hash`. `attempt_id` is producer-supplied because
it identifies the current process lease, not an event-store sequence. In one
database transaction the store:

1. verifies the immutable run manifest, `task_spec_id`/revision/digest,
   `manifest_digest`, current attempt lease, and principal scope;
2. checks idempotency;
3. locks the run's cursor row;
4. assigns `run_seq = last_seq + 1`;
5. resolves `prev_event_hash` from the cursor;
6. validates parent and lineage references;
7. computes `event_hash` over canonical JSON;
8. inserts the row and advances the cursor; and
9. commits before acknowledging the append.

Sequences may contain gaps after operational repair or partition migration;
consumers require strict increase, not contiguity. Clock skew and UUID order do
not affect reconstruction.

`run.admitted` is always `run_seq=1`. Initial execution then appends
`attempt.started`; a safe resume appends an approval/admission revalidation
receipt when required and a new `attempt.started` with a new `attempt_id`.
Neither path creates a new logical sample.

Concurrent branches can finish in either committed order. That order states
only what the ledger accepted first. `parent_event_id`, `caused_by_event_id`,
`branch_id`, `candidate_id`, and `attempt_id` express semantic relationships.

### 6.2 Parent and cause

- `parent_event_id` builds the episode tree: a tool attempt is a child of its
  requested action; a verification is a child of the candidate it checks.
- `caused_by_event_id` answers why a later event occurred: an abstention may
  cause a repair request even when both belong under the same candidate.
- Both references must target an event already committed in the same run.
- An event may have no causal reference only when its event-type schema allows
  it, such as the first run lifecycle event.
- Cross-run causality uses `source_run_id` plus an artifact or benchmark
  reference in the payload, never `parent_event_id`.

### 6.3 Branches

`branch.created` allocates a unique `branch_id` and names its parent branch and
fork event. The main branch is declared by the initial `attempt.started`. A branch closes with
`branch.completed`, `branch.failed`, or `branch.cancelled`; closure does not
delete its artifacts.

Arms A–D use `branch_main` unless existing supervisor execution genuinely
forks work. Arm E's T2 tier must emit a separate branch for every diverse plan
or outline so parallel candidates are not flattened into one message list.

### 6.4 Candidate lineage

Every selectable or revisable output has a `candidate_id`. Candidate lineage
is a directed acyclic graph governed by:

- `candidate.created` has zero or more input artifact refs and no candidate
  parent for a root candidate;
- `candidate.revised` has exactly one `parent_candidate_id`, a new
  `candidate_id`, and a typed change scope;
- candidate parents must exist in the same run and cannot reference their
  descendants;
- sibling candidates never share an id even if their bytes are identical;
- identical bytes may share a content-addressed artifact while retaining
  distinct candidate identities;
- `candidate.selected` lists all eligible candidate ids, selection method,
  policy reason codes, and the chosen id;
- listwise model selection links its request, observation, usage, and score
  artifact; and
- rejection or non-selection never deletes a candidate.

Arm C therefore records the original draft and repaired draft as parent and
child candidates. Arm E records tier, branches, siblings, selector outcome,
and marginal-stop decision. This is the minimum data needed to measure repair
regressions, selector oracle gap, and whether additional compute helped.

## 7. Artifact contract

### 7.1 `ArtifactRef`

Each reference includes:

```text
artifact_id, role, digest, media_type, byte_length, schema_ref,
storage_uri, trust_class, data_class, retention_policy_ref
```

Optional fields are `encryption_key_ref`, `compression`, `created_by_event_id`,
and `source_artifact_ids`.

Normative rules:

1. `artifact_id` is `artifact:sha256:<lowercase hex>` for byte-identical global
   deduplication unless a privacy domain requires a scoped keyed digest.
2. The digest is computed over the stored plaintext canonical bytes before
   transport compression. Encryption happens after hashing inside the
   authorized privacy domain.
3. The store verifies hash and byte length on write and read.
4. `storage_uri` is a logical `cas://` URI, not a temporary signed URL or local
   absolute path.
5. Artifact access enforces the run's principal/data domain independently of
   possession of the hash.
6. Event payloads may include a bounded excerpt only when its event schema and
   data policy explicitly allow it; source text, prompts, PDFs, transcripts,
   model responses, reports, and code outputs use artifacts by default.
7. `source_artifact_ids` records derivation. It does not replace event-level
   cause or evidence edges.
8. Garbage collection follows retention policy only after proving no retained
   event or derived dataset references the artifact.

### 7.2 Required artifact roles

V1 registers at least:

```text
plan | tool_input | tool_output | source_document | source_span |
evidence_record | claim_set | candidate_outline |
candidate_report | verification_report | repair_patch | checkpoint_snapshot |
human_input | final_report | failure_detail | runtime_score_record |
admission_receipt | approval_revalidation_receipt
```

Schemas should prefer small, independent artifacts. A claim-support link should
reference a source-span artifact rather than a complete PDF.

The full `TaskSpec`, `RunManifest`, benchmark case, evaluator overlay, approval
record, split assignment, label set, and grader configuration are control-plane
objects, not trajectory artifacts. Only an allowlisted receipt/projection may
cross the boundary, and it must not reveal hidden membership or evaluation
content.

## 8. Event taxonomy

Event types are registered centrally with owners, legal statuses, payload
schema, maximum size, allowed artifact roles, and data classifications.
Unregistered strings are rejected.

### 8.1 Run and policy lifecycle

| Event type | Required payload | Purpose |
|---|---|---|
| `run.admitted` | `admission_receipt_ref`, `admission_receipt_digest`, `environment_class`, `product_lane` | First event after the manifest is sealed; binds an accepted control-plane admission without copying it |
| `approval.revalidated` | `proposed_attempt_id`, `receipt_ref`, `receipt_digest`, `result`, `reason_codes` | Trusted admission-controller fact required before a chargeable resume; contains no approver, scope, cap, conversation, or credential detail |
| `attempt.started` | `entrypoint`, `main_branch_id`, `effective_budget_ref`, `resume_checkpoint_id` | A new process lease began advancing the same logical run |
| `attempt.completed` | `attempt_id`, `last_committed_event_id` | Process attempt ended after advancing the run; not necessarily a terminal run |
| `attempt.interrupted` | `attempt_id`, `interruption_class`, `last_checkpoint_id`, `side_effect_reconciliation_required` | Process stopped without declaring the logical run failed |
| `attempt.failed` | `attempt_id`, `failure_class`, `last_checkpoint_id`, `safe_resume_possible` | Process attempt failed; orchestrator still decides whether the run can resume |
| `policy.decision` | `decision_kind`, `eligible_actions`, `chosen_action`, `reason_codes`, `feature_snapshot_ref` | Records routing without private reasoning |
| `run.completed` | `final_candidate_id`, `final_artifact_id`, `stop_reason_code` | Successful terminal fact |
| `run.failed` | `failure_class`, `failure_stage`, `last_good_artifact_id` | Terminal fact after the orchestrator declares no safe resume |
| `run.cancel_requested` | `requested_by_kind`, `reason_code` | Cooperative cancellation was requested |
| `run.cancelled` | `acknowledged_at_stage`, `last_good_artifact_id`, `in_flight_action_attempt_ids` | Cancellation terminal fact |
| `run.budget_stopped` | `budget_id`, `last_good_artifact_id`, `partial_candidate_id`, `stop_reason_code` | Budget-stop terminal fact without relabeling it as an ordinary failure |

Exactly one of `run.completed`, `run.failed`, `run.cancelled`, or
`run.budget_stopped` is accepted. A process crash with no terminal run event is
an interrupted/unknown attempt, not an implicit run failure or success.
`budget.exhausted` precedes `run.budget_stopped`; if the sealed policy declares
a valid partial deliverable, `run.completed` may instead name that explicitly
partial final.

Task compilation emits no trajectory event. Its sealed compilation receipt is
validated and referenced by the control-plane `RunManifest` before
`run.admitted`. Admission or approval revalidation records only an opaque,
algorithm-prefixed receipt reference/digest and the bounded result fact.

### 8.2 Planning and actions

| Event type | Required payload | Purpose |
|---|---|---|
| `plan.created` | `plan_artifact_id`, `objective_count`, `action_count`, `plan_kind` | Creates an inspectable bounded plan |
| `plan.revised` | `plan_artifact_id`, `parent_plan_artifact_id`, `change_scope`, `reason_codes` | Preserves re-plan lineage |
| `plan.approved` | `plan_artifact_id`, `approval_source`, `constraints_changed` | Policy or human approval fact |
| `action.requested` | `action_id`, `action_kind`, `bounded_input_summary`, `allowed_tool_ids` | Declares intended action before side effects |
| `action.started` | `action_id`, `executor_kind` | Attempt began |
| `action.completed` | `action_id`, `observation_event_ids`, `output_artifact_ids` | Action settled successfully |
| `action.failed` | `action_id`, `error_class`, `retryable`, `attempt_number` | Typed failed attempt |
| `action.skipped` | `action_id`, `reason_code` | Eligible action deliberately not run |
| `observation.recorded` | `observation_kind`, `source_kind`, `completeness`, `freshness_at` | Bounded observation plus artifact refs |

`bounded_input_summary` contains structured parameters or a redacted summary,
not a full prompt. Model prompts and outputs, when retention permits them at
all, are access-controlled artifacts.

### 8.3 Tools and external sources

| Event type | Required payload | Purpose |
|---|---|---|
| `tool.requested` | `tool_call_id`, `tool_id`, `tool_version`, `argument_schema_ref`, `side_effect_class`, `network_scope` | Pre-execution tool contract |
| `tool.started` | `tool_call_id`, `sandbox_ref` | Tool execution began |
| `tool.completed` | `tool_call_id`, `result_kind`, `result_count`, `exit_status`, `cache_status` | Settled tool result |
| `tool.failed` | `tool_call_id`, `error_class`, `retryable`, `provider_status_class` | Failure without leaking raw errors/secrets |
| `source.discovered` | `source_id`, `source_kind`, `canonical_locator_hash`, `published_at`, `accessed_at` | Retrieval provenance |
| `source.accepted` | `source_id`, `admissibility_codes`, `quality_signals` | Source passed policy |
| `source.rejected` | `source_id`, `rejection_codes` | Source excluded without disappearing |

Untrusted source text is always an observation with
`trust_class=untrusted_source`. It never appears in `policy.decision` control
fields, tool identifiers, system prompts, or executable arguments without an
explicit isolation and validation step.

The source **snapshot** and the observation **capture** are different records:

- the sealed manifest pins source mode, source-policy ref/digest, and—when
  applicable—a registry-owned snapshot ref/digest defining the permitted input
  universe before the run;
- trajectory `tool.completed`, `source.discovered`, and
  `observation.recorded` events identify only the result bytes actually
  returned to the policy for its chosen action;
- a snapshot does not imply every contained source was observed, while a
  captured live result does not turn the changing live source into a frozen
  snapshot; and
- only candidate-visible source refs may enter the trajectory. A hidden case,
  split, label, canary, or evaluator-only corpus identifier remains solely in
  the control plane.

Typed safe references use the shared `kind`/`id`/`revision`/`digest` shape. At
minimum the manifest must bind source-policy and snapshot
registry refs; an observation must bind the selected tool-call ref and captured
artifact digest.

### 8.4 Evidence and claims

| Event type | Required payload | Purpose |
|---|---|---|
| `evidence.extracted` | `evidence_id`, `source_id`, `source_span_artifact_id`, `extraction_method`, `supports_task_item_ids` | Immutable evidence node |
| `claim.created` | `claim_id`, `claim_artifact_id`, `candidate_id`, `claim_kind`, `report_location_ref` | Identifies one checkable claim |
| `claim.evidence_linked` | `claim_id`, `evidence_id`, `relationship`, `link_method` | Support/contradiction/qualification edge |
| `claim.evidence_unlinked` | `claim_id`, `prior_evidence_id`, `reason_code`, `replacement_link_event_id` | Corrects a bad link append-only |
| `evidence.coverage_assessed` | `task_item_ids`, `covered_item_ids`, `missing_item_ids`, `coverage_method` | D1 completeness input |

`relationship` is `supports`, `contradicts`, `qualifies`, or `background`.
An unlink event invalidates a prior edge in derived views; it does not erase
the historical assertion. Claim text and source spans remain artifacts so the
row stays bounded and privacy rules remain centralized.

### 8.5 Verification and repair

| Event type | Required payload | Purpose |
|---|---|---|
| `verification.requested` | `check_id`, `check_kind`, `subject_ref`, `verifier_ref`, `acceptance_rule_ref` | Freezes what will be checked |
| `verification.completed` | `check_id`, `verdict`, `confidence`, `failure_codes`, `suggested_repair_kind` | Pass/fail/abstain result |
| `verification.malformed` | `check_id`, `error_class`, `fallback_action` | Judge output could not be trusted |
| `repair.requested` | `repair_id`, `repair_kind`, `subject_candidate_id`, `target_refs`, `repair_budget_ref` | Names one bounded repair |
| `repair.completed` | `repair_id`, `result_candidate_id`, `changed_scope`, `verification_required` | New child candidate; never overwrite |
| `repair.failed` | `repair_id`, `error_class`, `candidate_unchanged` | Failed recovery fact |
| `repair.exhausted` | `subject_candidate_id`, `attempted_repair_ids`, `stop_reason_code` | Repair policy limit reached |

`verification.completed.verdict` is exactly `pass`, `fail`, or `abstain`,
independent of envelope `status`. A verifier with insufficient evidence must
abstain. `verification.malformed` cannot be projected as a pass.

Arm C must prove from events that:

1. verification followed synthesis;
2. at most one `repair.requested` was accepted for the original candidate;
3. the repair kind was one of the five approved bounded operations;
4. unrelated report sections were not regenerated when the repair claimed a
   section-scoped change; and
5. the child candidate was re-verified before final selection.

### 8.6 Candidate and compute control

| Event type | Required payload | Purpose |
|---|---|---|
| `compute.tier_selected` | `tier`, `eligible_tiers`, `feature_snapshot_ref`, `tier_budget_ref`, `reason_codes` | T0–T2 routing for Arm E |
| `branch.created` | `new_branch_id`, `parent_branch_id`, `fork_event_id`, `diversity_dimension` | Starts explicit parallel work |
| `branch.completed` | `branch_id`, `candidate_ids`, `stop_reason_code` | Settles a branch |
| `branch.failed` | `branch_id`, `failure_class`, `last_good_candidate_id` | Preserves failed branch |
| `branch.cancelled` | `branch_id`, `reason_code` | Settles cancelled branch |
| `candidate.created` | `candidate_id`, `candidate_kind`, `artifact_id`, `generation_method` | Root candidate identity |
| `candidate.revised` | `candidate_id`, `parent_candidate_id`, `artifact_id`, `change_scope` | Revision lineage |
| `candidate.scored` | `candidate_id`, `score_artifact_id`, `runtime_scorer_ref`, `score_scope` | Policy-visible runtime selection score, never a hidden benchmark grade |
| `candidate.selected` | `eligible_candidate_ids`, `selected_candidate_id`, `selector_kind`, `selection_artifact_id` | Listwise/deterministic choice |
| `compute.stop_decided` | `considered_action`, `expected_gain_method`, `marginal_gain`, `incremental_cost_estimate`, `reason_code` | Why extra compute stopped |

T3 is reserved and rejected by the first experiment's validator. A static
policy may emit `compute.tier_selected` only if its manifest declares that
event as diagnostic; it must not be mislabeled as adaptive routing.

Post-run task-rubric grades, hidden-label comparisons, judge prompts, human
adjudications, and promotion scores are control-plane evaluation records. They
may reference final trajectory artifacts by digest, but are never appended as
policy-visible `candidate.scored` events or exposed through replay.

### 8.7 Budget and accounting

| Event type | Required payload | Purpose |
|---|---|---|
| `budget.established` | `budget_id`, `currency`, `episode_cap`, `campaign_cap_ref`, `limit_dimensions` | Effective immutable envelope |
| `budget.reserved` | `reservation_id`, `action_id`, `maximum_cost`, `expires_at` | Concurrency-safe pre-call reservation |
| `budget.reservation_released` | `reservation_id`, `actual_cost`, `release_reason` | Returns unused capacity |
| `budget.usage_recorded` | `reservation_id`, `usage_event_ids`, `cost_delta` | Links usage to reservation |
| `budget.threshold_reached` | `threshold`, `spent`, `reserved`, `remaining` | Warning or policy transition |
| `budget.exhausted` | `spent`, `reserved`, `attempt_blocked`, `partial_candidate_id` | Hard-stop fact before another call |
| `budget.reconciled` | `summed_event_cost`, `run_cost_snapshot`, `difference`, `result` | Terminal accounting check |

Reservations are required before concurrent provider calls so five workers
cannot each pass a stale remaining-budget check. The budget authority lives
outside the candidate policy. A candidate may request compute, but cannot
raise the cap, change the price table, suppress usage, or emit its own accepted
budget event.

### 8.8 Checkpoint, HITL, final, and terminal failures

| Event type | Required payload | Purpose |
|---|---|---|
| `checkpoint.saved` | `checkpoint_id`, `checkpoint_artifact_id`, `graph_position`, `resumable`, `state_schema_ref` | Links mutable execution to immutable snapshot evidence |
| `checkpoint.resumed` | `checkpoint_id`, `resume_reason`, `resuming_worker_id` | Resume fact |
| `checkpoint.invalid` | `checkpoint_id`, `failure_codes`, `fallback` | Refused or degraded resume |
| `hitl.requested` | `request_id`, `request_kind`, `subject_ref`, `allowed_responses`, `deadline_at` | Durable human pause request |
| `hitl.responded` | `request_id`, `response_kind`, `response_artifact_id`, `responder_principal_ref` | Human response, separately scoped artifact |
| `hitl.timed_out` | `request_id`, `timeout_policy` | Typed timeout |
| `hitl.cancelled` | `request_id`, `reason_code` | Pause no longer awaits a response |
| `final.candidate_selected` | `candidate_id`, `selection_basis`, `verification_event_ids`, `unresolved_issue_codes` | Finalization decision |
| `final.artifact_produced` | `candidate_id`, `artifact_id`, `deliverable_kind`, `partial` | Deliverable exists before terminal run event |
| `failure.recorded` | `failure_id`, `failure_class`, `stage`, `retryable`, `safe_message` | Non-terminal or terminal diagnostic |

`hitl.responded` records the decision after authentication and principal-scope
checks; raw human prose is an encrypted artifact only if the approved retention
policy permits it. The existing `plan_ready` and `turn_ready` SSE frames are
projections of `hitl.requested`, not canonical writes from the client stream.

## 9. Payload schemas and examples

Each type owns a JSON Schema under a future registry path such as
`schemas/trajectory/v1/events/<event-type>.schema.json`. The registry rejects
unknown keys by default. Additive metadata belongs in a namespaced `extensions`
object whose total size still counts against the envelope bound.

### 9.1 Tool attempt

```json
{"schema_kind":"trajectory-event","schema_version":"1.0.0",
 "event_type":"tool.completed","event_type_version":"1.0.0",
 "event_id":"01992d95-64ef-7517-a717-474d1d3e1f97",
 "idempotency_key":"tool:search:action-07:attempt-02:completed",
 "run_id":"run_01K4...","attempt_id":"att_01K4...",
 "task_spec_id":"tsp_01k4x9q7d4m2n8pv","task_revision":1,
 "task_spec_full_digest":"sha256:3f8...","manifest_digest":"sha256:91a...",
 "principal_key_id":"synthetic:research-policy-v1",
 "occurred_at":"2026-09-04T17:25:10.000000Z",
 "actor":{"kind":"tool","name":"arxiv_search","instance_id":"worker-1",
          "version_ref":"arxiv-search@sha256:ab2..."},
 "policy_ref":{"policy_id":"fixed","policy_version":"1",
               "policy_digest":"sha256:7b2..."},
 "parent_event_id":"01992d94-c981-79c7-b447-a6b07ae8525d",
 "caused_by_event_id":"01992d94-c981-79c7-b447-a6b07ae8525d",
 "branch_id":"branch_main","action_attempt_id":"aatt_tool_02",
 "duration_ms":733,"status":"succeeded","reason_codes":[],
 "payload":{"tool_call_id":"toolcall_07","result_kind":"paper_metadata",
            "result_count":5,"exit_status":"success","cache_status":"miss"},
 "artifact_refs":[{"artifact_id":"artifact:sha256:6ed...","role":"tool_output",
   "digest":"sha256:6ed...","media_type":"application/json","byte_length":9012,
   "schema_ref":"arxiv-search-result/1","storage_uri":"cas://sha256/6ed...",
   "trust_class":"untrusted_source","data_class":"public",
   "retention_policy_ref":"evaluation-artifact-policy/pending"}],
 "data_governance":{"content_class":"artifact_reference",
   "effective_data_class":"public",
   "consent_scope":"public_source_evaluation","redaction_status":"passed",
   "contains_user_content":false,"training_eligible":false},
 "replay":{"origin":"live","source_run_id":null,
   "observation_status":"observed"}}
```

Store-assigned fields are omitted from producer examples.

### 9.2 Targeted repair

```json
{"schema_kind":"trajectory-event","schema_version":"1.0.0",
 "event_type":"repair.requested","event_type_version":"1.0.0",
 "event_id":"01992da1-949d-78ef-89b9-969650819196",
 "idempotency_key":"repair:cand-report-01:missing-rubric-3:once",
 "run_id":"run_01K4...","attempt_id":"att_01K4...",
 "task_spec_id":"tsp_01k4x9q7d4m2n8pv","task_revision":1,
 "task_spec_full_digest":"sha256:3f8...","manifest_digest":"sha256:91a...",
 "principal_key_id":"synthetic:research-policy-v1",
 "occurred_at":"2026-09-04T17:31:00.000000Z",
 "actor":{"kind":"policy","name":"fixed_verify_repair",
   "instance_id":"policy-runtime","version_ref":"policy@1"},
 "policy_ref":{"policy_id":"fixed_verify_repair","policy_version":"1",
   "policy_digest":"sha256:7b2..."},
 "parent_event_id":"01992d7d-32f1-7ca8-a7a4-bc11c9bd8312",
 "caused_by_event_id":"01992d7d-32f1-7ca8-a7a4-bc11c9bd8312",
 "branch_id":"branch_main","candidate_id":"cand_report_01",
 "status":"requested","reason_codes":["verification_abstained"],
 "payload":{"repair_id":"repair_01",
   "repair_kind":"retrieve_missing_evidence",
   "subject_candidate_id":"cand_report_01",
   "target_refs":["rubric-item:3"],"repair_budget_ref":"budget:repair-01"},
 "artifact_refs":[],
 "data_governance":{"content_class":"metadata",
   "effective_data_class":"internal",
   "consent_scope":"evaluation_only","redaction_status":"passed",
   "contains_user_content":false,"training_eligible":false},
 "replay":{"origin":"live","source_run_id":null,
   "observation_status":"not_applicable"}}
```

### 9.3 Cancellation after in-flight work

```json
{
  "event_type": "run.cancelled",
  "status": "cancelled",
  "payload": {
    "acknowledged_at_stage": "reader",
    "last_good_artifact_id": "artifact:sha256:774...",
    "in_flight_action_attempt_ids": ["aatt_reader_paper_4"],
    "cost_reconciliation_pending": true
  },
  "reason_codes": ["user_requested"]
}
```

The abbreviated example inherits all required envelope fields. A later provider
response from the in-flight attempt may append usage with
`reason_codes=["settled_after_cancel"]`; it cannot change the terminal run
outcome. The store accepts these declared settlement event types after terminal
state while rejecting new policy actions.

## 10. Privacy, redaction, and injection isolation

### 10.1 Data minimization

The default event contains ids, enums, counts, digests, and bounded summaries.
It excludes:

- API keys, cookies, authorization headers, connection strings, signed URLs,
  environment dumps, and raw exception locals;
- raw user requests, learner messages, PDF bodies, source chunks, prompts,
  model outputs, reports, code, and tool stdout/stderr;
- private chain-of-thought, scratchpads, hidden reasoning tokens, or requests
  to reconstruct them; and
- direct identifiers when a stable scoped `principal_key_id` suffices.

Permitted artifacts are encrypted and access-controlled according to their
data domain. Redaction runs before hashing and append. A detected secret causes
`redaction_status=rejected` on a safe `failure.recorded` event; the rejected
body is never persisted for debugging.

### 10.2 Principal and tenant scope

- Product events require the authenticated principal key already used by
  principal-scoped stores.
- Evaluation fixtures use explicit `synthetic:*` principals and cannot be
  joined to product users.
- Authorization checks run on both event queries and artifact reads.
- Global content hashes do not grant cross-principal access.
- Cross-principal analytics operate only on an approved de-identified export,
  never through an unrestricted trajectory query.

### 10.3 Consent and training

`consent_scope` describes the externally determined scope; a producer cannot
elevate it. V1 supports:

```text
product_operation_only | support_only | aggregate_analytics |
human_evaluation | evaluation_only | public_source_evaluation |
synthetic_test
```

A future training scope is intentionally absent until D8 is approved. Every v1
event has `training_eligible=false`. Dataset promotion, if later authorized,
creates a separately versioned dataset record containing inclusion reasons,
consent evidence, redaction version, and source event ids.

### 10.4 Prompt-injection boundary

Every artifact and observation carries a `trust_class`:

```text
system_generated | authenticated_human | untrusted_user |
untrusted_source | tool_generated | evaluator_generated
```

Untrusted text is data, never instruction. A policy decision may cite an
untrusted observation id as evidence, but its executable fields must be built
from registered enums and validated parameters. Tests inject instruction-like
canaries into papers, metadata, user text, and tool errors and prove they do not
appear in tool ids, policy choices, system-control payloads, logs, or unrelated
artifacts.

## 11. Idempotency and concurrency

### 11.1 Append API

Conceptual interface:

```text
append_event(run_scope, proposed_event) -> StoredTrajectoryEvent
append_batch(run_scope, proposed_events) -> list[StoredTrajectoryEvent]
```

`run_scope` is authenticated context, not a caller-supplied payload. A batch is
atomic and ordered as given. It may only contain events for one run.

The database enforces:

- unique `event_id` globally;
- unique `(run_id, idempotency_key)`;
- unique `(run_id, run_seq)`;
- foreign keys to run manifest and event-type registry;
- same-run, earlier-sequence parent/cause/candidate references through the
  append procedure; and
- first-terminal-wins plus a narrow allowlist of post-terminal settlement and
  audit event types.

### 11.2 Retry behavior

On a repeated `(run_id, idempotency_key)`:

- if the producer semantic digest matches, return the stored event unchanged;
- if it differs, reject with `IdempotencyConflict` and record a safe operational
  metric outside the run; and
- never overwrite the stored payload or append a second logical fact.

The semantic digest excludes store-assigned fields and normalizes JSON through
RFC 8785 JSON Canonicalization Scheme. It includes artifact digests, so a retry
cannot silently point the same action at new bytes.

### 11.3 Multi-worker races

The run cursor transaction serializes appends only long enough to allocate
sequence and hash. Slow artifact uploads happen first to a staging namespace;
the event transaction promotes their references only after every digest is
verified. Orphaned staging objects are garbage-collected safely.

Budget reservation uses a separate atomic compare-and-reserve transaction.
Action execution may begin only after the corresponding reservation event is
committed. Cancellation sets a durable flag checked before reservation and at
cooperative cancellation points; a race that already crossed the provider
boundary must still record its final usage.

## 12. Integrity

### 12.1 Hash chain

For event `n`:

```text
event_hash[n] = SHA-256(
  UTF8("trajectory-event-v1\n") ||
  previous_event_hash_bytes ||
  RFC8785(canonical_event_without_prev_event_hash_or_event_hash)
)
```

`previous_event_hash_bytes` is empty for the first event. The stored
`prev_event_hash` is null on that row and must equal the prior row's
`event_hash` everywhere else. The transaction computes both hash fields;
producers cannot submit them. Artifacts have independent hashes.

This detects accidental mutation or deletion when a trusted head hash is kept
separately. It is tamper-evident, not tamper-proof against an attacker who can
rewrite both database and trust anchor. A production ADR must choose signing or
external anchoring if that threat matters.

### 12.2 Validation and quarantine

Reads verify schema, event hash, chain continuity, artifact digest, manifest
digest, and principal scope. Corrupt rows are never silently skipped. A run is
marked unavailable in derived views, the affected partition is quarantined,
and operators receive ids and safe metadata—not user content—for repair.

## 13. Replay and counterfactual limits

The word “replay” is reserved for three distinct operations.

### 13.1 Observational replay

Fold the exact stored events and artifacts to reconstruct historical state and
derived views. No agent, model, network, or tool runs. This can reproduce what
the system observed and decided, subject to artifact retention and schema
upcasters.

### 13.2 Decision replay

Run a candidate policy against observations recorded from a source run. It may
compare routing, stopping, or deterministic validation decisions without a
provider call. The replay manifest records `source_run_id`, candidate policy,
and the first divergence.

Before divergence, inherited observations use `observation_status=recorded`.
After a candidate chooses a different action, any reused historical observation
is labeled `held_constant_after_divergence`; simulated outputs are `simulated`.
All downstream outcome claims are counterfactual. They cannot be scored as if
the different action actually retrieved, generated, or verified those bytes.

### 13.3 Live rerun

A new execution against tools or models is a new run with a new manifest and
current timestamps. It may cite the source run as an experimental pair, but is
not called a replay. Live reruns and any associated spend require the applicable
approval.

### 13.4 What replay cannot establish

Replay cannot prove:

- freshness or availability of live retrieval;
- what an unchosen query, tool, prompt, or model would have returned;
- latency or cost under a different provider/runtime state;
- correctness of a new candidate report built from held-constant results;
- human responses to a changed plan; or
- quality gains after the first unsupported counterfactual observation.

Counterfactual exports therefore include `diverged_at_event_id`,
`counterfactual_depth`, and the percentage of observations that were observed,
held constant, or simulated.

## 14. Storage, retention, and query views

### 14.1 Logical storage

The recommended first implementation is Postgres for envelopes and a
content-addressed artifact adapter with a local-filesystem test backend. This
matches the current durable-store direction while keeping object storage behind
an interface.

Conceptual tables:

```text
trajectory_runs(
  run_id PK, task_spec_id, task_revision, task_spec_full_digest,
  manifest_digest, principal_key_id,
  retention_policy_ref, last_seq, head_event_hash, terminal_event_id
)

trajectory_events(
  recorded_date, event_id PK, run_id, run_seq, event_type,
  event_type_version, occurred_at, recorded_at, parent_event_id,
  caused_by_event_id, branch_id, candidate_id, attempt_id, action_attempt_id,
  idempotency_key, payload_jsonb, envelope_jsonb,
  prev_event_hash, event_hash
)

trajectory_artifact_refs(
  run_id, event_id, artifact_id, role, data_class,
  retention_policy_ref
)
```

`trajectory_events` may be time-partitioned by `recorded_date`, but the logical
API orders by `(run_id, run_seq)`. Required indexes cover:

- `(run_id, run_seq)`;
- `(run_id, event_type, run_seq)`;
- `(task_spec_id, event_type)` through the run join;
- `(run_id, candidate_id, run_seq)`;
- `(run_id, branch_id, run_seq)`;
- `(principal_key_id, recorded_at)` through the run join; and
- artifact reverse references.

No general JSONB index is created initially; add narrow expression indexes only
for measured query needs.

### 14.2 Retention

Every run and artifact has a required `retention_policy_ref`, resolved by an
external data-policy registry. Until D8 is approved:

- synthetic Stage 0 fixtures may use `synthetic_test` policy;
- existing operational data remains governed by its current contracts;
- the new store must not begin production capture of raw user or learner
  content;
- no event is training-eligible; and
- implementation tests use synthetic, redacted fixtures only.

Retention expiry may remove artifact bytes when policy permits, but retained
events continue to expose the digest, media type, expiry reason, and an
`artifact_unavailable` status in views. Principal erasure must remove or
cryptographically erase every scoped artifact and event according to the later
approved policy; append-only means normal application behavior, not an excuse
to violate deletion obligations.

### 14.3 Required views

| View | Grain | Used for |
|---|---|---|
| `trajectory_run_timeline_v1` | one event | Ordered debugging and audit, with safe payload projection |
| `trajectory_action_outcomes_v1` | one logical action | Success, retry, latency, redundant-action, and tool-yield metrics |
| `trajectory_candidate_lineage_v1` | one candidate edge | Branches, revisions, selection, oracle-gap analysis |
| `trajectory_claim_support_v1` | one claim/evidence edge | Supported-claim precision, abstention, contradiction, and coverage |
| `trajectory_repair_outcomes_v1` | one repair | Repair success, scope, re-verification, and induced regression |
| `trajectory_budget_ledger_v1` | one run/model/tool | Tokens, calls, cost, reservations, cap adherence, reconciliation |
| `trajectory_hitl_latency_v1` | one request | Wait, response, timeout, cancellation, and principal scope |
| `trajectory_episode_export_v1` | one run | Eval-ready task/manifest/trajectory/artifact/score references |
| `trajectory_integrity_v1` | one run | Hash-chain, manifest, terminal, artifact, and schema health |

Views are rebuildable from events and versioned. A changed definition creates a
new view version rather than silently changing historical experiment results.

## 15. Schema evolution and migration

### 15.1 Compatibility rules

- `schema_version` changes only for an incompatible envelope change.
- `event_type_version` changes when that type's payload contract changes.
- Additive optional fields may remain in the same type version only when old
  readers ignore them safely and meaning is unchanged.
- Required fields, enum reinterpretation, unit changes, and field removal
  require a new event-type version.
- Event names are never reused with new meaning.
- Readers validate against the recorded version, then apply pure upcasters to a
  requested read model.
- Upcasters never invent observed facts. A missing new field becomes `unknown`
  or a typed default whose derivation is recorded.
- Raw rows are immutable. Backfills write derived projections or explicit
  `migration.annotation` events; they do not rewrite history.

### 15.2 Registry record

Each event-type version records:

```text
event_type, event_type_version, json_schema_digest, owner,
introduced_in_code_commit, compatible_reader_range,
allowed_statuses, allowed_artifact_roles, allowed_data_classes,
upcaster_ref, retired_at
```

CI checks that producer code, schemas, fixtures, docs, and view builders agree
on the registry digest.

### 15.3 Importing existing records

Existing SSE frames, logs, checkpoints, eval files, and learner progress events
must not be retroactively labeled canonical. If historical import is useful,
an importer creates a new synthetic migration run whose events have:

```text
replay.origin = fixture
replay.observation_status = recorded
reason_codes = [historical_import, incomplete_source_surface]
```

Missing causality, usage, or artifacts remain unknown. The importer records
source file digests and an import report; it does not fabricate parents or
claim an exact trajectory.

## 16. Projection into current runtime surfaces

The canonical event is written before an externally visible projection when a
durable fact is required. Projection failures do not alter history.

| Canonical event | Current projection |
|---|---|
| `run.started` | `job_started` SSE plus structured log |
| `action.completed` for graph node | `node_completed` SSE with existing safe state delta |
| `hitl.requested` for plan review | `plan_ready` SSE and `pending_review` job status |
| `hitl.requested` for learner turn | `turn_ready` SSE and `awaiting_learner` job status |
| `run.completed` | `job_completed` SSE, terminal job row, metrics |
| `run.failed` | `job_failed` SSE, terminal job row, metrics |
| `run.cancelled` | `job_cancelled` SSE, terminal job row, metrics |
| selected learning outcome | separately validated `ProgressEvent`; no bulk trajectory copy |

The SSE payload remains a stable client contract and may deliberately expose
less detail. A dropped intermediate SSE frame is not a lost trajectory event.
The OTel span id is copied into `trace_ref` when available; spans may be sampled
without affecting the ledger.

Checkpoint payloads are not automatically duplicated. `checkpoint.saved`
references an encrypted snapshot only at declared recovery boundaries; ordinary
LangGraph internal writes can remain solely in the checkpointer if per-step
snapshot retention would add no evaluation value.

## 17. Five-arm experiment requirements

The Stage 0 validator reconstructs each episode and enforces:

| Arm | Required trajectory proof | Forbidden/mislabel check |
|---|---|---|
| A `fixed` | fixed policy ref, main branch, fixed action order, terminal reconciliation | no evidence-path, verifier, adaptive-tier, query-refiner, or reader-recovery events |
| B `fixed_evidence` | typed evidence and claim links consumed by synthesis | no active verifier/repair or adaptive decision |
| C `fixed_verify_repair` | verification, optional one bounded repair, child candidate, re-verification | existing supervisor-only verifier flag cannot masquerade as C; no second repair |
| D `supervisor_verified` | every dynamic route has `policy.decision`; evidence and verifier enabled | query refinement and reader recovery remain absent in experiment v1 |
| E `adaptive_verified` | T0–T2 selection; T2 branch/candidate lineage; selection and marginal stop | no T3; static always-more-compute behavior cannot be labeled adaptive |

Common checks prove prompt isolation is on, Semantic Scholar and prompt caching
are off, HITL is off, the exact manifest/config digest matches the declared arm,
and failed/timed-out/budget-stopped episodes remain in denominators.

The output path in the experiment protocol keeps `trajectory.jsonl` as a
portable export. Export order is `run_seq`; every line is the complete stored
envelope plus artifact metadata, not artifact content. The campaign manifest
records the event-registry and export-schema digests.

## 18. No-cost test plan

All tests below use synthetic fixtures, mocked providers, local stores, and
zero network calls.

### 18.1 Schema and serialization

- accept one golden event for every registered event type and legal status;
- reject missing ids, unknown types, future envelope versions, unknown fields,
  invalid timestamps, negative durations, floating-point money, oversized
  payloads, and disallowed artifact roles;
- canonicalize JSON deterministically across key order and process restart;
- round-trip every event without loss through Postgres and JSONL export; and
- snapshot registry digests so unreviewed schema drift fails CI.

### 18.2 Ordering, idempotency, and integrity

- append 1,000 events concurrently from multiple tasks and prove unique,
  strictly increasing per-run sequences;
- retry every append and prove one stored event and the original returned id;
- reuse an idempotency key with different bytes and require
  `IdempotencyConflict`;
- reject cross-run, future, missing, and cyclic parent/candidate references;
- alter/delete/reorder one fixture event and prove hash-chain validation fails;
- race two terminal outcomes and prove first-terminal-wins; and
- allow only declared cost-settlement events after cancellation.

### 18.3 Artifacts and data safety

- reject artifact hash/length mismatches and temporary/signed storage URLs;
- prove identical public bytes deduplicate while authorization remains scoped;
- inject secrets in every string field and prove rejection occurs before
  persistence and logs contain no secret;
- inject prompt-control canaries in user/source/tool content and prove no canary
  enters policy-control or executable-tool fields;
- prove chain-of-thought-shaped fields are absent/rejected;
- prove synthetic principals cannot query product principals; and
- prove every v1 event exports `training_eligible=false`.

### 18.4 Accounting and lifecycle

- reconcile standard, cached, retried, failed, timed-out, and late-after-cancel
  provider attempts against `RunCosts` fixtures;
- reserve budget concurrently and prove total spent plus outstanding reserved
  never exceeds the cap;
- prove `budget.exhausted` blocks the next mocked model/tool action;
- test checkpoint save/resume/invalid paths without duplicating actions;
- test HITL request, response, timeout, cancellation, and cross-worker retry;
- project terminal events to the current exact SSE names; and
- prove projection failure leaves the canonical event queryable.

### 18.5 Replay and views

- fold a golden episode to the same final candidate, claim-support view, repair
  view, and budget totals;
- replay a policy with no divergence and label observations `recorded`;
- force a decision divergence and prove all later reused observations are
  `held_constant_after_divergence` and excluded from factual outcome claims;
- prove historical imports retain `unknown` rather than invented fields; and
- rebuild all versioned views from a JSONL fixture in a clean database.

### 18.6 Experiment-arm conformance

- generate a dry-run A–E matrix with exact conceptual policy refs;
- require Arm C's one-repair cap and re-verification;
- require Arm E branch/candidate/selector/marginal-stop lineage;
- reject query-refiner, reader-recovery, T3, HITL, prompt-cache, and Semantic
  Scholar events in the first experiment;
- retain failures and null scores in episode exports; and
- run the entire suite with a guard that fails on any attempted network or
  provider call.

## 19. Acceptance criteria

The RFC is ready to become bounded work orders when all of the following are
true:

1. The `TaskSpec`, `RunManifest`, and benchmark/data-registry RFCs accept the
   cross-contract assumptions in section 21.
2. D8 establishes retention, deletion, consent, artifact-encryption, and human
   evaluation rules before production/user-content capture.
3. An ADR selects the event id format, store/adapters, transaction strategy,
   hash anchor, and exact schema-registry location.
4. Every event type has a machine-readable schema, owner, golden fixture, and
   legal-state table.
5. Append, batch, query, export, and integrity-check interfaces pass the
   no-cost tests in section 18.
6. Current SSE, tracing, checkpoints, progress events, and `RunCosts` remain
   backward compatible and have explicit projections or reconciliation tests.
7. A dry-run A–E campaign emits mechanically distinguishable, valid episodes
   with zero provider/network calls.
8. Arm C cannot append a second repair, and Arm E cannot use T3 or lose sibling
   candidate lineage.
9. Verifier `abstain`, malformed output, partial final, timeout, cancellation,
   and budget exhaustion remain visible in exports and denominators.
10. Raw prompts, documents, reports, learner text, secrets, and private
    reasoning do not appear in event rows or safe logs.
11. An operational failure to project SSE/log/trace output cannot erase or
    mutate an accepted event.
12. No paid or deployed validation begins without the user's explicit later
    approval and a written cost ceiling.

## 20. Proposed implementation slices

These are planning slices, not authorized work orders.

1. **Schema package:** envelope, event registry, artifact refs, canonical JSON,
   validators, golden synthetic fixtures.
2. **In-memory adapter:** idempotency, ordering, lineage, fold/replay, and unit
   tests without infrastructure.
3. **Postgres adapter:** append procedure, cursor, constraints, hash chain,
   partitions, scoped queries, retention hooks, concurrency tests.
4. **Artifact adapter:** local content-addressed test store, hash validation,
   staging/promote flow, access-control interface.
5. **Runtime bridge:** action/tool/checkpoint/budget lifecycle hooks plus SSE,
   OTel, and `RunCosts` reconciliation.
6. **Research semantics:** evidence, claim, verifier, repair, candidate, and
   Arm A–E conformance views.
7. **Eval export:** JSONL/artifact manifest, counterfactual labels, view rebuild,
   and dry-run campaign matrix.
8. **Production-policy gate:** D8/ADR decisions, deletion exercise, threat
   review, capacity test, and only then an explicit collection decision.

Each slice should be independently reviewable and keep all runtime behavior
behind a default-off typed capability until its no-cost gates pass.

## 21. Cross-RFC assumptions

### 21.1 `TaskSpec`

This RFC assumes `TaskSpec` owns:

- immutable `task_spec_id`, integer task revision, stable logical `task_id`,
  task kind/product lane, objective, deliverables,
  acceptance/rubric item ids, source/freshness constraints, allowed tools,
  denied actions, autonomy tier, human checkpoints, and task budget intent;
- a canonical schema version and digest; and
- the redacted task summary that may appear in safe views.

Trajectory events reference task/rubric ids. They do not duplicate the raw user
request or reinterpret task constraints.

### 21.2 `RunManifest`

This RFC assumes `RunManifest` owns:

- immutable `run_id`, `task_spec_id`/revision/full digest, code commit,
  environment class, policy id and
  version, policy-specific config, prompt versions, exact model routes, tool
  versions, seed/sampling settings, task-set version, budget, and config digest;
- experiment arm and repeat identity; and
- replay/source-run declaration when applicable.

It must be sealed before `run.admitted` and have one canonical digest. Events repeat
only the small `policy_ref` and manifest digest needed to detect cross-run
contamination. Effective changes require a new run, except explicitly modeled
HITL decisions and budget reservations inside the original immutable envelope.

### 21.3 Benchmark/data registry

This RFC assumes the registry owns:

- benchmark id/version, task membership, split visibility, task-slice labels,
  corpus/snapshot digests, rubric and judge versions, evaluator access policy,
  consent/provenance, retention policy, and sealed-set controls;
- dataset inclusion/exclusion and retraction records; and
- the rule that a candidate policy cannot read labels, change graders, promote
  its own trajectory, or declare training eligibility.

Trajectory exports point to registry versions and record observations; they do
not become the authoritative dataset merely by being stored.

### 21.4 Shared naming assumptions

The companion RFCs should reserve these exact identities or explicitly map
them in the implementation ADR:

```text
task_spec_id, task_revision, task_id, run_id, attempt_id,
action_attempt_id, policy_id, policy_version, manifest_digest,
task_set_ref, experiment_arm, repeat_index, principal_key_id,
retention_policy_ref, artifact_id, candidate_id, branch_id
```

## 22. Open decisions

1. **Event id:** adopt UUIDv7, ULID, or another opaque 128-bit format? The
   answer must not change `(run_id, run_seq)` as canonical order.
2. **Storage:** use the existing Postgres deployment first, or start with JSONL
   plus an importer? This RFC recommends Postgres plus portable JSONL export.
3. **Artifact privacy digest:** where user-controlled content exists, should
   deduplication use a per-principal keyed digest rather than a global SHA-256
   id to reduce cross-domain correlation?
4. **Retention and erasure (D8):** what durations and deletion guarantees apply
   to product, learner, support, evaluation, and artifact data?
5. **Artifact encryption:** which key hierarchy and crypto-erasure mechanism
   backs `encryption_key_ref`?
6. **Hash trust anchor:** is an internal periodically signed run head enough,
   or does the threat model require an external immutable anchor?
7. **Late events:** which accounting/audit event types may append after a run
   terminal event, and for how long?
8. **Checkpoint granularity:** which recovery boundaries justify immutable
   checkpoint artifacts versus references to the existing checkpointer only?
9. **Human content:** may raw HITL text be retained, for how long, and under
   which human-evaluation consent?
10. **Progress-event bridge:** which trajectory outcomes may produce learner
    `ProgressEvent` records, and which independent validation must happen first?
11. **Reason-code registry:** which module owns cross-policy codes and their
    compatibility lifecycle?
12. **Production capture:** should v1 launch for evaluation-only synthetic runs
    before any user-facing runtime writes? This RFC recommends yes.

Until these decisions are accepted, the safe next step is schema/fixture work
and synthetic no-cost validation only. The current fixed pipeline remains the
control and production fallback.
