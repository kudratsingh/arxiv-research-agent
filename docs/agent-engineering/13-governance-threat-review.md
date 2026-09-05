# P0 governance and threat-review decision package

Status: **PROPOSED FOR OWNER RULING — NO DATA COLLECTION OR POLICY ENABLEMENT**

Date: **2026-09-05**

Work order: **P0-WO09**

Dependency: **P0-WO00 shared contract kernel only**

This package makes the decisions behind D8 reviewable before the system gains
a persistent trajectory store for product or learner traffic, a restricted
evaluation store, a human-labeling campaign, or a training export. It does not
authorize any of those activities. It makes no provider call, collects no new
data, changes no runtime behavior, and does not approve spend.

The recommended initial ruling is deliberately narrow:

> Permit synthetic, provider-free P0 contract qualification with
> `training_eligible=false`. Keep persistent product and learner trajectory
> capture, human evaluation, validation/sealed data, and every training export
> disabled until the owner accepts or amends the decisions in section 12 and
> the corresponding implementation and deletion exercises pass.

## 1. Scope and authority

This document governs the future P0 contract family:

- `TaskSpec` and its referenced task/context objects;
- full and candidate-safe `RunManifest` records;
- trajectory envelopes and their referenced artifacts;
- benchmark-registry objects, labels, graders, and split metadata;
- product feedback and human-evaluation records; and
- derived evaluation, analytics, replay, and possible future training data.

It also maps the new contracts onto current stores so an implementation cannot
make a deletion promise that covers only the new tables.

The package does **not**:

- change the current job, conversation, checkpoint, cache, learner-profile, or
  progress-event lifecycle;
- choose a cloud, database, key-management vendor, or legal basis;
- assert that a hash chain is a deletion mechanism;
- authorize validation/sealed material on an agent-readable filesystem;
- authorize model judging, human labeling, provider use, deployment, or spend;
- add a training consent scope to trajectory v1; or
- create a second provenance, statistics, semantic-convention, groundedness,
  reason-code, or synthetic-campaign registry.

Where a value is marked **OWNER**, implementation must fail closed until the
owner records an answer. An engineer may recommend a value but may not convert
an unanswered policy question into a default.

## 2. Existing contracts this package reuses

The following are inputs, not surfaces for W09 to redesign.

| Concern | Existing source of truth | W09 rule |
|---|---|---|
| Contract refs, canonical JSON, timestamps, fixed money, sensitivity order, retention refs | `src/contracts/kernel.py` (P0-WO00) | Reuse `ImmutableObjectRef`, `DataClass`, `RetentionPolicyRef`, and `agent-contract-json/v1`; do not define aliases here |
| Runtime error codes | `src/errors.py` and ADR 0064 | Runtime adapters map failures to existing `AppError.code` values; contract-local validation errors do not become a competing application registry |
| GenAI telemetry names | `src/observability/semconv.py` and ADR 0066 | Event-to-trace projections use the pinned `gen_ai.*` table; event schemas do not copy those constants |
| Correlation context | `src/observability/context.py` and ADR 0067 | Use `RequestContext` for correlation only; keep content capture off and logs bounded/redacted |
| Eval provenance | `src/eval/provenance.py` and ADR 0070 | Legacy eval import and evaluation artifacts wrap the existing provenance block; do not create a parallel manifest-shaped block |
| Repeats, pairing, denominators, and confidence procedures | `src/eval/stats.py`, the runner's `--repeats`, and ADR 0071 | A campaign or trajectory view consumes these results; it does not reimplement the statistics |
| Deterministic claim verification | `src/eval/groundedness.py` and ADR 0074 | Per-claim outcomes are the verification payload/input; they remain versioned and attributable |
| Zero-cost research episodes | `src/eval/simulate_research.py` and ADR 0075 | Synthetic qualification consumes these episodes after its hook seam lands; it never initializes a provider client |

There is one integration mismatch to resolve before a product event bridge:
`RequestContext` carries `run_id`, `job_id`, `request_id`, `job_kind`, a salted
`principal_hash`, and `worker_id`. It intentionally does **not** carry the raw
`principal_key_id` or an actor/role. Therefore:

1. correlation fields and trace linkage come from `RequestContext` and the
   active OTel span;
2. authorization scope comes from the authenticated `ApiKeyPrincipal` or the
   already-owned resource, not from a log correlation digest;
3. actor role comes from the authenticated service/role boundary; and
4. an adapter must reject a mismatch among run ownership, authenticated
   principal, and proposed event scope.

Adding raw identity or authority to `RequestContext` would reverse ADR 0067's
privacy boundary and is not approved by this package.

## 3. Data inventory

The inventory separates content from control metadata. A digest, stable
pseudonym, source locator, or label can still be personal, confidential, or
restricted even when it is not prose.

### 3.1 P0 objects

