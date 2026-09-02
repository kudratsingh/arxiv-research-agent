# The honesty inventory

Gate W1's row:

> Honesty inventory: provenance rules, no-inferred-as-fact, evidence-quoting
> judge, no-mastery-% gate | named tests, all green | W02, W04, W07, W14

**Resolved.** Four items, four owning work orders, and the named tests below.
All run in ordinary `pytest -m "not e2e"` and `npm test`, both of which are
per-PR CI jobs. Python counts are `--collect-only` on `3ccb650` with the repo
venv; web counts are quoted from the producing PR body.

The mapping is not one item per work order — WO-W02 owns two of the four and
WO-W07 reinforces a third at the database layer — so it is written out rather
than implied.

---

## 1. Provenance rules — **WO-W02** (#134, `19e8b17`, ADR 0058)

`tests/test_learner_profile_store.py` — **60 tests**. The classes PR #134's
criteria table names:

| Class | Rule |
|---|---|
| `TestProvenanceIsNonNullable` (`:123`) | `SkillEntry.source` has no default and no `None` member; a stored row missing it raises `ProvenanceError` on read rather than defaulting |
| `TestInferredIsCapped` (`:172`) | `inferred` above 0.6 rejected |
| `TestConfidenceOneIsReservedForDeclared` (`:199`) | `confidence = 1.0` is `declared`-only |
| `TestDeclarationsSurviveInference` (`:261`) | a `declared` entry is never overwritten by an inference; the contradiction is stored as a second entry |
| `TestSkillCapNeverDropsADeclaration` (`:324`) | eviction takes guesses, then assessments, **never** a declaration; refuses the write if only declarations remain |
| `TestProvenanceIsEnforcedAtRest` (`:724`) | the same rules as `CHECK` constraints, verified against a real Postgres 16 by direct `INSERT` |
| `test_the_edit_surface_cannot_forge_provenance` (`:296`) | the only HTTP path refuses a non-`declared` claim |

