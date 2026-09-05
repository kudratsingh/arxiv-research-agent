# 0079. Register the existing benchmarks, prove parity, and change nothing they mean

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: P0 measurement foundation (P0-WO06)
- **Follows**: [ADR 0005](0005-custom-eval-over-ragas.md) (the eval pipeline is
  ours), [ADR 0070](0070-eval-integrity-provenance.md) (dataset fingerprints and
  rubric version locks), [ADR 0071](0071-eval-statistics-and-gates.md) (paired
  comparison and quantum-derived bands), [ADR 0074](0074-deterministic-groundedness.md)
  (the deterministic check publishes a version and a spec digest)
- **Implements**: [`11-benchmark-data-registry-rfc.md`](../agent-engineering/11-benchmark-data-registry-rfc.md)
  §18 M1/M2, and [`12-p0-work-orders.md`](../agent-engineering/12-p0-work-orders.md)
  §12 (P0-WO06)

## Context

The repository's evaluation inputs are good and completely unregistered. The
twenty research queries live in a Python list; the fifteen guided-reading
scenarios, three personas and eight papers live in another; the recorded
fixtures live in a JSON manifest under `tests/`. Each is versioned only by a
content fingerprint computed at import (ADR 0070), and none of them can answer
the question a campaign needs to answer mechanically: *which exact task,
rubric, label set and grader version produced this score, and could the
candidate see its own answer?*

W02 landed the registry contract — schemas, a role-aware resolver, a lock
generator and a CLI — with no content in it. This ADR is the content, and the
proof that putting it there changed nothing.

Two constraints shaped the result:

- The scripted research tier keeps a committed baseline keyed by query id, and
  `regression_diff` pairs campaigns on query id and order. A registration that
  reordered or renamed anything would silently invalidate a baseline nobody
  would think to re-derive.
- Nothing may claim more evidence than exists. These queries are checked into a
  public repository, so registering them cannot turn them into promotion
  evidence, and no historical result may be relabelled as registry-resolved.

## Decision

Register both benchmarks as immutable objects under `eval_registry/`, keep the
runners reading their own modules, and gate the whole thing on a parity report.

**Two suites, two lanes.** `research-policy-v1@1.0.0` (twenty cases,
`evaluation_lane: research`) and `guided-learning-v1@1.0.0` (fifteen cases,
`evaluation_lane: guided_learning`). Separate task sets, rubric sets, label
sets, split assignments and grader profiles; no shared case id; nothing
aggregates across them.

**One case per old id, at the old id.** `case_id` *is* the query id and the
scenario id, in the module's order. Personas, papers, scripts, expectations and
fixture files each map one-to-one too. `tests/test_benchmark_adapters.py`
asserts membership in both directions and asserts *order* separately, because
membership and order are different claims and only one of them is what
`regression_diff` pairs on.

**Content objects for verbatim material.** W02's registry carries governance
metadata and typed references; it has no inline payload field, and RFC 11 §10
says content is content-addressed and referenced rather than embedded. So the
expected topics, personas, papers, learner scripts and structural expectations
live in `eval_registry/content/<kind>/<id>/<revision>.json` — small
self-verifying envelopes with their own `agent-contract-json/v1` digests,
resolved by `LocalContentStore` under the same role rules the registry
enforces. A task case references them and never inlines them.

**The evaluator overlay is a real boundary, not a naming convention.** For a
research case, the candidate projection is the query text and its task kind.
The expected topics are an evaluator-only content object, referenced from
`evaluator_refs` (which `project_for_role` strips for the candidate) and bound
by digest from a `LabelSet` record. For a learning case, the candidate sees the
scenario input, the persona and the paper; the learner *script* is
evaluator-only, because a tutor that could read the next turn before it
happened would be measured on a different task. The domain and the script kind
are `slice_tags`, also evaluator-side.

**Development only, promotion refused.** Both suites declare
`intended_uses: [development, regression]` and `prohibited_uses: [promotion]`,
and their licence permits the same two. `calibration` and `capability_probe`
are simply not declared, so the resolver refuses them as well. Sealed use fails
at a different layer: a split that is not `development` raises
`RestrictedRegistryUnavailable` until a real access broker exists, so renaming
the split does not launder a public task set into sealed evidence.

