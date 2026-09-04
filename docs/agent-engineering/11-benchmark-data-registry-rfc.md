# RFC: benchmark and evaluation-data registry

Status: **PROPOSED — PLANNING ONLY**

Date: **2026-09-04**

Roadmap items: **AE-003**, with interfaces to AE-000, AE-001, AE-002,
AE-004, and AE-005

Related documents:

- [`02-target-architecture.md`](02-target-architecture.md)
- [`03-evaluation-strategy.md`](03-evaluation-strategy.md)
- [`04-roadmap.md`](04-roadmap.md)
- [`07-first-policy-experiment.md`](07-first-policy-experiment.md)
- [`08-task-spec-rfc.md`](08-task-spec-rfc.md)
- [`09-run-manifest-rfc.md`](09-run-manifest-rfc.md)
- [`10-trajectory-event-rfc.md`](10-trajectory-event-rfc.md)

This RFC defines a registry contract. It does not authorize implementation,
human-labeling spend, live model evaluation, provider calls, dataset download,
or hosted infrastructure.

## 1. Decision summary

Create an in-repository registry that resolves every evaluation input by an
immutable revision and content digest. Keep these objects separate:

1. task cases and their candidate-visible inputs;
2. rubrics and grader configuration;
3. source or tool-result snapshots;
4. reference labels and human adjudications;
5. split assignments and their visibility policy;
6. contamination canaries and exposure records;
7. licenses, consent, retention, and permitted-use metadata.

A benchmark suite is a versioned manifest that references those objects; it is
not one large file that grants every consumer access to all content. A
control-plane `RunManifest` records the exact suite revision, selected cases,
and resolved digests. Its separately hashed policy-runtime projection excludes
sealed case identity, split membership, labels, graders, approval details, and
private locators. One `TaskSpec` is compiled from each selected task-case
revision and reused for every arm and repeat. A `TrajectoryEvent` may reference
permitted registry objects but may never copy hidden labels into the
policy-visible trajectory.

The repository's current 20-query research benchmark will enter the registry
as `research-policy-v1`, object revision `1.0.0`, with a `development` split only. Its
checked-in topics and notes are visible to developers, so this revision cannot
serve as a sealed promotion test. The existing guided-reading scenarios and
recorded fixtures will be registered separately and keep their own task and
metric lane.

## 2. Problem

The current evaluation assets are useful but distributed across Python
constants, fixture manifests, recorded events, runner conventions, ADRs, and
documentation:

- `src/eval/benchmark_queries.py` owns the research query inputs and expected
  topics;
- `src/eval/learning_benchmark.py` owns guided-reading personas, papers,
  scripts, and structural expectations;
- `tests/fixtures/learning/manifest.json` indexes recorded learning fixtures;
- `src/eval/runner.py` and `src/eval/simulate_learner.py` define campaign and
  persistence behavior;
- judge prompts and deterministic metrics live in evaluator code;
- output directories identify runs, but do not yet bind every input to an
  immutable data revision.

That is sufficient for regression testing but not for a defensible agent
improvement loop. Today it is difficult to answer mechanically:

- which exact task, rubric, label set, source snapshot, and grader version
  produced a score;
- whether a candidate could see its expected answer or sealed split;
- whether a task changed in place between two campaigns;
- whether a source snapshot was legal to store and still valid to use;
- whether a benchmark is for development, promotion, calibration, or an
  external capability probe;
- whether an apparent win reflects task leakage, label drift, source drift,
  stochastic variance, or a policy improvement.

## 3. Goals and non-goals

### Goals

- Resolve every campaign input to immutable bytes with a content digest.
- Separate policy-visible inputs from evaluator-only and owner-only data.
- Make development, validation, and sealed/canary use enforceable rather than
  conventional.
- Support research episodes, guided-learning episodes, and future
  long-horizon projects without blending their outcome metrics.
- Preserve source, label, license, consent, provenance, and contamination
  history.
