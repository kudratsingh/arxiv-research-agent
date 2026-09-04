# RFC: immutable run manifest and reproducibility contract

Status: **PROPOSED — IMPLEMENTATION NOT AUTHORIZED**

Snapshot date: **2026-09-04**

Target schema kind/version: `run-manifest` / `1.0.0`

Shared digest profile: `agent-contract-json/v1` (RFC 8785 canonical JSON,
SHA-256 references, and application-level normalized UTC timestamp and fixed-
decimal string fields)

Related planning:

- [`02-target-architecture.md`](02-target-architecture.md) defines the
  platform-level `RunManifest` concept.
- [`03-evaluation-strategy.md`](03-evaluation-strategy.md) requires versioned,
  repeatable comparisons rather than one-off output inspection.
- [`07-first-policy-experiment.md`](07-first-policy-experiment.md) defines the
  approved five-arm research-policy experiment that first exercises this
  contract.
- `08-task-spec-rfc.md`, `10-trajectory-event-rfc.md`, and
  `11-benchmark-data-registry-rfc.md` are companion P0 contracts. They may be
  drafted concurrently; the cross-contract assumptions are explicit in
  section 15.

This RFC specifies the immutable record that answers: **what exactly was
authorized and intended to run?** It does not authorize an experiment, a live
model call, deployment, GPU use, or any other chargeable work.

## 1. Decision summary

Before an agent episode starts, the orchestrator must write and seal one
`RunManifest`. The manifest identifies the task, benchmark item, policy,
effective configuration, code, prompts, models, tools, source mode, random
settings, budget, approval provenance, and environment. Once sealed, its
payload is immutable and content-addressed.

The full manifest is a control-plane object. The policy receives a separately
hashed, least-privilege `policy_runtime_projection`; it never receives sealed
case/split identity, evaluator configuration, approval metadata, private object
locators, or other control-plane-only fields.

Runtime progress does not mutate the manifest. Attempts, status changes,
observations, costs, failures, cancellation, and terminal outcome are recorded
as append-only events and a terminal completion receipt. Resume is permitted
only when the original manifest digest and compatible checkpoint remain
unchanged. A changed task, arm, configuration, model, prompt, tool, code
revision, benchmark snapshot, or budget creates a new run.

The contract has four top-level invariants:

1. **Reproducibility:** every behavior-affecting input is captured by value or
   by an immutable, hash-verified reference.
2. **No silent drift:** resume and aggregation fail closed when identity or
   compatibility fields differ.
3. **No secrets:** manifests contain allowlisted public metadata and opaque
   references, never credentials, raw authorization tokens, environment dumps,
   or unrestricted prompts/user content.
4. **No spend without approval:** a chargeable run is inadmissible unless the
   manifest links an explicit approval whose scope and cap cover that run.
5. **Least privilege is proved:** admission records every input ceiling and the
   deterministic intersection that produced effective permissions and limits.
6. **Evaluation is independent:** grader, label, judge, calibration, and
   blinding configuration is pinned but inaccessible to the candidate policy.

## 2. Scope and non-goals

### In scope

- research-policy experiments and production research episodes;
- stable campaign, episode, run, repeat, and attempt identities;
- task and benchmark references;
- exact policy/arm and effective configuration snapshots;
- provider, model, prompt, tool, source, code, dependency, and environment
  provenance;
- seeds, stochasticity, repeat semantics, and reproducibility classification;
- episode and campaign budget envelopes plus approval provenance;
- output layout, integrity, redaction, schema evolution, and migration;
- lifecycle, failure, cancellation, and resume rules;
- deterministic/no-cost qualification and acceptance criteria.

### Out of scope

- the internal event payload for each agent action; that belongs to
  `TrajectoryEvent`;
- the full normalized task schema; that belongs to `TaskSpec`;
- benchmark ownership, access controls, and split promotion; those belong to
  the benchmark/data registry;
- the scoring implementation or statistical analysis;
- implementation of experiment arms C or E;
- permission to execute any paid stage of the first experiment.

## 3. Current state versus target state

The current eval runner already preserves useful per-query records, but those
records are execution results rather than a pre-run reproducibility contract.

| Concern | Currently captured | Planned by this RFC |
|---|---|---|
| Per-query identity | Random 16-character `run_id`, `query_id`, query text, domain | Globally unique `run_id`; stable campaign/episode/repeat identity; immutable task and benchmark refs |
| Campaign identity | UTC timestamp used as output directory and summary title | Sealed campaign manifest plus immutable protocol, task-set, arm, and approval refs |
| Runtime state | Serialized `ResearchState` excluding messages | State remains an output artifact; manifest captures only the inputs and contracts that selected the trajectory |
| Policy identity | Inferred from process-global settings at run time | Explicit policy selector, policy version, graph digest, arm id, typed policy config, and capability declaration |
| Configuration | Not snapshotted with each query | Allowlisted, fully resolved `Settings` projection with type/schema and content digest |
| Models | Effective values can be inferred only if the environment is preserved | Provider and exact configured model id per actor, routing/fallback rules, sampling parameters, and pricing snapshot |
| Prompts | Not versioned in eval output | Prompt-bundle id, template/code hashes, renderer version, and per-call rendered-prompt hashes in the trajectory |
| Tools and sources | Retrieved papers remain in state, without a sealed tool/source contract | Agent-invocable tool versions, internal component versions, TaskSpec corpus mode, observation-capture mode, shared snapshot refs, and actual provenance |
| Seeds/repeats | No `--repeats`; no seed record | Root/component/provider seed fields, repeat index, replicate group, and an honest determinism classification |
| Cost | Workflow and judge token/cost counters are separated; per-run and campaign caps exist | Pre-run budget envelope, pricing-table ref, actual cost events/receipt, and explicit approval provenance |
| Resume | Presence of `queries/<query_id>.json` means “done”; output directory must use `--resume` | Manifest-digest and checkpoint-compatibility checks; attempts are distinct; repeats never masquerade as resumes |
| Failure/cancel | Error, traceback, exit code, interrupt flush, and budget-stop behavior | Typed lifecycle events, terminal reason codes, safe diagnostic refs, and machine-checkable resumability |
| Code/environment | Not captured in result | Commit, dirty/patch state, dependency/image digests, runtime versions, architecture, and execution class |
| Integrity/redaction | JSON files are written, but no manifest hash or declared redaction policy exists | Canonical encoding, SHA-256 digest, optional signature, allowlist serializer, redaction report, and schema-aware validation |