| Object | Content and identifiers | Default class | Authoritative owner | Initially permitted purposes | Prohibited by default | Deletion/retraction unit |
|---|---|---|---|---|---|---|
| TaskSpec | Objective/deliverables, public rubric refs, source/tool limits, immutable context refs, task identity | Research conversation: `user_confidential`; learning: `learner_sensitive`; synthetic/public benchmark: `public` or `internal` | Task compiler plus source/registry policy | One declared episode; synthetic contract tests | Hidden labels, unrestricted raw context, approval secrets, training | Entire spec plus principal-scoped referenced context; retain only a content-free erasure receipt |
| Full RunManifest | Task/config refs, policy/model/prompt/tool/code/environment snapshots, budgets, evaluator refs, approval receipt refs, principal scope | Most restrictive input class; control-plane-only | Admission controller | Admission, reproducibility, accounting, approved evaluation | Candidate access, public export, approval conversation, credentials, training | Manifest and private projections become unavailable together; a sparse campaign audit may remain |
| Candidate runtime projection | Least-privilege task and execution material plus projection digest | At least TaskSpec class | Admission controller | Execute the admitted task | Evaluator/split/label/approval/private-locator disclosure | Deleted with run content; projection digest alone is not permission to retain content |
| Trajectory event | IDs, typed decisions, counts, reason codes, artifact refs, usage delta, governance and replay metadata | Most restrictive of run, payload, and artifact classes | Append service under run ownership | Synthetic evaluation initially; later approved product operation | Raw prompts/documents/reports/learner text, hidden reasoning, training | Run/principal erasure or cryptographic erasure; intentional erasure may make the chain unavailable |
| Artifact | Prompt-independent report, source observation, checkpoint, human response, evaluation output, or other referenced bytes | Declared per artifact, never below run/task minimum | Artifact service under run and role scope | Only the artifact role and purpose declared at creation | Signed URLs, secrets, silent cross-purpose reuse, training inheritance | Byte deletion or key erasure, all replicas/derived indexes, then `artifact_unavailable` in allowed views |
| Registry metadata | Suite/task/rubric/source/license/retention/contamination/lifecycle records | `public` or `internal`, with separately restricted object visibility | Registry steward | Development and explicitly allowed evaluation purposes | Candidate mutation, spend authorization, implicit activation | New immutable revision, revoke/tombstone; do not rewrite history |
| Restricted registry object | Validation/sealed cases, labels, grader config, canaries, restricted locators | At least `internal`; labels/canaries may be more restrictive | Independent evaluator/data steward | Predeclared evaluation only | Candidate/developer bulk access, training unless separately approved | Revoke object, delete content when required, retain a content-free tombstone and review record |
| Human label/adjudication | Target/evidence refs, individual label, pseudonymous annotator/adjudicator id, guideline revision, disagreement lineage | Maximum of source data and human-evaluation classification | Human-evaluation steward | Approved human evaluation and calibration | Product operation inheritance, consensus overwrite, training inheritance | Delete or key-erase human identity mapping and restricted evidence; preserve only approved pseudonymous audit facts |
| Product feedback | Rating/action, optional free text, task/output refs, principal scope, timestamp | Research: `user_confidential`; learning: `learner_sensitive` | Product data steward | Product operation or support under the declared notice | Evaluation, human review, or training unless separately consented | Principal-scoped feedback and derived features; retained aggregate must pass de-identification review |
| Eval result | Metrics, failures, nulls, denominators, per-claim outcomes, provenance, run/artifact refs | Maximum of evaluated material and evaluator policy | Evaluation runner/evaluator | Evaluation and promotion decision for the declared campaign | Relabeling as ground truth, candidate mutation, training inheritance | Campaign policy; preserve sparse decision/audit facts only when permitted |
| Training export (future) | Selected events/artifacts/labels plus inclusion, consent, redaction, and lineage records | Source class; often restricted | Separate data steward, never the candidate | None in v1 | Creation or consumption | Not applicable until a later schema and affirmative D8/training decision |

### 3.2 Current adjacent stores

These stores predate P0. A future deletion orchestrator must include them when
they contain or reference the same principal or run.