- Make task selection, exclusions, repeats, failures, and null scores visible
  in the campaign record.
- Support local, no-provider-call validation and replay.
- Allow external benchmark adapters without importing unlicensed or secret
  test data into the repository.

### Non-goals

- A general-purpose feature store, model registry, experiment tracker, or data
  warehouse.
- Storing provider credentials, private access tokens, or approval secrets.
- Treating an LLM judge output as ground truth.
- Automatically promoting a policy from registry results.
- Defining user-feedback training consent; D8 remains open and must be settled
  before product feedback becomes training data.
- Making sealed inputs available to a candidate for convenience.
- Replacing the current evaluation runners in the first implementation step.

## 4. Core concepts

The registry uses small immutable objects joined by references.

| Object | Purpose | Typical visibility |
|---|---|---|
| `BenchmarkSuite` | Declares a product/evaluation objective and pins compatible revisions | Developer-visible metadata |
| `TaskSet` | Ordered task cases and their candidate-visible inputs | Split-dependent |
| `TaskCase` | One evaluation unit from which a `TaskSpec` is compiled | Split-dependent |
| `RubricSet` | Rubric dimensions, item ids, scoring rules, and abstention policy | Visible, evaluator-only, or mixed |
| `LabelSet` | Reference claims, citations, preferences, expected outcomes, and adjudications | Evaluator-only by default |
| `SourceSnapshot` | Frozen documents, metadata, tool responses, or content-addressed references | Candidate-visible when the task permits |
| `FixtureSet` | Recorded tool or session observations for replay and deterministic tests | Developer-visible unless sensitive |
| `SplitAssignment` | Case membership and access policy for development, validation, or sealed use | Membership may be restricted |
| `GraderProfile` | Deterministic and model-judge configuration references | Evaluator-only configuration |
| `ContaminationRecord` | Known exposure, canary matches, publication state, and audit history | Evaluator/owner-only |
| `ExternalAdapter` | License-aware mapping to a benchmark held outside this repository | Metadata visible; payload may remain external |

Each object has a logical id, immutable semantic revision, schema version,
content digest, lifecycle status, owners, and access classification. A changed
byte creates a changed digest. A material semantic change creates a new object
revision.

## 5. Identity and immutability

### 5.1 Reference form

Use a typed reference rather than a path string:

```yaml
kind: task_set
id: research-policy-tasks
revision: 1.0.0
digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

Normative rules:

- `kind` is a controlled vocabulary.
- `id` is a stable lowercase kebab-case logical name.
- `revision` is an immutable semantic version within the logical object id.
- `digest` hashes canonical serialized content, including ordered child
  references where order is meaningful.
- all P0 contract objects use `agent-contract-json/v1`: RFC 8785 canonical JSON
  with application-level six-decimal money and RFC 3339 UTC timestamp strings.
- mutable aliases such as `latest` may exist for humans but are forbidden in a
  funded or promotion `RunManifest`.
- paths are locators, not identity. Moving an object without changing its
  canonical bytes does not change the reference.
- every manifest validates the declared digest before execution.

### 5.2 Revision rules

| Change | Required action |
|---|---|
| Whitespace or comment outside canonical content | Digest may remain unchanged |
| Clarification that cannot change scoring or task behavior | Patch revision |
| Add/remove a task, rubric item, label, or fixture | Minor revision |
| Change task meaning, score semantics, split policy, or compatibility | Major revision |
| Correct a bad label after adjudication | New label-set revision; never overwrite history |
| Reassign a case between visibility splits | New split-assignment revision and audit event |
| Change only evaluator code | New grader-profile revision, not a task-set revision |

Historical revisions remain resolvable while their retention and license
policy permits. A revoked revision remains identifiable but cannot start a new
campaign.

## 6. Proposed suite schema

The implementation may use Pydantic plus canonical JSON/YAML, but the semantic
contract is format-independent. `schema_kind`, `schema_version`, `payload`,
and `integrity` form the common envelope. All suite-specific fields below
`schema_version` live inside `payload`; `integrity` carries the algorithm,
digest profile, and payload digest.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `schema_kind` | string | yes | `benchmark-suite` |
| `schema_version` | string | yes | Envelope schema version, initially `1.0.0` |
| `suite_id` | string | yes | Stable logical suite name |
| `revision` | semver | yes | Immutable object revision within `suite_id` |
| `title` | string | yes | Human-readable name |
| `description` | string | yes | Capability and intended use |
| `task_kinds` | list[enum] | yes | Allowed case kinds from the `TaskSpec` vocabulary |
| `evaluation_lane` | enum | yes | `research`, `guided_learning`, or future `long_horizon` |
| `intended_uses` | list[enum] | yes | `development`, `regression`, `calibration`, `promotion`, or `capability_probe` |
| `prohibited_uses` | list[string] | yes | Explicitly disallowed decisions or training uses |
| `owners` | list[string] | yes | Maintainer and adjudication owners; no secrets |
| `status` | enum | yes | `draft`, `reviewed`, `active`, `deprecated`, or `revoked` |
| `task_set` | object ref | yes | Ordered cases and candidate-visible input refs |
| `rubric_set` | object ref | yes | Rubric items and score semantics |
| `label_sets` | list[object ref] | no | Expert/reference labels, independently versioned |
| `source_snapshots` | list[object ref] | no | Frozen corpora or tool observations |
| `fixture_sets` | list[object ref] | no | Replay material |
| `split_assignment` | object ref | yes | Membership and access rules |
| `grader_profiles` | list[object ref] | yes | Permitted deterministic/model evaluators |
| `license_policy` | object | yes | Licenses, redistribution, attribution, expiry |
| `data_policy` | object | yes | Classification, consent, retention, deletion |
| `contamination` | object | yes | Exposure state, canaries, audit references |
| `compatibility` | object | yes | Supported schema/runtime ranges |
| `provenance` | object | yes | Creator, timestamps, parent revision, review record |

### Example: current research benchmark registration

The repeated digest characters below are syntactically valid placeholders
until implementation computes real values. Integrity is outside the hashed
payload to avoid a circular self-digest.

```yaml
schema_kind: benchmark-suite
schema_version: 1.0.0
payload:
  suite_id: research-policy-v1
  revision: 1.0.0
  title: Research policy comparison, development suite
  description: >-
    Current checked-in twenty-query research benchmark, registered for paired
    policy development and regression analysis.
  task_kinds:
    - research.focused_evidence_review
    - research.literature_survey
    - research.method_comparison
    - research.contradiction_analysis
  evaluation_lane: research
  intended_uses: [development, regression]
  prohibited_uses: [sealed promotion evidence, training-target export]
  owners: [maintainer]
  status: active
  task_set:
    kind: task_set
    id: research-policy-tasks
    revision: 1.0.0
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  rubric_set:
    kind: rubric_set
    id: research-policy-rubric
    revision: 1.0.0
    digest: sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  label_sets:
    - kind: label_set
      id: research-policy-expected-topics
      revision: 1.0.0
      digest: sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  source_snapshots: []
  fixture_sets: []
  split_assignment:
    kind: split_assignment
    id: research-policy-splits
    revision: 1.0.0
    digest: sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
  grader_profiles:
    - kind: grader_profile
      id: current-research-metrics
      revision: 1.0.0
      digest: sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
  license_policy:
    registry_metadata: project_license
    task_text: maintainer_authored
    redistribution: permitted
  data_policy:
    registry_object_classification: internal
    effective_data_sensitivity: public
    contains_personal_data: false
    training_use: prohibited
    retention_policy_ref:
      kind: retention_policy
      id: repository-history
      revision: 1.0.0
      digest: sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
  contamination:
    exposure: public_repository
    canary_set: null
    last_reviewed_at: 2026-09-04T00:00:00Z
  compatibility:
    task_spec_schema_kind: task-spec
    task_spec_schema_version: 1.0.0
    runner: research
  provenance:
    created_at: 2026-09-04T00:00:00Z
    created_by: maintainer
    parent: null
    review_record: pending-implementation-adr