Existing output must be treated as **legacy observational evidence**, not
retroactively labeled `run-manifest` schema `1.0.0`. A migration may wrap known fields
in a `legacy-import` record, but it must preserve unknown provenance as
`unknown`, never infer it.

## 4. Identity model

The system needs separate identities because “campaign,” “planned episode,”
“run,” “resume attempt,” and “statistical repeat” are different things.

| Identity | Meaning | Stability rule |
|---|---|---|
| `campaign_id` | One approved experimental campaign or production batch | New when protocol, arm set, task set, aggregate cap, or approval scope changes |
| `episode_key` | Deterministic slot within a campaign: task + arm + repeat | Derived from immutable refs; unique within a campaign |
| `replicate_group_id` | All independent repeats of one task/arm condition | Same across repeats; excludes `repeat_index` |
| `run_id` | One logical execution of one episode slot | Stable across safe resumes; new for rerun or changed inputs |
| `attempt_id` | One process attempt to advance a run | New on every initial start or resume |
| `manifest_digest` | SHA-256 of the canonical manifest payload | Changes if and only if the payload changes |

Recommended initial forms:

```text
campaign_id       = camp_<UTC timestamp>_<96 bits random>
run_id            = run_<UUIDv7 or equivalent time-sortable random id>
attempt_id        = att_<UUIDv7 or equivalent time-sortable random id>
replicate_group_id= sha256(campaign_id, task_id, task_revision,
                           task_semantic_digest, arm_digest)
episode_key       = sha256(replicate_group_id, repeat_index)
```

The exact id library is an open implementation choice. Correctness does not
depend on parsing time or metadata out of an id. Digests, not names, establish
equivalence. The semantic task digest is included in repeat grouping as a
defense-in-depth equivalence check. The same stored TaskSpec revision, id, full
digest, and semantic digest must be reused across every arm and repeat for a
selected case; per-repeat recompilation is invalid in the first experiment.

### Repeat, rerun, and resume

- A **repeat** is an independent statistical sample: new `run_id`, new
  `repeat_index`, same `replicate_group_id`.
- A **resume** continues the same logical sample: same `run_id`, same manifest
  digest, new `attempt_id`, same repeat index.
- A **rerun** after a terminal outcome is a new run. It may carry
  `lineage.rerun_of_run_id`, but does not overwrite the old output.
- A changed manifest is always a new run even if the operator uses the same
  output path or query id.

## 5. Manifest lifecycle and storage

### 5.1 Seal before side effects

The orchestrator follows this order:

1. compile or resolve `TaskSpec` and persist a pre-run compilation receipt;
   that receipt is a control-plane audit artifact, not a `TrajectoryEvent`;
2. resolve the campaign lock, registry objects, policy, config, models,
   prompts, tools, source/capture modes, code, dependencies, environment,
   budgets, and authoritative external approval record;
3. compute the admission intersection, validate every reference, and persist
   the admission/approval-verification receipt;
4. build and separately hash the candidate-safe policy runtime projection;
5. serialize the full control-plane manifest payload canonically;
6. compute `manifest_digest` and write `run-manifest.json` plus
   `run-manifest.sha256` atomically;
7. append `run.admitted` as the first trajectory event, carrying the manifest
   and runtime-projection digests;
8. only then allow a tool, model, network, or sandbox side effect.

If sealing fails, no episode starts. A file with a missing/mismatched digest is
not a degraded manifest; it is an invalid run.

### 5.2 Immutable manifest, append-only outcome

`run-manifest.json` has no mutable `status`, accumulated `cost`, or output
fields. Those facts arrive after admission and live in:

- `trajectory.jsonl`: append-only lifecycle and action events;
- `attempts/<attempt-id>.json`: one bounded attempt receipt;
- `completion.json`: one terminal receipt written exactly once;
- `artifacts/`: immutable content-addressed outputs;
- `verification.jsonl` and `scores.json`: evaluation artifacts, separate from
  policy inputs.

This division prevents a finished record from pretending its final facts were
known before execution.

### 5.3 Campaign layout

The first experiment's proposed layout becomes:

```text
outputs/eval/research-policy-v1/<campaign-id>/
  campaign-manifest.json
  campaign-manifest.sha256
  campaign-lock.json
  campaign-lock.sha256
  protocol.md
  approval-ref.json
  arm-configs/{A,B,C,D,E}.json
  task-set.json
  episodes/<query-id>/<repeat>/<arm>/
    run-manifest.json
    run-manifest.sha256
    policy-runtime-projection.json
    policy-runtime-projection.sha256
    trajectory.jsonl
    attempts/<attempt-id>.json
    completion.json
    artifacts/
    verification.jsonl
    scores.json
  human-labels/
  aggregate.json
  scorecard.md
  error-analysis.md
  decision.md
```

The episode directory is a human navigation aid for development campaigns.
Loaders use ids and digests, not path names, as authority. Restricted campaigns
use opaque episode directories rather than query/case ids so filesystem paths
do not reveal sealed membership.

## 6. Normative manifest payload

`run-manifest.json` is an envelope with a content-hashed `payload`:

```json
{
  "schema_kind": "run-manifest",
  "schema_version": "1.0.0",
  "object_revision": 1,
  "payload": {},
  "integrity": {
    "algorithm": "sha256",
    "digest_profile": "agent-contract-json/v1",
    "canonicalization": "RFC8785",
    "payload_sha256": "<64 lowercase hex characters>"
  }
}
```

The digest covers only the canonical `payload`, avoiding a circular self-hash.
The sidecar repeats the envelope digest for filesystem and artifact-store
verification. An optional deployment signature signs the payload digest; a
signature never replaces the hash. `schema_version` describes compatibility of
the manifest format; `object_revision` describes this immutable object's
lineage. Referenced objects carry their own schema versions and revisions.

### 6.1 Required payload sections