| Current surface | Data | Current lifecycle fact | W09 implication |
|---|---|---|---|
| Job store | Query, status, result/report, event snapshots, cost/error fields, `principal_key_id` | Terminal records expire via `api_job_retention_sec` (currently bounded to at most 24 hours) | New trajectories cannot silently outlive the user-visible job under a broader purpose |
| Conversation store | Thread title and prior job/report relationships | Principal-scoped; whole-conversation delete exists | Conversation deletion must cascade to new conversation-derived artifacts/trajectories or explicitly report what remains |
| LangGraph checkpoints | Research/session state and, for sessions, transcript source | Backend-specific; no P0 erasure orchestration exists | Product trajectory enablement waits for checkpoint deletion coverage |
| Paper/embedding caches | Public arXiv text and derived vectors | Shared, not currently principal-owned; cache purge remains a follow-up | Exempt from principal deletion only when inputs are demonstrably public and not user-derived |
| Learner profile | Goals, notes, skill claims, provenance, `principal_key_id` | Whole-principal delete; flag and auth gated | Always `learner_sensitive`; its data may not flow to evaluation/training by implication |
| Progress ledger | Evidence-linked append-only learner events | Whole-principal `erase_principal`; no per-event edit/delete | P0 append-only semantics must retain the same explicit erasure door |
| Logs/traces/metrics | Bounded metadata, error/correlation fields; optional content capture | ADRs 0066/0067 keep content capture off by default and use `principal_hash` | P0 must not add raw ids/content to telemetry; deletion claims must state telemetry limitations |
| Eval outputs | Rows, summaries, reports, provenance, failure/null denominators | Campaign artifacts; research scripted baseline is synthetic and zero-cost | Apply the campaign's policy; never backfill unknown provenance or drop failed rows |

## 4. Processing-purpose and consent matrix

Consent is one input to permission, not the only input. Rights, contract,
security, split policy, and the applicable retention policy must also permit
the operation. A producer may narrow a purpose but may not elevate one.

| Purpose | May use | Required authority | Default | Explicit exclusions |
|---|---|---|---|---|
| `product_operation_only` | Minimum task/run state needed to answer the user's request or run a guided session | Product notice/contract and authenticated principal scope | Allowed only on current approved stores; **new persistent trajectories off** | No evaluation, cross-user analytics, human review, or training inheritance |
| `support_only` | User-selected diagnostic artifacts and bounded audit metadata | Case-specific support authorization and restricted support role | Off | No bulk browsing, model improvement, benchmark use, or training |
| `aggregate_analytics` | Approved de-identified aggregates from minimized exports | Owner-approved analytics purpose plus de-identification review | Off for P0 trajectories | No unrestricted event query, raw principal ids, small-cell disclosure, or row-level export |
| `human_evaluation` | Preselected outputs/evidence needed by an approved rubric | Separate human-evaluation notice/consent or other recorded authority, evaluator role, time/cost approval | Off | No full account history, unrelated learner profile, silent training reuse |
| `evaluation_only` | Synthetic/development cases, manifests, minimized trajectories, deterministic evaluator outputs | Active registry purpose and campaign lock | Allowed for synthetic Stage 0 only | No production/learner content, no sealed claim from public development data |
| `public_source_evaluation` | Lawfully stored public source material and derived evaluation artifacts | License/source-rights review and active registry record | Allowed only where rights are affirmative | Public availability alone does not imply redistribution or training permission |
| `synthetic_test` | Generated fixtures with no person or confidential source represented | Fixture provenance and secret/canary lint | Allowed | No copied production prose, identifiers, credentials, private paths, or sealed material |
| Future training | Separately promoted, versioned dataset records | **New affirmative training decision**, specific consent/rights, deletion/retraction lineage, independent approval | Prohibited; no v1 consent value exists | Product operation, feedback, labels, public availability, or evaluation never imply training permission |

Rules that apply to every row:

1. Effective purpose is the intersection of TaskSpec, platform, registry,
   source/license, campaign, and consent constraints.
2. `training_eligible` remains false for every P0 event even when another
   purpose is permitted.
3. Learner data defaults to `learner_sensitive`, content capture off, no
   aggregate export, and the shortest approved content-retention window.
4. Human labels preserve individual decisions and adjudication lineage; an
   adjudicated result does not erase disagreement.
5. Withdrawal or source retraction blocks new use immediately and starts the
   applicable erasure/rebuild process. It does not wait for the next campaign.
6. Historical records with unknown consent or provenance stay unknown and are
   ineligible; they are never backfilled as permitted.

## 5. Retention, deletion, retraction, export, and legal hold

### 5.1 Proposed retention profiles

The numbers below are recommended maximums for the **future P0 stores**, not a
retroactive change to current stores. Source terms or a user's earlier deletion
always shorten them. The owner must accept or replace each value before the
corresponding use is enabled.

| Proposed policy | Content/bytes | Minimized non-content audit | State before owner ruling |
|---|---:|---:|---|
| `synthetic-fixture-repository-v1` | Repository history while active; revoke on secret/personal-data discovery | Repository/ADR history | May be used only after fixture lint proves synthetic |
| `development-eval-90d-v1` | 90 days after campaign close | 365 days | Synthetic/public development only |
| `validation-sealed-90d-v1` | 90 days after promotion decision, shorter if rights require | 365 days | Blocked on real access broker and owner acceptance |
| `product-research-30d-v1` | 30 days after terminal run unless user deletes earlier | 90 days | Blocked |
| `learner-sensitive-30d-v1` | Raw transcript/artifacts 30 days; structured profile/ledger only while service need remains | 90 days after principal erasure | Blocked; strictest access and purpose defaults apply |
| `human-eval-90d-v1` | Source/output packet 90 days after adjudication | Pseudonymous label lineage 365 days, only if permitted | Blocked on human-evaluation authority |
| `training-v1` | Not defined | Not defined | Prohibited |