Three independent layers — the type, the merge, the table — so no single
missed code path can produce a claim that lies about its origin (PR #134).

## 2. No inferred-as-fact — **WO-W02**, reinforced by **WO-W07** (#133, `5d53514`)

**In the prompt** (the claim as §6 words it):
`tests/test_learner_profile_serializer.py` — **19 tests**.

- `TestNoInferredAsFact` (`:122`) — parametrized over **both** positions of
  `enable_prompt_isolation`, so the property does not depend on that flag.
- `test_a_contradiction_shows_both_claims_with_their_provenance` (`:154`)
- `test_every_claim_carries_its_provenance_marker` (`:166`)
- `TestLearnerTextIsIsolated` (`:230`) and
  `test_a_learner_cannot_forge_a_provenance_marker` (`:260`) — adversarial
  `profile_note` arrives isolation-wrapped, following the
  `tests/test_reader_isolation.py` pattern.

**In the ledger** (WO-W07's half — an event may not assert what nothing backs):
`tests/test_progress_events.py` — **76 tests**.

- `TestEvidenceAtTheWriteBoundary` (`:196`) —
  `test_an_assessment_without_evidence_is_refused`,
  `test_a_blank_evidence_ref_is_not_evidence`,
  `test_the_ledger_has_no_anonymous_rows`,
  `test_the_store_validates_and_does_not_trust_its_caller`.
- `TestAppendOnly` (`:292`) — no mutation method on the surface, the module's
  SQL never `UPDATE`s an event, a correction is a **new** event and the old one
  survives, no HTTP route mutates the ledger.
- `TestRecomputableViews` (`:481`) —
  `test_every_count_carries_exactly_the_events_behind_it`,
  `test_every_evidence_row_points_at_something`,
  `test_a_path_that_never_declared_a_length_gets_no_denominator`,
  `test_an_empty_log_is_an_empty_record_not_a_zero_claim`. An absence in the
  record is not a low result.

## 3. Evidence-quoting judge — **WO-W04** (#142, `4d033fb`, ADR 0060), with **WO-W09/W10**'s rubric judges

`tests/test_assessment_judge.py` — **15 tests**.

- `TestAssessmentParseDefense` (`:80`) —
  `test_valid_findings_are_grounded_and_guidance_only`;
  `test_any_malformed_judgment_degrades_whole_result_to_unassessed`;
  `test_timeout_is_unassessed_not_a_fabricated_default`;
  `test_control_signals_are_never_swallowed_as_unassessed` (cancellation and
  cost-cap signals survive the degradation path);
  `test_mock_mode_records_unassessed_without_constructing_client`.
- `TestIsolationAndExposure` (`:182`) — a jailbreak is isolation-wrapped before
  the judge; the raw judge schema is **absent** from every learner-facing
  contract.
- `TestGraphIntegration` (`:238`) — `test_gap_routes_to_exactly_one_probe_then_progress`
  (at most one follow-up, then a fixed edge);
  `test_malformed_judge_writes_explicit_unassessed_event`.

The same rule is enforced on the rubric judges in
`tests/test_learning_metrics.py` — **23 tests**:
`TestShameFreeCopyJudge::test_a_fabricated_quote_fails_the_whole_metric`
(`:203`) asserts the failure message contains `"not verbatim"`.
`docs/eval.md` states the rule the tests pin: a judge *"may only report an
offending quote that appears verbatim in the copy it was given"* — because *"a
judge that invents the text it complains about is how a rubric metric
manufactures a regression that never happened"* (PR #145).

`TestDeterministicChecks::test_pure_checks_and_agreement_make_no_model_call`
(`:323`) keeps the deterministic half free.

**The judge's calibration is not evidence of agreement with humans, and
`docs/eval.md` says so in its own words:** the 20-case set *"was authored as a
Codex-assisted implementation fixture on 2026-09-01; it is not composed of real
learner sessions, has not been ratified by the repository owner/operator, and
has not been scored by a live judge. … It is **not** evidence that the
assessment judge agrees with humans, cannot clear Gate W1, and cannot authorize
assessed learner-profile claims."* The flag stays default-off for that reason
(`src/config.py`: *"remains tutor guidance until its calibration prior is
owner-ratified"*).

## 4. The no-mastery-% gate — **WO-W14** (#147, `a9e26bf`), with **WO-W07** at the database

**The copy tier.** `web/tests/copy/forbidden.test.ts` — **63 tests** (PR #147
and #150). `PEDAGOGY_PHRASES` (`web/lib/copy/index.ts:250`) is a comment-fenced,
append-only section covering mastery, percentages, "unlocked", XP, streaks and
streak-guilt phrasing, badges/certificates, proficiency, any knowledge scalar,
"score", "grade", "dashboard". `LEARN_DENY_LIST` is a **strict extension** of
the product-wide list, asserted as such
(*"keeps the pedagogy list a strict extension of the product-wide one"*, `:634`).

Two properties make it more than a convention:

1. **The module set is discovered, not listed.** `copyModulesRenderedBy("(learn)")`
   walks `app/(learn)/`'s import graph; a discovered module the gate's table
   does not carry fails the coverage assertion (`:572-612`). When WO-W13 landed
   the reached set went from four modules to **nine**.
2. **A committed fixture that MUST fail.** `web/tests/fixtures/copy-pedagogy.fixture.ts`
   plants "87% mastered", a knowledge score, XP, a streak and a graded
   explain-back. `describe("WO-W14 criterion 2 — the planted fixture, which
   MUST fail")` asserts `findForbidden("87% mastered", LEARN_DENY_LIST)`
   equals `["mastery", "percentage", "percentage of knowledge"]`, that every
   planted key is caught **by name**, that the failure names which rule caught
   what, and — the test that justifies the whole list —
   *"would have escaped the product-wide list, which is why this list exists"*
   (`:699`): the product-wide list alone catches only the percent sign.

**The gate has already bitten, on this project's own copy.** Four WO-W13
sentences were reworded to satisfy it, all four *negations*, listed in PR
#147's body with before/after — and `session-copy.test.ts`'s own
`unassessedBody` carve-out was **deleted** rather than kept. Coordinator ruling:
the pedagogy list is **learn-scoped** (the `LEXICON_PHRASES` precedent), because
`run.qualityLabel` is the research metric's real name.

**The database tier.** `tests/test_progress_events.py::TestNoMasteryPercentage`
(`:609`) — no view field reads as a knowledge scalar; the only progress
arithmetic is labelled *schedule*; a payload key claiming a scalar is refused,
including nested; a **learner may still say the word** (`:675`); the SQL `CHECK`
and the Python ban are asserted to be the same list (`:688`); and
`test_the_published_api_schema_offers_no_mastery_property` (`:706`) checks the
contract. `BANNED_SCALAR_TOKENS` and the `progress_events_no_mastery_scalar`
CHECK mean the store cannot *hold* one; WO-W14 means the copy cannot *say* one.

**The browser tier.** `e2e/ledger.spec.ts` (4 tests) asserts no pedagogy
vocabulary in the painted document, and `e2e/session-flow.spec.ts:226` asserts
`expect(painted).not.toMatch(/\d+\s*%/)` over the whole rendered session page.

## 5. One string the gate does not cover, and it is service-authored

`src/agents/tutor.py:486` emits
**"This is an activity record, not a mastery score."**
It reaches `draft_report` → `job.result` → `SessionDetail.result` and
`GuidedSessionView` renders it verbatim, which is RC-16/H11 working as
designed — the service's own word, unedited.

It is also *"the exact construction WO-W14 removed from the copy dictionary one
tier down — a denial plants the frame it rejects"* (PR #150). The spec
subtracts that one service-authored string before running the pedagogy scan
over the painted page, and says in the code why.

Not a defect in either card. It is an inconsistency between the copy tier's
ruling and an agent string outside that tier's scope, and it is
[`known-gaps.md`](known-gaps.md) §6 — **closed by WO-W03b**, PR
[#151](https://github.com/kudratsingh/arxiv-research-agent/pull/151) /
`1026534`, one commit past this pack's baseline. The line now reads *"The lines
above are this session's activity record, drawn from the events it wrote."*, the
spec's carve-out is gone so the whole painted page is scanned, and the ban now
also binds the backend through `PEDAGOGY_DENY_LIST`
(`tests/test_simulate_learner.py:315`) — a hand-maintained mirror that is itself
[`known-gaps.md`](known-gaps.md) §17.

## 6. Fixture provenance, so no recording can pass as a session

**WO-W08** (#132) `validate_provenance`, pinned by
`tests/test_learning_fixtures.py` (**36 tests**): `real_session: true` is
rejected outright; every disclaimer must contain **"Not a real learner
session."** *verbatim*, hard-coded so the wording cannot be softened;
`recorded-mock` fixtures must name the generating commit and `mock_mode: true`;
`hand-authored` fixtures must name neither.

**WO-W11** (#148) filled the pending slot with fifteen real recordings and
`tests/test_record_learning_fixtures.py` (**15 tests**), including
`test_record_learning_fixtures` making `src.llm._get_client` raise — *"so a
recording that reached a model fails the test rather than billing"*. Two
vocabulary items belong to recordings alone: `recorded_ungraded` as an
assessment outcome (*"because the mock graph grades nothing and writing
`strength` into a file it never graded is the fabrication these rules exist to
prevent"*) and `simulator_filler` as a learner-turn intent.