| Section | Required content |
|---|---|
| `identity` | Campaign, episode, replicate group, run, repeat, and creation ids/timestamps |
| `lineage` | Optional rerun/fork/import parent refs and reason |
| `compilation` | Pre-run TaskSpec compilation receipt ref and digest |
| `task` | Exact immutable `TaskSpecRef`: schema, revision, full/semantic digests, artifact ref, and effective data class |
| `campaign_lock_ref` | Typed immutable lock that owns suite selection, arm/repeat plan, denominators, seed policy, and campaign approval scope |
| `registry_resolution` | Typed suite/task-set/case/split/rubric/grader/label/source refs; hidden refs remain opaque to the candidate |
| `policy` | Arm, selector, policy version, graph digest, typed config, and capability flags |
| `runtime_config` | Effective allowlisted settings snapshot, settings-schema digest, and snapshot digest |
| `invocation` | Typed caller-only controls such as HITL enable/bypass and checkpoint mode |
| `providers` | Provider protocol, exact configured models per actor, model-resolution mode, sampling, and retry/timeout policy |
| `prompts` | Prompt-bundle/version refs, renderer/code hashes, and isolation mode |
| `tools` | Tool registry snapshot, implementation/protocol/config hashes, permissions, and network policy |
| `sources` | TaskSpec input corpus mode, independent observation-capture mode, and typed shared source snapshot |
| `evaluation` | Candidate-inaccessible grader, judge, prompt, calibration, blinding, failure, and budget configuration |
| `randomness` | Root/component/provider seeds, repeat index, and determinism classification |
| `admission_resolution` | All task/platform/campaign/provider/approval ceilings, permission intersection, resolved limits, and receipt |
| `budgets` | Resolved episode/campaign ceilings and concrete resource quotas, denominated and priced explicitly |
| `approval` | External authoritative record ref, status at seal, scope/cap, and verification receipt—without secrets |
| `code` | Repository, commit, dirty/patch state, and policy/prompt/tool subtree digests |
| `environment` | Execution class, runtime/dependency/image/platform digests and safe feature metadata |
| `outputs` | Output root and artifact layout/schema versions, never final outcome |
| `privacy` | Data class, retention policy ref, redaction policy/version, forbidden-field declaration |
| `policy_runtime_projection` | Separately hashed candidate-safe projection ref, exclusions, schema, and digest |

### 6.2 Representative run manifest

The example below is illustrative. Placeholder digests are not valid values.