Checked-in public benchmark metadata may use the registry's
`repository_history` deletion mode. That exception is invalid for personal,
licensed non-redistributable, validation, sealed, canary, or secret material.

### 5.2 Deletion semantics

Deletion is an orchestrated, idempotent operation scoped by principal, run,
conversation, campaign, source, or registry object. It must enumerate:

- primary rows and object bytes;
- candidate-safe and evaluator projections;
- checkpoints and staged/partial artifacts;
- derived chunks, embeddings, indexes, caches, summaries, and exports;
- replicas, backup expiry, local downloads, and queued work;
- human-evaluation packets and annotator identity mappings where applicable;
- source-provider copies covered by the provider agreement; and
- registry links that must become revoked, retracted, or unavailable.

Content that must be removed includes prose, labels, responses, source bytes,
embeddings derived from non-public content, private locators, stable principal
mapping, and any digest that remains a practical cross-domain correlation key.

The retained **non-content** erasure receipt may contain only:

- opaque request and receipt ids;
- object kinds and counts, not object titles or content digests;
- requested, started, completed, and verified timestamps;
- retention-policy ref and policy revision;
- completion state and an existing safe reason/error code;
- counts still under an authorized legal hold; and
- key-erasure and backup-expiry attestations by opaque reference.

It must not retain raw principal ids, user/learner text, source locators,
evaluator material, approval conversations, secrets, or a reversible content
fingerprint. If regulation or contract requires stronger audit identity, that
is an **OWNER/legal** decision and belongs in a separately restricted audit
domain.

Append-only and hash-chained do not mean undeletable. An authorized principal
erasure may delete or cryptographically erase a run and make its historical
fold unavailable. The external erasure receipt explains that absence. The
system must not rewrite remaining events to fabricate a valid chain.

### 5.3 Retraction and correction

- Correcting an operational fact appends a superseding record; it does not
  overwrite a prior accepted event or label.
- Withdrawing consent or retracting a source stops new processing immediately.
- A registry retraction creates a new revision/status, invalidates new
  resolution, identifies affected campaigns, and either deletes restricted
  bytes or records why a legal hold prevents deletion.
- Derived datasets, indexes, baselines, and promotion decisions receive an
  impact assessment. A result is marked invalidated rather than silently
  recomputed under different inputs.
- Training, if ever authorized later, must support source-event retraction and
  document whether unlearning, model retirement, or non-retrain is the approved
  remedy. P0 makes no such claim.

### 5.4 Principal export

A principal export is authenticated, rate-limited, generated from an ownership-
scoped query, and itself assigned a short retention policy. It includes the
principal's product data and human-readable provenance, not:

- another principal's rows or aggregate small cells;
- credentials, approval internals, private infrastructure locators, or system
  prompts;
- sealed/validation membership, hidden labels, canaries, grader prompts, or
  evaluator-only decisions; or
- private model reasoning.

The export manifest lists unavailable/expired artifacts and active legal holds
without reconstructing deleted content. Export generation must not reset the
source objects' retention clocks.

### 5.5 Legal hold

A legal hold is a purpose restriction, not broader permission. Only a named
privacy/legal role may create or release one. It must be object-scoped,
time-bounded or reviewed on a declared cadence, stored outside candidate
authority, and auditable. Held data:

- moves to a separately restricted key/access domain;
- is excluded from product reuse, analytics, evaluation, and training unless
  the hold authority separately permits the specific purpose;
- remains invisible to candidates and ordinary support/operators; and
- is deleted promptly after release under the original policy.

## 6. Principal, tenant, and evaluator access model

Authentication, authorization, and correlation remain separate:

- `principal_key_id` is the current resource-owner key from ADR 0036. It is
  not public experiment content and is not a telemetry label.
- `principal_hash` is a salted correlation value from ADR 0067. It is not an
  ownership key and cannot authorize a read or append.
- `actor` states which authenticated role performed an action. A producer may
  not self-declare a more privileged actor.
- synthetic fixtures use an explicit `synthetic:*` principal and can never
  query or join product principals.