integrity:
  algorithm: sha256
  digest_profile: agent-contract-json/v1
  payload_digest: sha256:9999999999999999999999999999999999999999999999999999999999999999
```

## 7. Task cases and `TaskSpec` compilation

A task case is registry data, not runtime state. It contains enough immutable
input to compile one runtime `TaskSpec`, plus references to evaluator-only
material that the compiler must not expose to the policy.

```yaml
schema_kind: task-case
schema_version: 1.0.0
case_id: hallucination-mitigation
revision: 1.0.0
task_input:
  objective: What are the latest approaches to reducing hallucination in large language models?
  task_kind: research.focused_evidence_review
  constraints:
    source_policy_ref:
      kind: source_policy
      id: scholarly-default
      revision: 1.0.0
      digest: sha256:1111111111111111111111111111111111111111111111111111111111111111
  deliverable_ref:
    kind: deliverable_contract
    id: supported-research-report
    revision: 1.0.0
    digest: sha256:2222222222222222222222222222222222222222222222222222222222222222
candidate_visible_refs: []
evaluator_refs:
  rubric_items: [coverage.required-topics, claims.supported, citations.valid]
  label_case_id: hallucination-mitigation
slice_tags: [survey, freshness, retrieval, hallucination]
```

The compiler:

1. receives only a permitted case reference from the campaign planner;
2. resolves and verifies candidate-visible objects;
3. produces a control-plane `TaskSpec` origin containing typed suite, task-set,
   and task-case refs; the agent-safe projection may omit that origin when case
   identity is restricted;
4. keeps `evaluator_refs`, split metadata that reveals hidden membership, and
   labels outside the agent process;
5. emits a content-addressed pre-run compilation receipt; the `RunManifest`
   references that receipt before sealing.

Compilation happens once per selected task-case revision for a campaign. The
same TaskSpec id, task revision, full digest, and semantic digest are reused
across all arms and statistical repeats. Repeat identity belongs to the
`RunManifest`, not to `TaskSpec` compilation.

Rubric visibility is per item. User-visible deliverable criteria may be placed
in the `TaskSpec`; hidden reference answers, expected papers, adjudicated
claims, judge prompts, and canary tokens remain evaluator-only.
`TaskSpec` does not carry a generic evaluation-profile string: rubric, grader,
label, split, and calibration refs remain registry/manifest responsibilities.

## 8. Splits and access control

### 8.1 Split semantics

| Split | Who can see inputs | Who can see labels | Permitted use |
|---|---|---|---|
| `development` | Developers and candidate policy | Evaluator; developers where acceptable | Iteration, debugging, exploratory comparisons |
| `validation` | Evaluation operator or broker; candidate gets one case at execution | Evaluator/authorized reviewers | Predeclared selection and bounded promotion studies |
| `sealed` | Broker only; candidate gets minimum runtime input | Independent evaluator/owner | Rare confirmatory promotion decision |
| `canary` | Owner/evaluator only | Owner/evaluator only | Leakage and contamination detection |

Validation and sealed are access policies, not directory names. Simply placing
plain-text tasks in a private folder on the same agent-readable filesystem is
not sealed evaluation.

### 8.2 Enforcement

- The policy runtime receives a capability-scoped task payload, never a
  registry root or arbitrary object path.
- The evaluator runs under a different role and reads labels only after the
  final artifact is immutable.
- A candidate may not choose cases, exclude failures, modify graders, or alter
  split membership.
- Promotion campaigns predeclare suite revision, split, case-count rule,
  repeats, exclusion policy, primary metrics, and stopping rule.
- Every access to validation, sealed, label, or canary material produces an
  audit record that is outside candidate authority.
- Local development must use synthetic or development data, not copied sealed
  payloads.

The first implementation may support development data only, provided it fails
closed on validation/sealed declarations until a real broker boundary exists.

## 9. Rubrics, labels, and graders

### 9.1 Rubric set

Each rubric item has:

- stable `rubric_item_id` and revision;
- description and task applicability;
- scoring type and valid range;
- required evidence type;
- pass/fail/partial/abstain semantics;
- deterministic or human adjudication precedence;
- candidate visibility;
- metric aggregation rule and denominator policy.

Candidate-visible `TaskSpec` acceptance checks may carry a typed
`rubric_item_ref` to public contractual items. Hidden reference answers,
promotion margins, and evaluator-only rubric items are referenced only by the
control plane and evaluator. A local `check_id` and registry `rubric_item_id`
are different identifiers and must not be conflated.

The approved first experiment uses task-rubric success and supported-claim
precision as separate primary outcomes. Safety, citation validity, completion,
and denominator integrity are gates. Cost, latency, and human preference remain
separate frontier dimensions; the registry must not encode a hidden weighted
overall score.

### 9.2 Label set

Labels record `label_id`, target object, label type, value, evidence,
annotator/adjudicator pseudonymous ids, timestamps, guideline revision,
agreement state, confidence where meaningful, and supersession lineage.
Disagreement is retained; adjudication creates a new record rather than
deleting the original labels.

Model-judge outputs are run results, not reference labels. They may be promoted
into a weak-label dataset only under a separately approved data process and
must remain distinguishable from human or deterministic ground truth.

### 9.3 Grader profile

A grader profile pins:

- deterministic metric implementation/version;
- model judge provider/model route by public identifier, with the exact model
  resolved in the `RunManifest` immediately before an approved live run;
- judge prompt and rubric references;
- decoding parameters and retry/timeout policy;
- input redaction and ordering/blinding rules;
- abstention, failure, null-score, and denominator handling;
- calibration-set revision and known error rates by slice.

The profile contains no API key and grants no spend authority. Selecting a
model grader in a manifest is invalid without a separate recorded cost
approval applicable to that campaign.

The shared effective data-sensitivity vocabulary is `public`, `internal`,
`user_confidential`, and `learner_sensitive`. Registry-object classification
is a separate field describing access to registry metadata. The effective
artifact handling policy is the most restrictive result of TaskSpec,
registry, and platform policies; it is never weakened by a less restrictive
label on one object.

## 10. Source snapshots and fixtures

A controlled comparison should freeze observations when practical.

`SourceSnapshot` records:

- source identity, version, publication and access timestamps;
- retrieval query/tool request and normalized response;
- content digest and object-store locator;
- license, redistribution, retention, and deletion terms;
- parser/chunker version when derived text is stored;
- missing, retracted, corrected, or access-denied state;
- relationships between raw, normalized, chunked, and evidence-span objects.

Large content is content-addressed and referenced; it is not embedded in the
suite manifest. A snapshot may contain metadata-only references when storing
full text is not licensed. Expiry or deletion makes future execution fail
closed or explicitly run in a documented degraded mode; it never silently
substitutes current live content under the old digest.

`FixtureSet` is for deterministic replay. It records observation ordering,
tool contract version, sanitization, and whether a changed policy would have
requested an unrecorded observation. Any score produced after the replay path
diverges is labeled counterfactual and cannot substitute for a live end-to-end
result.

## 11. Contamination and benchmark exposure

Every suite revision declares one of:

- `private_unexposed`;
- `limited_access`;
- `public_repository`;
- `published_external`;
- `exposure_unknown`.

The registry also records known use in prompts, training exports, examples,
documentation, debugging transcripts, and publications. Canary material is
stored separately from tasks and labels. A canary match triggers review; it is
evidence of possible exposure, not automatic proof of training contamination.

Rules:

- development results never become sealed evidence by renaming the split;
- a publicly exposed task may remain valuable for regression but loses its
  generalization claim;
- generated benchmark expansions record the generator and source inputs and
  require human review before activation;
- a policy or self-improvement candidate cannot generate the sealed tasks on
  which it is promoted;
- benchmark failures and negative results do not authorize editing a label to
  favor the candidate.

## 12. Lifecycle and governance

```text
draft -> reviewed -> active -> deprecated -> revoked
```

- `draft`: schema-valid, not usable for promotion.
- `reviewed`: content, license, privacy, and leakage review complete; may still
  await activation.
- `active`: allowed for its declared intended uses.
- `deprecated`: existing manifests remain reproducible; new campaigns require
  an explicit override and reason.
- `revoked`: new execution forbidden because of corruption, rights, privacy,
  leakage, or material validity failure.

Activation requires named owners, an invariant report, documented allowed and
prohibited uses, resolved object digests, and a review record. Promotion-capable
suites additionally require split-control review and evaluator independence.
No agent candidate can activate, revoke, or reassign its own benchmark.

## 13. Campaign resolution and result boundary

The campaign planner resolves registry references before any episode begins:

```text
suite ref + split + selection rule + repeats
  -> authorized case ids
  -> verified immutable object refs
  -> one TaskSpec per selected case revision
  -> one RunManifest per arm/repeat episode plus campaign manifest
  -> append-only trajectories and immutable artifacts
  -> evaluator-only labels and graders
  -> results referencing, never mutating, the registry revision