```json
{
  "schema_kind": "run-manifest",
  "schema_version": "1.0.0",
  "object_revision": 1,
  "payload": {
    "identity": {
      "campaign_id": "camp_20260904T180000Z_example",
      "episode_key": "sha256:<campaign-task-arm-repeat>",
      "replicate_group_id": "sha256:<campaign-task-arm>",
      "run_id": "run_<uuidv7>",
      "repeat_index": 0,
      "created_at": "2026-09-04T18:00:00Z",
      "created_by": "eval-orchestrator/1.0.0"
    },
    "lineage": null,
    "compilation": {
      "receipt_ref": {
        "kind": "compilation_receipt",
        "id": "task-compilation-example",
        "revision": "1.0.0",
        "digest": "sha256:<task-compilation-receipt-digest>"
      },
      "receipt_locator": "cas://sha256/<task-compilation-receipt-digest>",
      "occurred_before_run_events": true
    },
    "task": {
      "task_spec_id": "tsp_01k4x9q7d4m2n8pv",
      "schema_kind": "task-spec",
      "schema_version": "1.0.0",
      "task_revision": 1,
      "task_id": "research-policy-v1:hallucination-mitigation",
      "full_digest": "sha256:<task-full-content-digest>",
      "semantic_digest": "sha256:<task-semantic-digest>",
      "artifact_ref": {
        "kind": "task_spec_artifact",
        "id": "hallucination-mitigation-task-spec",
        "revision": "1.0.0",
        "digest": "sha256:<task-full-content-digest>"
      },
      "artifact_locator": "cas://sha256/<task-full-content-digest>",
      "effective_data_class": "internal"
    },
    "campaign_lock_ref": {
      "kind": "campaign_lock",
      "id": "research-policy-v1-stage-1-example",
      "revision": "1.0.0",
      "digest": "sha256:<campaign-lock-digest>"
    },
    "campaign_lock_locator": "cas://sha256/<campaign-lock-digest>",
    "registry_resolution": {
      "suite_ref": {
        "kind": "benchmark_suite",
        "id": "research-policy-v1",
        "revision": "1.0.0",
        "digest": "sha256:<suite-digest>"
      },
      "task_set_ref": {
        "kind": "task_set",
        "id": "research-policy-tasks",
        "revision": "1.0.0",
        "digest": "sha256:<task-set-digest>"
      },
      "task_case_ref": {
        "kind": "task_case",
        "id": "hallucination-mitigation",
        "revision": "1.0.0",
        "digest": "sha256:<task-case-digest>"
      },
      "split_assignment_ref": {
        "kind": "split_assignment",
        "id": "research-policy-splits",
        "revision": "1.0.0",
        "digest": "sha256:<split-assignment-digest>"
      },
      "rubric_set_refs": [
        {
          "kind": "rubric_set",
          "id": "research-policy-rubric",
          "revision": "1.0.0",
          "digest": "sha256:<rubric-digest>"
        }
      ],
      "grader_profile_refs": [
        {
          "kind": "grader_profile",
          "id": "current-research-metrics",
          "revision": "1.0.0",
          "digest": "sha256:<grader-profile-digest>"
        }
      ],
      "label_set_refs": [
        {
          "kind": "label_set",
          "id": "research-policy-expected-topics",
          "revision": "1.0.0",
          "digest": "sha256:<label-set-digest>"
        }
      ],
      "source_snapshot_ref": {
        "kind": "source_snapshot",
        "id": "research-policy-v1-controlled-corpus",
        "revision": "1.0.0",
        "digest": "sha256:<source-snapshot-digest>"
      },
      "visibility": {
        "split_assignment": "control-plane-only",
        "rubric_set": "mixed-projected",
        "grader_profile": "evaluator-only",
        "label_set": "evaluator-only",
        "source_snapshot": "task-authorized-content-only"
      },
      "validation_receipt_ref": {
        "kind": "registry_validation_receipt",
        "id": "research-policy-v1-admission-example",
        "revision": "1.0.0",
        "digest": "sha256:<registry-validation-receipt>"
      }
    },
    "policy": {
      "arm_id": "C",
      "selector": "fixed_verify_repair",
      "policy_version": "1.0.0-experimental",
      "graph_sha256": "<sha256>",
      "config_schema": "fixed-verify-repair/1.0.0",
      "config": {
        "max_repairs": 1,
        "allowed_repairs": [
          "retrieve_missing_rubric_evidence",
          "reread_named_sections",
          "replace_or_qualify_claim",
          "remove_unsupported_claim",
          "rewrite_named_section"
        ],
        "reverify_repaired_subject": true
      },
      "capabilities": {
        "supervisor": false,
        "evidence_store": true,
        "fixed_post_synthesis_verifier": true,
        "adaptive_compute": false
      }
    },
    "runtime_config": {
      "settings_schema_sha256": "<sha256>",
      "effective_values": {
        "enable_supervisor": false,
        "enable_evidence_store": true,
        "enable_verifier": false,
        "enable_query_refiner": false,
        "enable_reader_recovery": false,
        "enable_prompt_isolation": true,
        "enable_semantic_scholar": false,
        "enable_prompt_caching": false,
        "use_mock_data": false,
        "max_papers": 10,
        "results_per_query": 5,
        "reader_max_workers": 5,
        "reader_max_chunks_per_paper": 5,
        "reader_max_claims_per_paper": 5,
        "max_iterations": 3,
        "max_loop_iterations": 20,
        "min_quality_score": 0.75,
        "anthropic_max_retries": 4,
        "anthropic_timeout_sec": 120.0,
        "max_cost_usd": "2.000000"
      },
      "effective_values_sha256": "<sha256>"
    },
    "invocation": {
      "enable_hitl": false,
      "hitl_bypass": true,
      "hitl_bypass_reason": "unattended-evaluation",
      "checkpoint_mode": "persistent"
    },
    "providers": {
      "llm": {
        "provider": "anthropic",
        "api_protocol_version": "<resolved-before-run>",
        "model_resolution": "exact-id-required",
        "routes": {
          "default": "<exact-approved-model-id>",
          "planner": "<same-exact-model-id>",
          "reader": "<same-exact-model-id>",
          "synthesizer": "<same-exact-model-id>",
          "critic": "<same-exact-model-id>",
          "verifier": "<same-exact-model-id>",
          "supervisor": "<same-exact-model-id>"
        },
        "sampling": {
          "temperature": 0.3,
          "provider_seed": null
        },
        "credential": {
          "present": true,
          "binding_ref": "credential-binding://anthropic/eval",
          "value_recorded": false,
          "fingerprint_recorded": false
        }
      },
      "pricing": {
        "currency": "USD",
        "table_ref": "src/observability/costs.py",
        "table_sha256": "<sha256>",
        "prices_last_verified": "2026-08-20"
      }
    },
    "prompts": {
      "bundle_id": "research-prompts",
      "bundle_version": "<commit-or-release>",
      "bundle_sha256": "<sha256>",
      "renderer_sha256": "<sha256>",
      "prompt_isolation": "enabled",
      "raw_rendered_prompts_in_manifest": false
    },
    "tools": {
      "registry_version": "1.0.0",
      "registry_sha256": "<sha256>",
      "agent_invocable": ["arxiv_search", "pdf_reader"],
      "internal_components": ["pdf_parser", "chunk_ranker"],
      "denied": [
        "general_shell",
        "repository_write",
        "external_publish",
        "deploy",
        "send_message"
      ],
      "network_policy": "arxiv-only",
      "tool_result_capture": "content-addressed-redacted"
    },
    "sources": {
      "input_corpus_mode": "snapshot",
      "observation_capture_mode": "recorded",
      "source_policy_version": "1.0.0",
      "source_policy_sha256": "<sha256>",
      "source_snapshot_ref": {
        "kind": "source_snapshot",
        "id": "research-policy-v1-controlled-corpus",
        "revision": "1.0.0",
        "digest": "sha256:<source-snapshot-digest>"
      },
      "live_access_allowed": false
    },
    "evaluation": {
      "candidate_visibility": "control-plane-only",
      "grader_profile_refs": [
        {
          "kind": "grader_profile",
          "id": "current-research-metrics",
          "revision": "1.0.0",
          "digest": "sha256:<grader-profile-digest>"
        }
      ],
      "judge_routes": {
        "citation_accuracy": "<exact-approved-judge-model-id>",
        "completeness": "<exact-approved-judge-model-id>",
        "faithfulness": "<exact-approved-judge-model-id>"
      },
      "judge_prompt_bundle_ref": {
        "kind": "prompt_bundle",
        "id": "research-eval-judges",
        "revision": "1.0.0",
        "digest": "sha256:<judge-prompt-bundle-digest>"
      },
      "calibration_ref": {
        "kind": "calibration_set",
        "id": "research-judge-calibration",
        "revision": "1.0.0",
        "digest": "sha256:<judge-calibration-digest>"
      },
      "blinding_policy": "arm-and-candidate-identity-masked",
      "ordering_policy": "campaign-predeclared",
      "sampling": {
        "temperature": 0.0,
        "provider_seed": null
      },
      "timeout_sec": 120.0,
      "max_retries": 4,
      "null_score_policy": "retain-and-report-denominator",
      "budget": {
        "currency": "USD",
        "cost_usd_max": "0.500000",
        "model_calls_max": 4
      }
    },
    "randomness": {
      "repeat_index": 0,
      "root_seed": 731245,
      "derivation": "hmac-sha256(root_seed, component-name)",
      "component_seeds_ref": {
        "kind": "seed_map",
        "id": "episode-component-seeds",
        "revision": "1.0.0",
        "digest": "sha256:<component-seed-map-digest>"
      },
      "provider_seed": null,
      "determinism_class": "recorded-observations-stochastic-model"
    },
    "admission_resolution": {
      "resolver_version": "admission-controller/1.0.0",
      "input_workflow_ceilings": {
        "task_workflow_cost_usd": "2.000000",
        "platform_workflow_cost_usd": "2.000000",
        "campaign_workflow_allocation_usd": "1.500000",
        "provider_workflow_cost_usd": "2.000000",
        "approval_workflow_allocation_usd": "1.500000"
      },
      "resolved_workflow_cost_usd": "1.500000",
      "cost_derivation": "minimum-of-all-input-ceilings",
      "resolved_limits": {
        "hard_timeout_sec": 600,
        "model_calls_max": 40,
        "tool_calls_max": 50,
        "autonomy_tier_max": "A1",
        "external_side_effects": "none"
      },
      "task_permissions_narrowed_or_equal": true,
      "receipt_ref": {
        "kind": "admission_receipt",
        "id": "episode-admission-example",
        "revision": "1.0.0",
        "digest": "sha256:<admission-receipt-digest>"
      }
    },
    "budgets": {
      "episode": {
        "currency": "USD",
        "workflow_cost_usd_max": "1.500000",
        "judge_cost_usd_max": "0.500000",
        "total_cost_usd_max": "2.000000",
        "wall_time_sec_max": 600,
        "workflow_model_calls_max": 40,
        "judge_model_calls_max": 4,
        "tool_calls_max": 50
      },
      "campaign": {
        "currency": "USD",
        "total_cost_usd_max": "10.000000",
        "enforcement": "between-episodes-with-in-flight-overshoot-risk"
      }
    },
    "approval": {
      "required": true,
      "status_at_seal": "approved",
      "approval_id": "approval_<opaque-id>",
      "record_ref": "approval-record://<opaque-id>",
      "record_sha256": "<approval-record-digest>",
      "authoritative_source": "external-approval-record",
      "scope": {
        "campaign_id": "camp_20260904T180000Z_example",
        "providers": ["anthropic"],
        "stages": ["calibration-smoke"],
        "total_cost_usd_max": "10.000000",
        "episode_allocation_usd_max": "2.000000",
        "workflow_allocation_usd_max": "1.500000",
        "judge_allocation_usd_max": "0.500000"
      },
      "approved_by": "owner",
      "approved_at": "2026-09-04T17:00:00Z",
      "expires_at": "2026-09-05T17:00:00Z",
      "admission_verification_receipt_ref": "cas://sha256/<approval-verification-receipt>",
      "resume_requires_fresh_verification_receipt": true,
      "secret_material_recorded": false
    },
    "code": {
      "repository": "kudratsingh/arxiv-research-agent",
      "commit_sha": "<40-hex-commit>",
      "worktree_state": "clean",
      "patch_sha256": null,
      "promotion_eligible": true
    },
    "environment": {
      "class": "local-eval",
      "python_version": "<major.minor.patch>",
      "platform": "<safe-os-and-architecture>",
      "dependency_lock_ref": "requirements-lock.txt",
      "dependency_lock_sha256": "<sha256>",
      "container_image_digest": null,
      "locale": "<locale>",
      "timezone": "UTC"
    },
    "outputs": {
      "root": "episodes/<opaque-episode-id>",
      "artifact_schema_version": "1.0.0",
      "trajectory_schema_version": "1.0.0",
      "verification_schema_version": "1.0.0"
    },
    "privacy": {
      "task_data_class": "internal",
      "registry_object_classification": "internal",
      "retention_policy_ref": {
        "kind": "retention_policy",
        "id": "eval-default",
        "revision": "1.0.0",
        "digest": "sha256:<retention-policy-digest>"
      },
      "redaction_policy_version": "1.0.0",
      "raw_secrets_allowed": false,
      "raw_environment_allowed": false,
      "chain_of_thought_allowed": false
    },
    "policy_runtime_projection": {
      "schema_kind": "policy-runtime-projection",
      "schema_version": "1.0.0",
      "artifact_ref": {
        "kind": "policy_runtime_projection",
        "id": "episode-policy-runtime-projection",
        "revision": "1.0.0",
        "digest": "sha256:<runtime-projection-digest>"
      },
      "artifact_locator": "cas://sha256/<runtime-projection-digest>",
      "excluded_classes": [
        "sealed-case-and-split-identity",
        "evaluator-and-label-refs",
        "approval-metadata",
        "private-object-locators",
        "hidden-rubric-content"
      ]
    }
  },
  "integrity": {
    "algorithm": "sha256",
    "digest_profile": "agent-contract-json/v1",
    "canonicalization": "RFC8785",
    "payload_sha256": "<sha256>"
  }
}
```