| Role | Product TaskSpec/run/event/artifact | Development registry | Validation/sealed input | Labels/graders | Governance/audit | Training export |
|---|---|---|---|---|---|---|
| Product principal | Own data through scoped API/export | No special access | None | None | Own deletion/export status only | None |
| Candidate runtime | Least-privilege projection and authorized observations for one run | Candidate-visible development case only | One brokered runtime payload, never registry root | Public rubric items only | None | None |
| Runtime service | Append/read within authenticated run and purpose | Resolved refs | Brokered case input only | None | Admission/erasure receipts by opaque ref | None |
| Evaluator | Immutable final output plus authorized evidence | Required evaluator objects | Required case/labels after output seal | Read/use, never mutate through candidate path | Evaluation audit | None by implication |
| Registry steward | Metadata lifecycle and development activation | Read/write with review | Metadata via broker, not raw candidate path | Manage immutable revisions | Registry audit | Cannot self-approve training |
| Privacy/data steward | Purpose, retention, deletion, export, hold | Governance metadata | Access only when required for review | Restricted review | Full restricted governance audit | Approval participant only |
| Support operator | Case-scoped, time-limited, user-authorized material | None | None | None | Bounded support audit | None |
| Training pipeline (future) | None directly | Only separately promoted dataset | None directly | Only dataset-authorized labels | Inclusion/retraction lineage | Disabled until a later ADR and approval |

Required enforcement properties:

1. Every query constrains by principal/domain before pagination or object load;
   cross-principal misses return the same not-found behavior.
2. Artifact access rechecks ownership and purpose independently of event access.
3. Validation/sealed access uses a separate broker credential and process
   boundary. A hidden directory in this checkout is not a boundary.
4. The evaluator sees hidden material only after the candidate output is
   immutable. The candidate cannot choose cases, remove failures, edit labels,
   graders, gates, or registry lifecycle.
5. Registry activation, campaign approval, evaluation, and promotion require
   distinct authority. A candidate or evaluator cannot promote itself.
6. Audit access is itself audited; bulk export requires a separate decision and
   small-cell/de-identification review.

## 7. Encryption and key-erasure proposal

This proposal is vendor-neutral and intentionally deferred from the W04
in-memory schema. Before any persistent restricted or product store exists:

```text
root key in managed KMS/HSM
  -> environment/domain key-encryption key (product, learner, sealed, audit)
    -> tenant/principal or campaign key-encryption key
      -> per-object or per-run data-encryption key
        -> encrypted event/artifact bytes
```

Requirements:

- encryption in transit and at rest is mandatory but insufficient without
  role/principal access checks;
- raw keys, wrapped key material, provider credentials, and private KMS
  locators never enter TaskSpec, candidate projections, trajectory rows,
  telemetry, or public exports;
- control-plane records use opaque key references only where needed;
- learner, product, sealed-evaluation, and audit domains use separate keys;
- deleting a principal/run destroys the relevant data-encryption key and all
  live wrapped copies, then records backup-expiry/key-erasure attestations;
- shared keys may not be used where erasing one principal would destroy
  another principal's data;
- rotations preserve read access only for objects still within policy;
- deterministic global hashes of user-controlled content are not used as
  cross-principal deduplication identifiers; and
- restore tests prove erased objects do not reappear from replicas or backups.

Crypto-erasure does not erase plaintext already copied to logs, exports,
provider systems, indexes, or human work queues. The deletion inventory must
cover those independently. The exact KMS, backup, rotation, and digest design
is an **OWNER/architecture** decision before W08 production persistence.

## 8. Threat model

### 8.1 Assets, actors, and trust boundaries

Protected assets include user and learner content, identity mappings,
restricted cases/labels/canaries, approval and budget state, source material,
artifacts, evaluator prompts/results, campaign denominators, registry
lifecycle, and encryption keys.

Relevant adversaries include a malicious source author, malicious or confused
user, compromised candidate policy, compromised tool/provider response,
curious cross-tenant user, over-privileged developer/operator/evaluator,
benchmark contributor trying to favor a candidate, and an attacker with write
access to one store but not every trust anchor.

The critical boundaries are browser-to-API identity, runtime-to-tool/source,
candidate-to-control-plane, candidate-to-evaluator, development-to-sealed
registry, event-to-artifact storage, telemetry export, and data-to-training
promotion.

### 8.2 Required threats and controls

