# Task-bound full abstention — offline revision

This is an implementation repair, not a new provider result, human qualification,
or an authorization. Stage D is deferred. The response-contract revision is
`workspace-assistance-task-bound-v7`; its number is independent of the historical
programme packet names. The starting application checkout is `35e8eef9`.

## Preserved baseline

The archived v8r4b packet is
`1429b39296792b8bc3d5530d28bcc56600048b149310fc10df30c2ee6048a7a7`.
Its raw results, scorer and Codex-attributed synthetic review remain unchanged in
`/private/tmp/arxiv-agent-eng-programme-capacity/outputs/d5/review-v8r4b-20261109/`.
No labels are promoted to independent human evidence. The observed Stage C run
completed eight mechanical workflows; that is not eight accepted answers.

A repeatable read-only census records **30 programme jobs, 61 Messages, 81 counts,
USD 1.779493 estimated cumulative spend, and zero pending/unknown liability**.
The effective limits remain 34 jobs, 80 Messages, 99 counts, USD 10 and concurrency
one. Existing expiry remains `2026-11-14T07:24:01Z`. No Stage D grant is present.
The implementation does not write this ledger or activate any approval.

## Application policy precedes generation

The Reader records an explicit task intent: explain/answer, compare sources, or
assess an application. Assessment context has four bounded fields: vehicle and
configuration, operating envelope, safety objectives, and validation evidence.
This first required-context profile is for vehicle/controller assessment, matching
the archived safety task; other assessment domains need separately declared
requirements rather than treating these four fields as universal. Whitespace is not supplied context. These inputs are unverified user context,
not source evidence or proof of safety. Private notes/history are not added.

The server derives a canonical task policy from that input, the mode and the
number of distinct selected works. The request digest, local schema, transformed
wire schema and qualification producer bind that policy. The adapter reconstructs
it before dispatch. Schema identities use the sorted unique evidence catalog, so
JSONB or canonical-JSON key reordering cannot change the sealed schema. Reversed
and duplicate catalogs and production-adapter JSON round trips are regression
controls. A model cannot decide that missing assessment context only
prevents a comparison, change the policy, or clear an abstention reason.

An assessment missing any required field has **only one response branch**:
`full_abstention`, with a fixed `application_context_required` reason and bounded
codes requesting exactly the missing fields. It has no claims, claim-reference
sections, comparison bases, free explanation, questions, or proposal prose.
Local rendering supplies the neutral requests. A generic full-abstention branch
exists for other unanswered tasks. Providing every context field permits the
normal answer schema; it does not make an answer supported or authorize execution.

A comparison request can instead return `comparison_abstention`: separately cited
source notes, with no comparison conclusion/basis fields. Existing selected-handle,
source/version/hash, Unicode offset, quote, scope and whole-claim checks remain.
The UI explicitly says **Requested comparison remains unanswered**. An actual
comparison answer still requires independently cited source bases. A single
selected work cannot produce the cross-source answer disposition.

New Reader requests default to the new task-bound contract. The policy is based
on the declared task, not a claim that arbitrary natural language is reliably
classified. Historical internal inputs with explicit `task_context=null` retain
their old contract; frozen benchmark construction pins that compatibility path.
They do not inherit the new guard or qualify as new-version validation. The
published client always supplies task context. Historical packets must be run
with their original producer checkout, not rebound to this source revision.

## Enforcement and rendering

Both local and exact transformed wire schemas are validated in the regression
suite. Validation precedes claim normalization and checker dispatch. The original
captured safety output, retaining its populated sections, is rejected; changing
its reason to comparison-only or null is also rejected. Correct full abstention
has zero factual claims and still receives mandatory checking. A final unsupported
claim after the existing single repair/recheck fails in the new revision; residual
unscored factual prose still blocks acceptance.

The same policy flows through the real isolated PostgreSQL service, HTTP preview,
submission, stage advance, ownership boundary, reload, and saved-job lookup. The
qualification read model also validates and renders the new envelope without
modifying its immutable raw steps; both Reader result views show the disposition. Reader
form tests verify separate draft recovery, context changes invalidating preview,
no dispatch from task selection/preview, missing-context prompts, comparison notes,
and exact passage links. No provider/client credential is used: production adapter
contacts are intercepted by `httpx.MockTransport`, and software verdicts are
synthetic. They establish control behavior, not actual support or checker quality.

## Reproduce the focused checks

From the implementation worktree root:

```sh
export ANTHROPIC_API_KEY=local-preview-disabled
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
"$VENV_PYTHON" -m pytest tests/test_workspace_task_policy.py tests/test_workspace_task_assistance.py -q
```

The PostgreSQL fixture creates and drops only random disposable test schemas.
Do not substitute the active qualification or owner database. Frontend:

```sh
cd web
ANTHROPIC_API_KEY=local-preview-disabled npm test -- --run tests/workspace/assistance-panel.test.tsx
```

The archive fixture preserves the original public outputs and exact selected
material. Wrapping the retrieval/measurement outputs in a new envelope and the
clean full abstention are explicitly synthetic projections; none are new model
successes. See `tests/fixtures/d5/stage-c-v8r4b/README.md`.

## Focused follow-up — separate from this repair

The machine review found request-coverage misses in seven of eight cases, eighteen
non-atomic claims, and two qualification losses. Those judgments remain synthetic
and attributed to Codex. This patch addresses the disposition failure, not all
three broader quality problems.

1. Request coverage: freeze a task-specific coverage checklist before generation.
   Full abstention, useful source notes and a completed answer must be scored
   separately. A supported note cannot count as answering an unanswerable comparison.
2. Bundled claims: separate independently testable findings before checking; bind
   each to its own evidence. Do not increase the claim cap or silently drop material
   requirements. Report omissions when the bounded claim budget cannot cover them.
3. Qualifications: explicitly test retention of population/task, intervention,
   evaluation conditions and exclusions. The memory and verification examples are
   development diagnostics; they must not become a newly held-out success cohort.

A fresh validation proposal is separate in
[FULL-ABSTENTION-VALIDATION-PROPOSAL.md](FULL-ABSTENTION-VALIDATION-PROPOSAL.md).
Neither that document nor remaining programme headroom grants permission to run it.

## Offline evidence

`outputs/d5/full-abstention-v7/` contains focused/full gate logs, the read-only
preservation receipt, exact local/transformed schemas and rendered controls, and
24 Chromium controls (two result viewers × three dispositions × dark/light × desktop/390 px). The
browser API was explicitly synthetic and read-only; database durability is
established by the separate real PostgreSQL HTTP/service tests, not these images.
No serious/critical axe findings or console exceptions occurred in that matrix.

To regenerate the schema/render report from the worktree root:

```sh
ANTHROPIC_API_KEY=local-preview-disabled "$VENV_PYTHON" - < planning/14-explore-and-research-modes/d5/tools/task-bound-regression-report.py
```

Representative captures: `assistance-safety-light-390.png`,
`qualification-safety-dark-1440.png`, and `qualification-retrieval-light-390.png` in that output directory.
The committed verification receipt records the final gate results separately.

The frozen v8r4b scorer and benchmark builder remain historical. A future paid
validation packet needs a separately versioned task-policy input/analysis binding;
the new contract is not silently inserted into old cohorts, scored results or
Stage A receipts. The separate proposal is an unexecuted development outline,
not an approval-ready provider packet or a renewed authorization.

### Concrete development follow-up from the preserved machine review

These are supplied Codex/synthetic findings, not new independent judgments. The
historical scorer and results remain unchanged.

| Archived case | Next offline correction to demonstrate |
|---|---|
| Retrieval | State that relevance cannot be compared from poison-detection and supervised-baseline abstracts; name incompatible tasks and missing common relevance judgments. Keep the separately checked notes, not an implied completed comparison. |
| Safety | New full-only policy addresses the disposition/context request. The old four-claim response and its bundled c3 remain failed historical evidence. |
| Mechanism | Name the unavailable IR specification, graph-to-prediction and encoder/readout details instead of a generic methods request; split c4's NLL and AUROC findings. |
| Conditions | Retain the five-domain web-safety scope and distinguish absent protocol/breakdown details; split c1 and c3. |
| Reproduction | Make the requested evidence-state schema/update, data access/splits, stop-judge training and fixed-round controls explicit unknowns or sourced steps; split c1/c4/c5/c6. |
| Measurement | Preserve request coverage and the weaker/variable effects; split c2's prefilling result from the banning-plus-examples result. |
| Memory | Say that persistence of incorrect stored information over time is not measured by the selected evidence; split c3/c4 and retain what the exclusion percentage measures. |
| Verification | Identify missing direct uncertainty evidence (confidence calibration and abstention coverage); split c2/c3/c4/c6 and restore c3's study/task scope. |

Predeclare a request-facet checklist with evidence/claim references, explicit
unavailable facets and unanswered facets. The checklist must not treat a populated
section as evidence that the request was answered. Budget independent findings
within the existing six-claim cap and expose omissions instead of increasing the
cap after a failed result. Retain task/population, comparator, metric definition
and intervention qualifications in each supported assertion. Coherent units and
separate citations must preserve nonadjacent qualifications without inventing a
continuous quotation. Use the observed cases only as development diagnostics;
freeze any genuinely new held-out questions and scoring policy before collection.