## 7. Five-arm campaign configuration

The campaign manifest owns common settings once and references five immutable
arm snapshots. Each episode manifest embeds or hash-references the resolved arm
and repeats the effective values that actually govern that episode.

### 7.1 Common frozen values

```json
{
  "model_routes": "one exact then-current approved model id for every actor",
  "temperature": 0.3,
  "max_papers": 10,
  "results_per_query": 5,
  "reader_max_workers": 5,
  "reader_max_chunks_per_paper": 5,
  "reader_max_claims_per_paper": 5,
  "max_iterations": 3,
  "max_loop_iterations": 20,
  "min_quality_score": 0.75,
  "anthropic_max_retries": 4,
  "anthropic_timeout_sec": 120.0,
  "query_refiner": false,
  "reader_recovery": false,
  "prompt_isolation": true,
  "semantic_scholar": false,
  "prompt_caching": false,
  "mock_data": false,
  "invocation": {
    "enable_hitl": false,
    "hitl_bypass": true,
    "hitl_bypass_reason": "unattended-evaluation"
  },
  "input_corpus_mode": "snapshot",
  "observation_capture_mode": "recorded",
  "source_snapshot_ref": "research-policy-v1-controlled-corpus@1.0.0"
}
```

`max_cost_usd` and the campaign cap are deliberately absent from this example:
their exact values must be calculated and explicitly approved immediately
before each paid stage. The episode manifest records the approved resolved
numbers; placeholders are inadmissible.

### 7.2 Arm snapshots

| Arm | Selector | Supervisor | Evidence | Existing verifier flag | Additional structural policy |
|---|---|---:|---:|---:|---|
| A | `fixed` | false | false | false | None |
| B | `fixed_evidence` | false | true | false | None |
| C | `fixed_verify_repair` | false | true | false | Fixed verifier stage, one targeted repair, re-verification |
| D | `supervisor_verified` | true | true | true | Existing strict supervisor action space |
| E | `adaptive_verified` | true | true | true | Difficulty router, T0–T2, candidate lineage, listwise selection, marginal stop |

Arm C must not be represented as `enable_verifier=true` with the fixed graph;
the current flag is a no-op there. The arm validator must require a graph
digest containing the new `fixed_post_synthesis_verifier` stage. Arm E must
require typed compute tiers and routing evidence, not merely the supervisor
flags.

An arm snapshot has this minimum shape:

```json
{
  "arm_id": "E",
  "selector": "adaptive_verified",
  "policy_version": "1.0.0-experimental",
  "graph_sha256": "<sha256>",
  "runtime_flags": {
    "enable_supervisor": true,
    "enable_evidence_store": true,
    "enable_verifier": true,
    "enable_query_refiner": false,
    "enable_reader_recovery": false
  },
  "policy_config": {
    "allowed_tiers": ["T0", "T1", "T2"],
    "default_tier": "T1",
    "difficulty_features_version": "1.0.0",
    "max_targeted_repairs": 1,
    "max_branches": "<bounded-value-set-before-run>",
    "selection": "listwise",
    "marginal_stop_policy_version": "1.0.0"
  }
}
```

Every arm snapshot receives its own digest. Stage 0 fails if any pair of arm
digests is equal, if a selector/flag combination is invalid, or if the graph
does not expose the capabilities the snapshot claims. Arm E's allowed tiers,
router, and hard bounds are manifest inputs; the tier actually selected,
difficulty features, branch decisions, and marginal-stop evidence are runtime
facts recorded as trajectory events and completion diagnostics.

`USE_MOCK_DATA=false` does not by itself create a controlled comparison: in the
current implementation it permits live arXiv retrieval. The controlled campaign
must route every paired arm through the same typed registry `SourceSnapshot`
and fail if its digest differs. Stage 4 is a separate campaign with
`input_corpus_mode=live`; it must never be aggregated into the snapshot result.