| Threat | Attack path and impact | Existing control to reuse | Required gate before affected use | Residual/owner decision |
|---|---|---|---|---|
| Prompt injection | Paper, prior report, learner text, tool error, or metadata writes instructions into executable fields or exfiltrates secrets | ADRs 0020/0033/0058 isolation; strict typed actions; ADR 0072 adversarial suite | Canaries cannot reach action ids, control payloads, logs, unrelated artifacts, or profile rows; synthesizer/verifier gap assessed | Whether/when prompt isolation becomes default; new tool trust policy |
| Label leakage | Candidate receives split identity, reference answer, grader prompt, canary, or label through manifest, event, artifact, log, cache, or error | Runtime projection; registry visibility; content-off telemetry | Negative projection tests and broker audit; evaluator starts only after final artifact seal | Real validation/sealed broker and operator roles |
| Benchmark tampering | Candidate/developer changes membership, label, grader, exclusion, denominator, or baseline after seeing results | Immutable registry refs/revisions; campaign lock; ADRs 0070/0071 provenance and denominator logic | Independent activation/review; digest verification; failed/null rows retained; changes force new campaign | Who may activate/revoke and sign campaign locks |
| Evaluator capture | Candidate influences judge prompt/input, evaluator optimizes to product output, self-grades, or selects favorable failures | Pinned/versioned rubrics and judge provenance (ADR 0070); independent deterministic groundedness (ADR 0074); paired stats (ADR 0071) | Candidate cannot mutate evaluator config; model output never becomes ground truth; human calibration precedes funded judge claims | Calibration set, adjudicator role, acceptable error by slice |
| Source-rights breach | Store/redistribute/reuse paper, user upload, external benchmark, or derived text beyond license/consent; ignore retraction | Registry license/permitted-use/expiry fields and SourceSnapshot lifecycle | Rights resolved before acquisition; metadata-only fallback; retraction impact report | Source-specific retention and redistribution authority |
| Artifact correlation | Global digest, locator, event id, principal id, or timing lets one tenant test another tenant's content/existence | Principal-scoped access; ADR 0067 salted telemetry identity; no signed URLs in rows | Cross-principal zero-tolerance tests; no global user-content dedup id; bounded/de-identified analytics | Per-principal keyed digest and opaque handle design |
| Cross-principal access | ID guessing, pagination/filter error, stale worker context, or artifact/event scope mismatch reads/writes another tenant | ADRs 0036/0043 ownership checks; immutable RequestContext with reset | Ownership predicate in storage query, artifact recheck, concurrency/context propagation tests | Stable owner id migration beyond mutable key name |
| Telemetry leakage | Raw prompt, label, learner text, credential, private locator, or raw principal id enters logs/traces/metrics | ADRs 0066/0067 content-off, allowlisted bounded logs, redaction, salted principal hash | Static/runtime forbidden-field tests; capture remains off for production P0 | Telemetry retention and deletion capability of chosen backend |
| Hash-chain rewrite or deletion concealment | Store writer mutates events and recomputes a local chain; accidental deletion appears valid | W04 hash chain and separately retained head in future | Integrity verification; production trust-anchor decision; intentional erasure receipt | Signed internal head versus external immutable anchor |
| Retention bypass | Copies in checkpoints, caches, exports, backups, evaluator queues, or derived embeddings survive deletion | Existing whole-principal learner erasure; required inventory/receipts | End-to-end deletion and restore exercise across every configured backend | Backup maximum and provider deletion terms |
| Consent/purpose laundering | Product operation, feedback, public source, or human label is silently reused for evaluation/training | Explicit purpose matrix; v1 has no training scope; `training_eligible=false` | Promotion job fails on absent affirmative metadata and lineage | Future training consent language and withdrawal remedy |
| Replay misrepresentation | Held-constant/simulated observations are reported as live evidence, cost, freshness, or quality | RFC 10 replay status/divergence contract | Export labels every observation origin and refuses unsupported quality claims | Maximum permitted counterfactual depth |
| Cost/approval leakage | Credential possession or registry activation is treated as spend authority; approval details leak to candidate | Run admission and sparse external approval refs | Admission fails before client init; projection excludes approval internals | D9 remains separate and blocked |

### 8.3 Security properties that remain unproven

- The current prompt-isolation follow-up still names synthesizer and verifier
  source text as an unclosed injection surface.
- No real restricted-store/broker boundary exists for validation or sealed data.
- No P0 event/artifact Postgres store, key hierarchy, deletion orchestrator,
  backup erasure proof, or external hash trust anchor exists.
- The current principal key name is a mutable display identifier; ADR 0063
  expects a future stable owner model.
- Current telemetry backends' retention/deletion behavior is deployment-
  specific and not an account-erasure guarantee.
- No human-label consent, annotation workforce policy, or calibration set has
  been approved.
- Training eligibility, unlearning, and model-retirement remedies are
  intentionally undefined.

These are blockers for the affected modes, not reasons to weaken a test.

## 9. Use-mode decision checklist

An unchecked **required** item means the mode stays disabled.

| Check | Development | Validation | Sealed | Production | Human evaluation | Training |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Active immutable registry refs and rights review | required | required | required | when registry data used | required | required |
| Candidate-safe projection leakage test | required | required | required | required | required | required |
| Synthetic/no-person fixtures only | required initially | no | no | no | no | no |
| Real broker outside candidate-readable storage | no | required | required | for restricted assets | required for hidden labels | required |
| Authenticated principal and role enforcement | no human principal | required | required | required | required | required |
| Accepted purpose/consent record | synthetic purpose | required | required | required | required | affirmative training-specific |
| Accepted retention policy with exact durations | repository fixture policy | required | required | required | required | required |
| End-to-end deletion, derived-data, backup restore exercise | fixture revocation test | required | required | required | required | required |
| Encryption/key-erasure design implemented | no secrets/persons | required | required | required | required | required |
| Prompt-injection/adversarial gate | required | required | required | required | required | required |
| Independent evaluator and immutable final artifact | advisory | required | required | for promotion claim | required | required |
| Provenance, repeats, failures/nulls, denominators | required | required | required | for evaluation | required | required |
| Human-label calibration/lineage | no | as applicable | required for human claim | as applicable | required | required |
| Owner implementation/deployment approval | local/no-cost only | required | required | required | required | required |
| D9 spend approval | never spend | if chargeable | if chargeable | if chargeable | time/model cost | training/compute cost |