```

The registry owns evaluation inputs. It does not own trajectories, outputs,
scores, confidence intervals, or decisions. Those belong to the campaign
artifact store and refer back to registry objects by immutable reference.

A campaign manifest must record:

- suite and every resolved child digest;
- split and authorized selection rule;
- ordered case ids and explicit exclusions;
- repeat identity and seed policy;
- grader profile and calibration references;
- source-snapshot/live-source mode;
- access broker and approval-record ids;
- registry validation receipt ref/digest covering lifecycle, rights, expiry,
  retention, availability, and split authorization at seal time;
- expected denominators and failure/null-score treatment.

The full campaign and run manifests are control-plane records. A separately
hashed policy-runtime projection contains only the task and execution material
the candidate is authorized to see. Evaluator configuration and restricted
registry refs live in an evaluator-only projection. Both projection digests
are pinned by the full manifest so omission and substitution are detectable.

Resume reuses the same resolution. It may not pick up a newer suite alias or
silently replace missing cases. The external registry and approval records
remain authoritative after sealing: resume revalidates revocation, expiry,
rights, availability, and approval scope and emits a new receipt without
mutating the original manifest.

## 14. First five-arm experiment mapping

The approved experiment in [`07-first-policy-experiment.md`](07-first-policy-experiment.md)
uses this registry as follows:

| Experiment need | Registry contract |
|---|---|
| Existing 20 queries | `research-policy-v1`, object revision `1.0.0`, development only |
| Five policy arms | Same suite/case refs for A–E; policy belongs in `RunManifest`, not suite data |
| Five-query screen | Predeclared case-id selection recorded in campaign manifest |
| Three repeats | Same task revision; distinct episode/repeat ids |
| Controlled retrieval | One source-snapshot revision shared within paired blocks where practical |
| Live retrieval follow-up | Separate campaign mode and result aggregate |
| Task slices | Versioned case tags declared before results are unblinded |
| Primary measures | Versioned rubric items; no blended score |
| Human adjudication | New label-set revision linked to the original run artifacts |
| Validation/sealed promotion | New limited-access task/split revisions; not the public v1 task set |

The registry design and dry-run resolution are no-cost P0 work. Running any arm
with live models, commissioning paid labels, downloading a paid dataset, or
hosting restricted assets remains separately approval-gated.

## 15. External benchmark adapters

An external benchmark must not be copied into this repository merely to fit
the registry. Its adapter records:

- upstream name, version, canonical location, citation, and license;
- acquisition procedure and digest of the acquired package;
- access requirements and whether redistribution is forbidden;
- task conversion and output normalization versions;
- evaluator/official-server protocol;
- contamination and known train-set exposure;
- environment, resource, time, and monetary costs;
- which internal capability claim the benchmark can and cannot support.

For server-held or secret tests, the local registry holds only permitted
metadata and an adapter version. The external service's result receipt is
stored with the campaign artifacts and its trust limitations are explicit.

## 16. Proposed repository layout

Names require an implementation ADR, but this separation is the target:

```text
eval_registry/
  suites/
  task_sets/
  rubrics/
  labels/                 # only data permitted in the repository
  source_snapshots/       # metadata and small licensed fixtures
  fixture_sets/
  splits/
  graders/
  external_adapters/
  schemas/