## 8. Provider, prompt, tool, and source snapshots

### 8.1 Providers and models

The configured model id must be exact enough to make drift visible. If a
provider accepts only a moving alias, record `model_resolution="alias"`, the
alias, and each observed response model id in trajectory events and the
completion receipt. Such a run has weaker reproducibility and cannot be called
bitwise repeatable.

Record for every actor:

- provider and API/protocol version;
- exact configured model id and fallback behavior;
- temperature, top-p/top-k where supported, maximum output tokens, and seed
  where supported;
- timeout and retry policy;
- prompt-cache behavior;
- pricing-table digest and verification date.

Never record an API key, bearer token, endpoint credential, secret hash, or
request header. An opaque credential-binding reference may prove that admission
checked for a configured credential without making the credential portable.

### 8.2 Prompts

The bundle snapshot includes all system templates, structured-output schemas,
prompt-rendering code, safety wrappers, and prompt-isolation rules. Since this
repository currently keeps prompts and rendering logic in code, an initial
bundle builder may hash the allowlisted source entrypoints plus their declared
dependencies.

The manifest does not contain rendered prompts. Each call event stores a
rendered-prompt hash and, when retention policy permits, a reference to a
redacted/encrypted artifact. This avoids copying private task text, source
documents, or hidden evaluator labels into the control-plane manifest.

### 8.3 Tools

Agent-invocable tool ids must use the exact TaskSpec vocabulary. For the first
experiment those are `arxiv_search` and `pdf_reader`. Parser, chunker, ranker,
cache, and HTTP-session implementations are internal components of those tools,
not extra permissions granted to the policy. Each snapshot records:

- logical name and registry version;
- implementation digest and dependency/protocol version;
- typed, allowlisted behavior configuration;
- network, filesystem, CPU, memory, and wall-time permissions;
- cache mode and cache namespace/version;
- result-recording and redaction behavior.

A generic environment dump is forbidden. Tool secrets use external bindings in
the same way as model credentials.

### 8.4 Corpus and observation modes

Two independent fields prevent “recorded” from being confused with “snapshot”:

| Field | Vocabulary | Meaning |
|---|---|---|
| `input_corpus_mode` | `live`, `snapshot`, `supplied`, `curated` | Exact TaskSpec source boundary |
| `observation_capture_mode` | `none`, `recorded` | Whether actual tool requests/results are retained for replay |

`input_corpus_mode=snapshot` requires a typed registry `SourceSnapshot` ref and
strong input replay; model stochasticity may remain. `live` provides only time-
bounded provenance even when its observations are recorded. `supplied` and
`curated` resolve the immutable refs declared by TaskSpec.

The controlled comparison uses the same `SourceSnapshot` revision/digest for
every arm within a paired block. The Stage 4 live-retrieval sweep is a separate
campaign and aggregate. A live episode records access timestamps and
source/result hashes in events; it must not fabricate a pre-run corpus digest.

### 8.5 Independent evaluation configuration

The full control-plane manifest pins evaluator configuration separately from
workflow policy:

- typed grader-profile, rubric, label, and calibration refs with revisions and
  digests;
- exact judge provider/model routes and resolution mode;
- judge prompt bundle, decoding, retry, timeout, ordering, and blinding;
- abstention, null-score, failure, and denominator treatment;
- separate judge call and fixed-decimal cost ceilings.

These fields never enter the policy runtime projection. Actual judge model ids,
costs, failures, and result refs are outcome events/receipts, not manifest
mutations.

### 8.6 Policy runtime projection

The orchestrator derives a separately canonicalized and hashed
`policy-runtime-projection/1.0.0`. It contains only the agent-safe TaskSpec
projection, effective allowed tools/source content, policy/configuration,
workflow model routes/prompts, resource limits, and non-secret run ids required
for execution. It excludes:

- sealed task-case and split identity;
- label, hidden rubric, grader, calibration, and judge configuration;
- approval ids, approver metadata, campaign balance, and pricing internals;
- private locators, access-broker metadata, credentials, and secret bindings.

Only the control plane reads the full manifest. `run.admitted` records both
digests so an auditor can prove which least-privilege projection was executed.

## 9. Randomness and reproducibility

A seed field does not guarantee determinism. The manifest records the actual
sources of randomness and classifies the run honestly.

Initial classes:

- `deterministic-local`: all code paths and tools are deterministic under the
  captured environment;
- `snapshot-input-seeded-model`: inputs use a registry snapshot and the provider honors a
  recorded seed, but provider implementation drift may remain;
- `recorded-observations-stochastic-model`: tool observations are replayable,
  but the provider exposes no deterministic seed;
- `live-input-stochastic-model`: both retrieval and generation may vary.

The orchestrator creates a root seed for each repeat and derives component
seeds by a documented function. It must record `null` where an API has no seed
control. Repeats remain independent runs even when the same nominal seed is
used to diagnose nondeterminism.

## 10. Budget and approval contract

### 10.1 Budget fields

The manifest distinguishes:

- workflow model spend;
- evaluator/judge spend;
- paid tool or data-source spend;
- sandbox/GPU/cloud allocation where applicable;
- episode wall time, model/tool call counts, tokens, and branch/repair limits;
- campaign aggregate cap and enforcement precision.

`admission_resolution` records the task, platform, campaign allocation,
provider, and approval ceilings individually, then the fixed-decimal resolved
minimum and resolver version. It also proves that effective source, tool,
autonomy, timeout, model-call, and tool-call permissions are equal to or
narrower than TaskSpec. The `budgets` section is the resolved enforcement view;
it cannot replace the derivation evidence.

Current `--max-budget-usd` enforcement occurs between queries and can overshoot
by the in-flight query. The manifest must state that enforcement behavior. A
future pre-call reservation system may claim a stronger bound only after it is
implemented and tested.

### 10.2 Approval admission rule

The admission validator computes `chargeable=true` if the plan includes any
real Anthropic/provider call, live LLM evaluation, paid API, GPU allocation,
cloud provisioning, deployment, or other metered external resource.

- If `chargeable=false`, `approval.status_at_seal` may be `not_required` with a reason
  such as `mocked-local-stage-0`.
- If `chargeable=true`, only `approval.status_at_seal=approved` is runnable.
- `pending`, `expired`, `revoked`, missing, cap-mismatched, stage-mismatched,
  provider-mismatched, or campaign-mismatched approval fails admission before
  credentials are read or side effects begin.
- Possession of an API key is never approval.
- An earlier stage's approval does not automatically authorize a later stage or
  a higher cap.