Mode-specific outcomes:

- **Development:** synthetic/public development fixtures may qualify contracts
  locally. They cannot support sealed promotion evidence.
- **Validation:** fail closed until a broker, access roles, accepted retention,
  and deletion exercise exist.
- **Sealed:** all validation requirements plus candidate isolation, canary
  controls, independent stewardship, and a confirmatory protocol.
- **Production:** no new persistent P0 trajectory capture until D8 is accepted
  for that product surface and rollout is separately approved.
- **Human evaluation:** no packet assembly or reviewer access until purpose,
  consent/authority, evaluator role, time/cost, and retention are approved.
- **Training:** prohibited. A later ADR must add a training-specific schema,
  consent evidence, selection/inclusion rationale, retraction lineage,
  independent holdout, and model-remedy decision.

## 10. Required verification evidence

Before a restricted or product mode can be proposed, its implementation must
produce no-cost evidence for:

1. cross-principal reads, writes, list pagination, artifact fetch, export, and
   deletion all fail closed;
2. synthetic principals cannot join or query product principals;
3. candidate projections contain no labels, split identity, grader config,
   canaries, approval detail, raw principal id, restricted locator, or secret;
4. context propagation/reset does not attribute one concurrent job to another;
5. event and artifact sensitivity never falls below the most restrictive
   TaskSpec/registry/platform input;
6. a product-operation record remains `training_eligible=false`;
7. source/license expiry and registry revocation block admission and resume;
8. deletion removes primary, derived, cached, exported, replicated, and
   restored copies, while the retained receipt contains no content;
9. corruption and intentional deletion are distinguishable without silently
   repairing the hash chain;
10. prompt-injection and secret canaries cannot become executable fields,
    telemetry, evaluator inputs outside scope, or unrelated artifacts;
11. the zero-cost research episode path and any hooks make zero provider calls
    and never initialize a provider client; and
12. historical unknown provenance remains unknown and ineligible.

Evidence from ADRs 0070, 0071, 0074, and 0075 satisfies its existing slice;
W09 does not demand a second implementation. The W05/W08 qualification report
should link those artifacts and add only the integration-specific evidence.

## 11. Rollout and rollback

Recommended order:

1. synthetic in-memory schema and replay tests only;
2. development registry plus provider-free scripted episodes;
3. persistent development adapter with synthetic fixtures and deletion test;
4. separately approved validation broker pilot;
5. separately approved human-evaluation or production capture pilot; and
6. training only after an entirely new decision and data contract.

Every mode is default-off. Rollback disables new writes and admissions first,
preserves already-required deletion/export access, completes in-flight erasure,
and marks affected registry/campaign revisions deprecated or revoked. Rollback
must not strand data in a backend whose deletion tool was gated off with the
writer.

## 12. Proposed D8 owner ruling

The owner should record **ACCEPT**, **AMEND**, or **REJECT** for each row. Until
then, the recommended enforcement state in the final column is binding for
implementation planning.