```

Restricted validation/sealed payloads must live behind an access-controlled
store or broker, not in Git history. Registry references may resolve to an
authorized object-store locator, but locators and audit metadata must not carry
credentials.

## 17. Validation and integrity

Validation occurs in layers:

1. schema shape and controlled-vocabulary validation;
2. canonical serialization and digest verification;
3. referential integrity and compatible schema ranges;
4. unique ids and stable ordered membership;
5. split disjointness and visibility-policy validation;
6. rubric/label/task target coverage and denominator validation;
7. source license, expiry, deletion, and required-attribution checks;
8. no-secret and redaction scanning;
9. candidate/evaluator access graph validation;
10. campaign resolution into an immutable lock document.

Invalid or unavailable objects fail before provider initialization. A missing
label may be acceptable for an explicitly exploratory metric, but it must yield
an unavailable/null result with a visible denominator—not an implicit pass.

## 18. Migration plan

### M0 — schemas and dry-run resolver

- Define typed refs, canonical serialization, digest calculation, suite/task/
  split schemas, and lifecycle rules.
- Add a CLI that validates and resolves a suite without running an agent.
- Fail closed on restricted split types until an access broker exists.

### M1 — research development suite

- Adapt `BENCHMARK_QUERIES` into immutable task cases without changing query
  behavior.
- Move or reference `expected_topics` as evaluator material instead of copying
  it into `TaskSpec`.
- Register current metrics and judge prompts as a grader profile.
- Keep the existing runner compatible while it begins writing registry refs.

### M2 — guided-learning suite

- Register personas, papers, scripts, structural expectations, and fixture
  manifest as separate referenced objects.
- Preserve existing scenario ids and the research/learning metric boundary.
- Record scripted learner content as untrusted candidate-visible input.

### M3 — validation and sealed broker

- Add independent storage, narrow runtime capabilities, access audit, and
  owner-only split membership.
- Create new tasks; do not relabel the public development tasks as sealed.

### M4 — source snapshots and external adapters

- Add controlled retrieval snapshots for paired experiments.
- Adopt external probes one at a time after license, contamination, cost, and
  task-fit review.

No migration deletes or rewrites existing benchmark history. Old output rows
with no registry ref are labeled `legacy_unresolved`; an optional migration
index may link them to a likely revision only when the exact Git commit and
input bytes prove the match.

## 19. No-cost test plan

All tests below use synthetic or checked-in data and must make zero provider or
network calls.

### Schema and identity

- canonical serialization produces the same digest across key ordering and
  platforms;
- any semantic byte change produces a new digest;
- mutable aliases are rejected in locked campaign manifests;
- duplicate ids, missing refs, incompatible versions, and digest mismatches
  fail with precise errors;
- historical revisions remain resolvable after a new revision is added.

### Split and leakage

- development, validation, sealed, and canary memberships obey declared
  disjointness rules;
- the policy-side resolver cannot read `LabelSet`, hidden rubric fields,
  split-membership secrets, or canaries;
- trajectories and generated artifacts contain no hidden sentinel;
- a candidate cannot select cases, change exclusions, or edit grader refs;
- unsupported restricted mode fails closed rather than falling back to a
  visible file.

### Campaign correctness

- a dry run resolves the same case/digest order twice;
- resume pins the original lock document even after a newer suite exists;
- repeats create distinct episode ids without duplicating task identity;
- errors, timeouts, cancellations, null grades, and exclusions stay in the
  expected denominator;
- paired arms resolve the same task and source snapshot refs;
- live-source and snapshot campaigns cannot be aggregated accidentally.

### License, privacy, and retention

- expired, revoked, deleted, or prohibited-use objects cannot start a run;
- required attribution survives object resolution;
- secret-shaped values and absolute private paths fail registry lint;
- deletion tombstones preserve identity/audit history without retaining
  prohibited content;
- training export rejects every object without affirmative permitted-use and
  consent metadata.

### Backward compatibility

- all current research query ids map one-to-one into the first task set;
- all current guided-learning scenario ids and fixture refs remain stable;
- existing runners can consume adapters without score-semantic changes;
- legacy outputs remain readable and are not falsely presented as fully
  resolved registry runs.

## 20. Acceptance criteria

AE-003 is complete only when:

1. a research suite and a guided-learning suite validate locally;
2. every object resolves by logical id, immutable revision, and digest;
3. one case from each lane compiles into a valid `TaskSpec` without exposing
   evaluator-only data;
4. a dry-run campaign produces a locked `RunManifest` input set and makes zero
   network/provider calls;
5. paired arms can prove they used the same task and source revisions;
6. failures, exclusions, repeats, and null metrics have explicit denominators;
7. split access tests prove fail-closed behavior;
8. license, data-classification, retention, contamination, and prohibited-use
   fields are required and tested;
9. the public 20-query suite is mechanically barred from claiming sealed
   promotion evidence;
10. no candidate policy can modify task membership, labels, graders, safety
    gates, budget approvals, or registry activation state.

## 21. Cross-RFC invariants

- `TaskSpec` records the exact suite/task-case refs from which it was compiled,
  but never hidden label content.
- the control-plane `RunManifest` pins all resolved registry refs and the
  campaign approval record; registry metadata does not itself authorize spend.
  Its policy-runtime projection excludes split membership, labels, graders,
  approval details, and restricted object locators.
- `TrajectoryEvent` uses `run_id`, `task_spec_id`, artifact refs, and public
  rubric-item ids; it never embeds evaluator-only labels or sealed membership.
- policy, prompt, model, and tool versions belong to `RunManifest` or their own
  registries, not to the benchmark suite.
- results and human adjudications refer to immutable output artifacts; they do
  not mutate the task or prior label revision.
- a suite cannot be both candidate-authored and independent promotion evidence
  for that candidate.
- registry validation completes before any live provider client is created.

## 22. Open decisions and recommendations

| Decision | Recommendation | Needed before |
|---|---|---|
| Registry serialization | Shared `agent-contract-json/v1` RFC 8785 profile; YAML is authoring-only | M0 implementation |
| Logical versioning | Semantic object revisions plus SHA-256 content digests | M0 implementation |
| Initial storage | Git for public/development metadata and small licensed fixtures | M1 implementation |
| Restricted storage | Separate access broker/object store; fail closed until selected | Validation/sealed work |
| Rubric visibility | Explicit per-item visibility, hidden by default for reference answers | M1 implementation |
| Public v1 status | Development/regression only | M1 activation |
| Split sizes/content | Decide after task taxonomy and expert review; do not generate by ratio alone | New validation suite |
| Human label format | Preserve individual labels plus adjudication, never consensus-only overwrite | AE-004 |
| Training eligibility | Prohibited by default until D8 consent/retention policy is approved | Any export/training |
| External benchmark adoption | One adapter per ADR with license, contamination, and cost review | P4 capability probes |
| Retention periods | Define by object class and license; learner data gets strictest default | Restricted data collection |
| Hash algorithm agility | Prefix digests with algorithm; start with SHA-256 | M0 implementation |

The remaining choices are implementation details except restricted storage,
split content, human-label governance, and training eligibility. Those change
the trust boundary and require owner decisions before the relevant work begins.