Approval metadata is intentionally sparse: opaque approval id/reference,
scope, monetary/resource cap, stage, approver alias, approval time, expiry, and
revocation status. It contains no secret, payment instrument, credential, or
private approval conversation. The external approval record is authoritative;
`status_at_seal` is historical evidence, not a permanent claim. Initial
admission stores a verification receipt in the manifest. Every resume appends a
fresh verification receipt to the attempt record before credentials or side
effects are available.

## 11. Lifecycle, failure, cancellation, and resume

### 11.1 Event states

The first lifecycle vocabulary is:

```text
run.admitted -> attempt_started -> running
running -> attempt_interrupted | attempt_failed | cancel_requested
running -> budget_stop_requested
attempt_interrupted | attempt_failed -> attempt_started  (safe resume only)
cancel_requested -> cancelled
budget_stop_requested -> budget_stopped
running -> succeeded
attempt_failed -> failed  (orchestrator declares no safe resume)
```

`succeeded`, `failed`, `cancelled`, and `budget_stopped` are terminal receipt
statuses. A process crash with no terminal receipt is `interrupted/unknown`,
not success and not automatically safe to resume.

An episode-level `budget_stopped` receipt is terminal and cannot resume. A
campaign stopped between episodes may continue only under the same immutable
campaign lock, monetary cap, and still-valid approval, using the remaining
balance. Raising a cap or expanding approval scope creates a new campaign with
lineage to the old one; it may reference prior completed episodes but does not
rewrite or re-home them.

### 11.2 Typed reason codes

At minimum support:

- `provider_error`, `tool_error`, `schema_error`, `policy_error`;
- `timeout`, `operator_interrupt`, `infrastructure_lost`;
- `episode_budget_exhausted`, `campaign_budget_exhausted`;
- `approval_missing`, `approval_expired`, `approval_revoked`;
- `manifest_mismatch`, `checkpoint_incompatible`, `integrity_failure`;
- `privacy_or_security_stop`, `benchmark_contamination`;
- `no_report_produced`, `judge_partial_failure`, `unknown`.

Diagnostics are bounded, redacted, and referenced as artifacts. Raw tracebacks
may contain paths, query content, headers, or provider bodies, so they do not
belong in the manifest and require the same redaction policy as trajectories.

### 11.3 Resume preconditions

Resume is allowed only when all are true:

1. no terminal completion receipt exists;
2. `run_id`, `episode_key`, and manifest digest match;
3. the checkpoint declares the same task, policy, graph, config, prompt, model,
   tool, source-snapshot, and code compatibility digests;
4. a fresh authoritative approval-verification receipt proves the original
   scope remains valid and has sufficient unspent balance;
5. episode and campaign budgets retain headroom;
6. no privacy, security, label-exposure, or integrity stop occurred;
7. the policy declares the interrupted boundary idempotent or provides a
   reconciliation action for ambiguous side effects.

Resume appends a new attempt. It never deletes a failed attempt, resets
accumulated cost, changes a seed, or produces a statistical repeat. If any
precondition fails, the operator must create a new run with explicit lineage.

## 12. Schema, redaction, and integrity

### 12.1 Versioning

Use semantic versions for the manifest schema:

- patch: clarifications or validator fixes that do not change accepted data;
- minor: additive optional fields that old readers may ignore;
- major: changed meaning, required fields, or incompatible validation.

Readers must reject an unknown major version. They may accept a newer minor
only when all unknown fields are preserved during read/write and no policy
decision depends on silently ignored content.

Policy, TaskSpec, benchmark, trajectory, verification, prompt bundle, tool
registry, and artifact schemas version independently and are referenced with
both version and digest.

### 12.2 Allowlist serialization

Build the manifest from typed domain objects, never from `os.environ`,
`Settings.model_dump()` without exclusions, provider request objects, or raw
process metadata. The serializer has an explicit allowlist. Validation rejects:

- known secret field names (`*_api_key`, token, password, cookie, authorization,
  private key, session secret);
- inline credential-like values and request headers;
- raw `.env` data or unrestricted environment maps;
- raw chain-of-thought or hidden evaluator labels;
- unbounded user text or source documents where an immutable ref is required;
- absolute private filesystem paths unless a redaction policy explicitly maps
  them to a safe logical path.

Do not hash secrets into the manifest. Hashes of low-entropy credentials can be
attacked and create a stable cross-run identifier. Record only an opaque
binding reference and boolean admission result.

### 12.3 Canonicalization and atomicity

- JSON uses the shared `agent-contract-json/v1` digest profile: UTF-8 RFC 8785
  canonicalization plus application-level normalized UTC timestamp and fixed-
  decimal string fields.
- Digests are lowercase SHA-256 with an algorithm prefix at reference sites.
- Writers use create-new/atomic-rename semantics and refuse overwrite.
- Readers verify envelope, payload digest, sidecar digest, referenced artifact
  digests, and schema before trusting a field.
- Aggregate reports carry the set/Merkle root of included manifest digests so
  omitted or substituted episodes are detectable.
- Optional signing keys live in a secret manager; the manifest stores only key
  id, algorithm, and signature.

## 13. Migration and backward compatibility

### 13.1 Legacy eval import

A no-cost importer may read current `queries/<query-id>.json` records and emit
an adjacent `legacy-import.json` with:

- known ids, query metadata, state/result refs, costs, metrics, elapsed time,
  error, and source file hash;
- `provenance_completeness="partial"`;
- missing policy/config/model/prompt/tool/approval/code/environment fields as
  `unknown`;
- `promotion_eligible=false`.

It must not manufacture a clean commit, exact settings, approval, seed, or
model route from today's checkout. The original record stays unchanged.

### 13.2 Schema migration

Migration is pure and append-only:

```text
old manifest -> validate old digest -> transform -> new manifest
```

The new manifest receives a new digest and
`lineage.migrated_from_manifest_digest`; the old file remains readable. Golden
fixtures test every supported version hop. Aggregates may mix schema minors
only after normalizing to a declared analysis schema; they do not mix unknown
majors.

## 14. No-cost validation plan

All items below run with mocks, recorded fixtures, or local deterministic code
and require no provider calls.

### Schema and canonicalization

- valid minimal research and production manifests pass;
- every required section and enum is enforced;
- unknown major versions fail;
- key order and whitespace do not change a payload digest;
- one behavior field changed by one value changes the digest;
- numeric and timestamp canonicalization has golden fixtures.

### Identity and arm isolation

- episode keys are stable for identical inputs and differ by task, arm, or
  repeat index;