| Id | Proposed ruling | Owner | Enforcement while unresolved |
|---|---|---|---|
| D8.1 | P0 may persist only synthetic, provider-free development fixtures/events under an active synthetic retention policy | **OWNER** | Permit local synthetic qualification only |
| D8.2 | New persistent research-product and learner trajectory capture is default-off and requires a surface-specific rollout decision | **OWNER** | Block |
| D8.3 | Learner inputs, transcripts, profiles, progress evidence, events, and derived artifacts default to `learner_sensitive`, shortest content retention, and no aggregate reuse | **OWNER** | Block new learner trajectory capture |
| D8.4 | Product operation, support, analytics, human evaluation, and training are separate purposes; none inherits permission from another | **OWNER** | Enforce most restrictive intersection |
| D8.5 | Every v1 event remains `training_eligible=false`; training requires a later schema, affirmative authority, dataset promotion record, and retraction/model-remedy ADR | **OWNER** | Prohibit export/training |
| D8.6 | Validation/sealed evaluation requires a broker and storage/credential boundary outside candidate-readable workspaces, with evaluator independence and audited access | **OWNER** | Block validation/sealed activation |
| D8.7 | Adopt the proposed retention maximums in section 5.1, subject to shorter source/user terms | **OWNER** | Only repository-safe synthetic fixtures; all other policies inactive |
| D8.8 | Principal deletion covers content and derived copies across jobs, conversations, checkpoints, trajectories, artifacts, profiles, progress, eligible caches, exports, replicas, and backups; retain only the sparse receipt in section 5.2 | **OWNER** | Block new product/learner persistence until exercised |
| D8.9 | Append-only/hash integrity yields to authorized erasure; intentional erasure makes the run unavailable and is explained by an external sparse receipt rather than a rewritten chain | **OWNER** | Synthetic stores only |
| D8.10 | Human evaluation requires separate purpose authority, restricted evaluator role, individual-label/adjudication lineage, accepted retention, and any required time/spend approval | **OWNER** | Block human-evaluation campaign |
| D8.11 | Use vendor-neutral envelope encryption with separate learner/product/sealed/audit domains and per-principal/campaign erasure scope; select the concrete KMS/backup design in an implementation ADR | **OWNER** | Block persistent restricted stores |
| D8.12 | Raw identity and authority do not move into `RequestContext`; runtime event bridges combine correlation context with authenticated ownership/role inputs and reject mismatches | **OWNER** | Block product bridge that lacks both inputs |

This is the proposed D8 answer. Acceptance of one row does not approve spend,
deployment, collection in another mode, or training.

## 13. ADR outline after owner ruling

Do not assign an ADR number until the owner rules and the decisions index is
rechecked for concurrent additions.

**Title:** Govern P0 trajectory, evaluation, feedback, and future training data

**Status:** proposed, then accepted only with owner sign-off

**Context:**

- P0 adds immutable task/run/trajectory/registry contracts but no approved
  product trajectory store or training pipeline.
- Existing job, conversation, learner profile/progress, telemetry, and eval
  stores have different lifecycle behavior.
- Append-only evidence, principal erasure, sealed evaluation, human labels,
  source rights, and future learning use create distinct trust boundaries.

**Decision:**

- copy accepted D8.1–D8.12 values exactly;
- name the approved retention-policy revisions and role matrix;
- state which modes remain disabled;
- name the encryption/key-erasure and restricted-broker implementations once
  selected;
- require purpose-specific consent/authority with no training inheritance;
- require sparse erasure receipts and end-to-end deletion tests; and
- preserve the separate D9 spend gate.

**Alternatives considered:**

- retain everything because events are append-only — rejected, conflicts with
  erasure obligations and data minimization;
- one broad consent for product improvement — rejected, launders purpose and
  training permission;
- put sealed files in a private repository folder — rejected, candidate and
  developer access are not independently enforced;
- store raw content in events for debugging — rejected, artifacts with scoped
  access and retention are the correct boundary;
- use one environment-wide encryption key — rejected, cannot erase one
  principal/campaign safely;
- authorize by `principal_hash` in telemetry context — rejected, it is a
  correlation value rather than an ownership credential; and
- let the candidate own registry activation/evaluation/promotion — rejected,
  permits benchmark and evaluator capture.

**Consequences:**

- P0 synthetic qualification can proceed without creating a data-liability
  shortcut.
- Product/learner capture and sealed evaluation stay blocked longer and need
  deletion, broker, key, and role work.
- Some intentional deletions make historical folds unavailable; sparse audit
  receipts explain the absence without retaining content.
- Training remains a future program with a new schema and approval, not a flag
  on operational events.

**Implementation gates:** section 9 checklist and section 10 evidence.

**Follow-ups:** concrete KMS/broker ADR, product-surface notices and consent,
telemetry retention mapping, stable owner-id migration, deletion runbook,
backup restore/erasure test, and future training-data/model-remedy ADR if ever
requested.

## 14. W09 acceptance mapping

| Work-order requirement | Evidence in this package |
|---|---|
| Data inventory by required object family | Sections 3.1 and 3.2 |
| Processing-purpose and consent matrix | Section 4 |
| Retention, deletion, retraction, export, legal hold | Section 5 |
| Principal/tenant access and restricted evaluator role | Section 6 |
| Encryption/key-erasure proposal | Section 7 |
| Required threat model | Section 8 |
| Use-mode decision checklist | Section 9 |
| Proposed D8 ruling and ADR outline | Sections 12 and 13 |
| No training permission inheritance | Sections 3, 4, 9, and D8.5 |
| Strictest learner default | Sections 3, 4, 5, and D8.3 |
| Content versus retained non-content deletion facts | Section 5.2 |
| Real sealed-evaluation boundary | Sections 6, 8, 9, and D8.6 |
| Unresolved questions remain owner decisions | **OWNER** markers and section 12 |

W09 is complete as a review package when the document is internally checked.
It does not make D8 effective. D8 becomes effective only when the owner records
the rulings and the accepted ADR is merged.