**One research task kind, not four.** RFC 11 §6's example declares four
`task_kinds` for this suite. The current runner drives one workflow shape for
all twenty queries, so the suite declares `research.focused_evidence_review`
and nothing else. Declaring the other three would claim task coverage the
benchmark does not have.

**Adapters, then parity.** `load_research_benchmark()` and
`load_learning_benchmark()` rebuild the exact `BenchmarkQuery` and
`LearningScenario` dictionaries the runners read today, from registry content
alone. `build_parity_report()` compares the checked-in tree with the live
modules on ids, order, membership, every registered object's canonical payload,
the rebuilt runner records field by field, and score semantics (each grader
lock against `RESEARCH_RUBRICS` / `LEARNING_RUBRICS` by name, version and
prompt digest). `python -m src.contracts.registry parity` prints the report and
exits non-zero on any mismatch. It is zero on this tree.

**The runners do not move.** `src/eval/**` is untouched. A later ADR chooses
the registry as authoritative; until then the modules are the source of truth
and the registry is a checked, generated view of them. The rollback is to stop
reading the registry.

## Alternatives considered

- **Inline the expected topics and scripts in the task case.** Rejected twice
  over: W02's `TaskCase` has no field for them, and adding one would put the
  reference answer in the same object the candidate resolves. The separation is
  the point.
- **Encode verbatim material in `RubricItem.description`.** The only free-text
  field long enough in W02's schema. Rejected: a reference answer is not a
  rubric item, and conflating them would make the rubric set both the score
  definition and the answer key.
- **Make the registry authoritative now and delete the module constants.**
  Rejected by the work order's rollback rule and by common sense: the parity
  report has to be green across at least one campaign before the modules stop
  being the thing that is true.
- **Slug the case ids into a registry-native namespace** (`research-q01`, …).
  Rejected: the committed scripted-tier baseline and `regression_diff` pair on
  the existing ids, and a mapping table is a thing that goes stale.
- **Backfill old summary rows with registry refs.** Rejected outright. RFC 11
  §18 permits a migration index only where the exact commit and input bytes
  prove the match; no such proof exists for any historical row, so every one of
  them stays `legacy_unresolved`.

## Consequences

- **Positive.** Every evaluation input now resolves by logical id, immutable
  revision and content digest. A campaign lock over the research suite resolves
  twenty cases and twenty-six objects with zero network calls. The candidate
  role cannot reach a label, a grader profile, a split assignment, a suite, a
  learner script or an expectation — proved by tests, not asserted in prose.
  The public suite is mechanically barred from promotion. A drifted expected
  topic, a reordered task set, a missing object, a mislocated file or an
  unsealed edit each produce a named mismatch instead of a silent divergence.
- **Negative.** There are now two places that describe the same benchmark, and
  they can drift. The mitigation is that drift is a test failure:
  `python -m src.contracts.benchmark_adapters` regenerates the tree from the
  modules, and CI fails if the checked-in tree is not exactly what the modules
  build. Editing a benchmark module is now a two-step change.
- **Negative.** Registering the material does not make it better material. The
  expected topics are one curator's hand-authored list with
  `agreement_state: unreviewed`; the registry records that honestly rather than
  claiming an adjudication that never happened. `citation_accuracy` publishes
  no rubric version, so the grader profile's `null_score_policy` says it is
  outside the lock rather than pretending otherwise.
- **Follow-ups.**
  - `ContextRef.kind_matches_ref` (`src/contracts/task_spec.py`) admits only
    `supplied_corpus` / `source_snapshot` / `content_entry` / `artifact` as
    candidate context reference kinds, so a learning case's `learning_persona`
    and `learning_paper` refs cannot yet ride into a compiled `TaskSpec`. The
    compile test passes an empty `candidate_visible_refs` for that lane. W01 or
    W07 should widen the vocabulary or map the kinds.
  - `LabelRecord` has no inline value field, which is why a label binds its
    reference answer by `value_ref` digest and the answer itself lives in a
    content object. If W02 later adds an inline value, these two can merge.
  - Source snapshots are empty for both suites: the research lane retrieves
    live today. Controlled-corpus snapshots are W07's paired-block work.
  - The retention policy for both lanes is `repository-history`, which is
    truthful because no real learner content is registered — every persona and
    transcript here is synthetic. Real learner data stays blocked on D8.3 and
    gets a stricter policy when it is ever registered.