- resume preserves `run_id` and creates a new `attempt_id`;
- rerun/repeat creates a new `run_id`;
- all five arm snapshots produce distinct digests;
- Arm C rejects the current fixed graph with only `enable_verifier=true`;
- Arm E rejects missing tier/router/selection/stop configuration.

### Configuration and provenance

- the effective config snapshot is generated after validation/default
  resolution, not from raw env strings;
- every model route resolves to the campaign's exact id in the first experiment;
- prompt/tool/code/dependency hash changes invalidate resume;
- dirty worktrees record a patch digest and are not promotion-eligible;
- frozen, recorded, and live source modes enforce different required fields.

### Cost and approval safety

- a dry-run five-arm matrix makes zero network/provider calls;
- a chargeable plan with missing/pending/expired/revoked/wrong-scope approval is
  rejected before credential access;
- `not_required` is valid only when the computed maximum external spend is
  zero;
- episode and campaign caps are positive, denominated, and within approval;
- resume includes previously accumulated workflow and judge spend;
- campaign enforcement describes the current in-flight overshoot risk.

### Privacy and integrity

- fixtures containing API keys, bearer tokens, cookies, `.env` maps, chain-of-
  thought, private paths, or hidden labels fail serialization;
- credential fingerprints/hashes are rejected alongside raw credentials;
- tampering with payload, sidecar, or referenced snapshot is detected;
- a manifest cannot be overwritten after sealing;
- diagnostic artifacts pass bounded redaction tests;
- aggregate membership validation detects a missing or substituted episode.

### Failure and recovery

- crash after manifest seal but before `attempt_started` remains an admitted,
  resumable run;
- crash during an attempt appends an interruption without mutating manifest;
- terminal completion blocks resume;
- manifest/checkpoint mismatch blocks resume;
- cancellation and budget stop retain partial artifacts and accumulated spend;
- atomic-write fault injection leaves either the old complete artifact or the
  new complete artifact, never a trusted partial file.

## 15. Cross-RFC assumptions

These assumptions allow the P0 RFCs to proceed concurrently. If a companion
RFC chooses a different contract, resolve it before implementation rather than
silently adapting one side.

### TaskSpec (`08`)

- exposes `task_spec_id`, semantic version, canonical payload digest, immutable
  artifact ref, and data classification;
- does not embed secrets or unrestricted raw user content in the manifest;
- carries allowed tools, denied actions, source/freshness requirements,
  deliverables, acceptance checks, autonomy tier, latency, and spend ceiling;
- its spend ceiling may be stricter than the run approval and therefore wins.

### TrajectoryEvent (`10`)

- provides append-only lifecycle and action events keyed by `run_id` and
  `attempt_id`;
- begins with `admitted`/`attempt_started` carrying the manifest digest;
- records actual model ids, prompt hashes, tool observations, cost deltas,
  artifact refs, reason codes, and redaction metadata;
- stores no chain-of-thought by default and never mutates the manifest.

### Benchmark/data registry (`11`)

- exposes dataset id/version/snapshot digest, split, item id/digest, label-access
  policy, task-slice metadata, and retention/classification refs;
- checked-in `research-policy-v1` is a visible development set, not sealed;
- validation/canary labels remain evaluator-only and are inaccessible to the
  candidate policy;
- registry snapshots are immutable; changing one creates a new version/digest.

### Evaluation runner

- campaign orchestration owns arm/repeat order and writes manifests before
  invoking the current per-query runner or its replacement;
- workflow and judge costs remain separate;
- failed/null scores remain in denominators and artifacts according to the
  approved analysis plan;
- a repeat is never implemented with `--resume`.

## 16. Implementation sequence

No step below authorizes arms C/E or a paid campaign.

1. Define typed `RunManifestV1`, canonical serializer, digest verifier, and
   secret/redaction validator.
2. Add policy, prompt, tool, settings, code, dependency, environment, TaskSpec,
   and benchmark snapshot adapters.
3. Add campaign/episode identity derivation and atomic output writer.
4. Add approval admission interface with a fake/local approval backend for
   tests; keep real approval records external.
5. Add lifecycle events, attempt receipts, terminal receipt, and resume
   compatibility validator.
6. Add five-arm dry-run compilation and structural arm validators.
7. Add legacy import/migration utilities and golden fixtures.
8. Integrate with eval orchestration behind a flag, then run Stage 0 only.
9. Write an ADR before selecting final policy names, ids, storage backend, or
   signing approach.

## 17. Acceptance criteria

The RFC is implemented when all of the following are true:

- every new research episode seals a valid manifest before side effects;
- every behavior-affecting input is captured by value or immutable verified
  reference, and missing provenance is explicit;
- all five experiment arms compile into mechanically distinct, valid manifests;
- the runner refuses structural impostors for arms C and E;
- repeats, reruns, resumes, and attempts have the identity semantics in section
  4;
- resume fails closed on manifest, checkpoint, approval, cost, or integrity
  mismatch;
- chargeable admission cannot begin with absent or insufficient approval;
- secrets, raw env dumps, hidden labels, chain-of-thought, and unrestricted
  private content cannot enter a manifest;
- workflow and judge budgets/costs remain separately accountable;
- interrupted, failed, cancelled, and budget-stopped runs preserve partial
  artifacts without rewriting the manifest;
- deterministic tests prove canonicalization, integrity, redaction, migration,
  arm distinction, and crash-safe writes;
- Stage 0 emits a complete five-arm dry-run matrix with zero provider calls;
- repository docs and an ADR explain operator workflow and compatibility;
- no policy promotion or paid-stage claim is made from manifest implementation
  alone.

## 18. Open decisions

These decisions are intentionally left for the implementation ADR or companion
RFC reconciliation:

1. UUIDv7 versus another sortable opaque id implementation.
2. Pydantic JSON Schema versus another typed schema/validation library.
3. Filesystem content-addressed storage first versus an artifact-store adapter.
4. Whether signatures are required for local eval, CI, production, or only
   promotion evidence.
5. The exact approval-record system and revocation check interface.
6. Which environment features are necessary for reproducibility without
   collecting host-identifying data.
7. Retention and encryption rules for task, prompt, source, and diagnostic
   artifacts by data class.
8. Whether promotable campaigns require a clean Git worktree or may accept a
   reviewed patch bundle digest.
9. Exact bounded values for Arm E branches/calls and all paid cost caps.
10. How long moving provider aliases remain acceptable before exact immutable
    model revisions become a promotion requirement.

Approved decisions D1–D3 are not reopened here: claim support/evidence
completeness remains the first target, the constrained scorecard remains the
decision model, and the fixed graph remains control/fallback until repeated
evidence supports a later promotion.
