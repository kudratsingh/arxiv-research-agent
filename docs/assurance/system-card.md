# System card

**A system card, not a model card.** This project trains no model, fine-tunes
nothing and ships no weights. It calls a hosted model through a vendor SDK. The
honest artifact therefore describes the *system* — what it is for, what it must
not be used for, which models it routes to, what has actually been measured
about it, and what has not.

**Reviewed at `ed71098`.** Every number below came out of a runner and is linked
to the file it came out of. Where there is no number, this card says there is no
number rather than supplying an adjective.

## 1. Identity

| | |
|---|---|
| **Name** | `arxiv-research-agent` |
| **What it is** | A multi-agent research assistant for ML/AI papers, plus the operable surface around it: a FastAPI async job API with SSE streaming, and a Next.js browser client (the "Evidence Workbench"). |
| **Version** | The commit. There is no release tag; the repository is the artifact. |
| **Provider** | One maintainer, Kudrat Singh. Not an organisation. |
| **Licence** | **None.** The repository ships no `LICENSE` file, so no grant is offered. This is recorded rather than fixed: licensing is an owner decision (W-OD-3), and inventing an SPDX identifier here would be a licensing claim the repository does not make. |
| **Deployment status** | **Not deployed.** No hosted instance, no collector, no dashboards running. Everything operational ships as reviewable files that nothing runs. |
| **Trains a model?** | No. |
| **Fine-tunes a model?** | No. |

Under NIST AI 300-1 ipd's *model* template (Clause 5.3), fields 4 (Design) and
5 (Training) have no honest answer for a system like this. They are left
unanswered rather than filled with something adjacent — see
[`framework-mapping.md`](framework-mapping.md) §1.

## 2. Intended use

Ask a research question in natural language. The system plans a search, **pauses
for a human to approve or rewrite that plan before it spends anything**,
searches arXiv (optionally enriching through Semantic Scholar's citation graph),
reads each paper's full text, synthesises a briefing with citations, and
self-critiques for quality.

**Intended users:** a person reading ML/AI literature for themselves — a
researcher, a student, an engineer catching up on a subfield. One shared
workspace; there is no multi-tenancy on `main` (a proposal exists; the decision
is the owner's).

**Intended context:** a briefing is a *starting point for reading the papers*,
not a substitute for reading them. Every claim in a briefing carries a citation
precisely so it can be checked, and the export formats exist so the output
leaves the tool.

**Human oversight is structural, not advisory.** HITL is on by default: every
submission stops after the planner, and the run goes nowhere until someone
approves, revises or cancels. That is a cost control first and an oversight
mechanism second, and both are real.

## 3. Out-of-scope use

Stated as prohibitions, not as caveats.

1. **Not for use by an educational or vocational training institution to
   evaluate learning outcomes, assign or admit people, assess what level of
   education someone should receive, or monitor students during tests.** Those
   four uses are EU AI Act Annex III point 3(a)–(d), and deploying this system
   into any of them would make it a high-risk AI system with obligations nothing
   in this repository satisfies. The guided-read learning surface makes this a
   live risk rather than a theoretical one: it is a study aid, and it is
   **explicitly not an assessment instrument**. `assessment_status` reports the
   judge's outcome as a *fact* (`recorded_ungraded` / `unassessed` / `assessed`)
   rather than as a grade, for exactly this reason.
2. **Not a source of truth.** No accuracy metric has ever been measured on a
   real run (§5). A briefing may be wrong, may cite a paper the run never
   retrieved, and may omit the most important work on a topic.
3. **Not for medical, legal, financial or safety-critical decisions.** It reads
   preprints. Preprints are not peer-reviewed.
4. **Not for high-volume or unattended operation.** HITL is the cost control;
   turning it off (`ENABLE_HITL=false` or `hitl_bypass: true`) removes the only
   thing standing between a bad plan and a full campaign's spend.
5. **Not a search engine, and not a replacement for arXiv.** It reads a small
   number of papers per run. Coverage is not a design goal and is not measured.
6. **Not to be run against a live search while claiming offline operation.** Mock
   mode is a demo fixture, not an offline mode — it still downloads five real
   PDFs from arxiv.org on a cold cache.

## 4. Models and routing

The system calls Anthropic's API through the official SDK. Nothing is trained,
tuned or distilled.

| Role | Setting | Default on this tree |
|---|---|---|
| Every agent, unless overridden | `anthropic_model` | `claude-sonnet-4-6` (`src/config.py:62-63`) |
| Eval judges | `eval_judge_model` | `claude-sonnet-4-6` (`src/config.py:799-800`), pinned separately **on purpose** — falling back to `anthropic_model` is the defect ADR 0070 records, because it makes the judge move when the product moves. |
| Per-agent overrides | `reader_model`, `planner_model`, `synthesizer_model`, `critic_model`, `verifier_model`, `supervisor_model`, `query_refiner_model`, `tutor_model`, `assessment_model` | Empty — each falls back to `anthropic_model` (`src/config.py:950-1015`). |

**On the routing recommendation.** ADR 0021 recommends putting a cheaper model
on the reader, supervisor and query refiner. `README.md:611` attaches a number
to that — "~50-60% cost cut with baseline quality preserved". **That number has
no measurement behind it anywhere in this repository**, and neither does
"quality preserved". ADR 0021 itself defers the evidence to "paired-diff eval
runs" that have never happened. It is recorded in the claim index as an
unenforced accuracy claim, and it is not repeated here as fact.

**Provider dependency and its failure behaviour.** One model supplier. The SDK
owns model retries; nothing above it adds a loop; the retry envelope is clamped
so one flaky call chain fits inside 75% of the job budget. A provider outage now
has its own error code rather than landing on `internal_unexpected` — a defect
this phase's fault tier found and fixed.

## 5. Evaluation — what has actually been measured

This is the section a system card is judged on, so it is split into what was
measured and what was not.

### 5.1 Measured, on this tree

All at zero model spend, from
[`../../planning/08-assurance/evidence/gate-a3/`](../../planning/08-assurance/evidence/gate-a3/README.md).

**Structural correctness**

| Signal | Result | Floor |
|---|---|---|
| `pytest -m "not e2e"` | 3235 passed, 55 skipped | — |
| Branch coverage, over exactly the gating selection | **91.31%** | 89% |
| `src/api` / `src/agents` / `src/security` / `src/eval` | 88 / 92 / 100 / 94 | 86 / 92 / 97 / 91 |
| `pytest -m e2e` | 16 passed | — |
| `pytest -m property` | 152 passed | — |
| `pytest -m fault` | 157 passed, 3 skipped | — |
| `pytest -m security` | 314 passed | — |
| `pytest -m contract` | 98 passed | — |
| `mypy --strict src/` | clean, 93 files | — |
| `ruff check src/ tests/` | clean | — |

**Adversarial safety** — 42 authored attacks, model-free, offline:

- **3 of 42 succeed — 7.14%, Wilson 95% interval 2.46%–19.01%.**
- **Zero categorical hard violations** (`egress_to_non_allowlisted_host`,
  `secret_exfiltrated`, `unauthorised_tool_call`). This is the veto the gate
  enforces at absolute zero, and it is the number that means the most.
- All three successes are **named residuals recorded in the corpus before the
  run**: one soft-phrased goal nudge (ASI01) and two content-shaped
  amplification cases (ASI08).
- The gate is a *regression delta plus a categorical veto*, not an absolute
  threshold — at n=42 an absolute threshold flips on noise, and the interval
  above is why.

**Scripted learning tier** — 15 scenarios driven through the real compiled
session graph: **15/15 completed, 0 errored, $0.0000, 0 unmet expectations, 15
attributable rows.** The campaign prints its own caveat: one repeat per
scenario, where three is the bar before a delta is believable. Single-run
differences are noise.

**Supply chain** — an SBOM (CycloneDX 1.4, 126 components) and a vulnerability
audit from one PyPA tool. Five advisories across four packages, none fixed on
this branch; one was already recorded in `pyproject.toml`. Listed individually
in [`framework-mapping.md`](framework-mapping.md) §4.

### 5.2 Not measured — and this is the honest headline

**No accuracy metric has ever been measured on a real run.** The four
LLM-judged research metrics — citation accuracy, faithfulness, completeness,
retrieval recall — are implemented, unit-tested and wired into a nightly
workflow that **failed every one of its runs at a missing repository secret**.
No campaign has produced a `summary.jsonl`. There is deliberately no eval badge
and there are deliberately no placeholder numbers, because a red badge for work
that was never funded says the wrong thing and a placeholder says a worse one.

The deterministic groundedness checks (identifier resolution against the run's
own corpus, verbatim quote matching) are built, cost nothing and do not drift
when a model is upgraded — but they have only run over recorded fixtures. A rate
measured over fixtures is a fact about the fixtures.

Unblocking all of this is one funded 20-query campaign. That is an owner
decision (W-OD-1), and an implementer does not take it.

### 5.3 Judge–human calibration is unmeasured, and deferred

Stated separately because it is the load-bearing gap under every judged number
this system could ever produce.

**Nothing in this repository calibrates any LLM judge against a human reader.**
Not the four research metrics, not the assessment judge, not the explain-back
scorer. The infrastructure that a calibration would need exists — pinned judge
models, versioned rubrics locked by digest, a paired McNemar comparison path,
and a 20-case `explain_back_calibration.json` fixture — and the fixture's own
provenance block says what it is: *"synthetic explain-backs; not real learner
sessions"*, `owner_ratified: false`, and it "cannot clear Gate W1 or authorize
assessed profile claims until W-OD-1 and owner ratification."

The consequence, stated plainly: **every judged score this system can produce is
a number with no known relationship to human judgement.** A judge can be
self-consistent, cheap and completely wrong in the same direction every time,
and nothing here would detect that. Content-preserving wrappers are measured to
flip 57–100% of LLM-judge verdicts, which is why ADR 0072 keeps judges out of
the safety gate entirely.

Closing it needs human-labelled items and paid judge calls. It is deferred, not
overlooked, and it is recorded in
[`framework-mapping.md`](framework-mapping.md) §6 row 1 under NIST MS-1.1-009.

## 6. Safety measures

The threat model starts from a fact rather than a hypothetical: **arXiv PDFs are
untrusted input.** Anyone can publish a paper, and paper text flows into model
calls whose output steers the workflow. Full model in `docs/security.md`.

- **Prompt-injection isolation.** Untrusted paper text is wrapped in a tagged
  block with control-string sanitisation and close-tag escaping; conversation
  `prior_context` gets the same treatment on the planner.
- **Egress control.** The PDF fetcher rejects non-HTTPS schemes and any URL
  resolving to a non-globally-routable address, before the request leaves the
  process. `egress_to_non_allowlisted_host` is a hard-violation class scored at
  absolute zero.
- **A closed action set.** The supervisor picks from a strict enum; an unknown
  action is refused and logged, not dispatched.
- **Spend ceilings at two layers.** `max_cost_usd` is checked inside `call_llm`
  before every call *and* between graph nodes, so a node's parallel fan-out
  cannot overshoot by its whole spend, and the ceiling binds on the CLI and eval
  paths too.
- **Resource guardrails.** Streamed PDF downloads abort at `pdf_max_bytes`;
  per-job wall-clock and per-run concurrency are bounded; retry envelopes are
  clamped against the job budget.
- **Credential boundary.** The browser never holds a key. `X-API-Key` is
  attached server-side in one route handler and nowhere else, and a test walks
  every shipped client file to prove that module is the only reader.
- **Per-principal scoping.** A key sees only its own jobs and conversations;
  cross-principal access returns 404, not 403.
- **Redaction.** Logs carry a salted `principal_hash` rather than a principal
  id, and the diagnostics surface a user can copy carries no question text and
  no briefing text.
- **Auth is off by default** for local development, and the production overlay
  forces it on plus a separate human-facing login — so an anonymous visitor
  cannot spend the account's money.

**And the honest counterweight:** the safety corpus is 42 authored cases written
by the same people who wrote the defences. There has been no third-party red
team, and there is no test for adversarial poisoning of the vector index
(OWASP LLM08 is defined in the corpus schema and unused).

## 7. Known limitations

The ones a user or reviewer would want to know, not a disclaimers list.

1. **No measured accuracy.** §5.2. This dominates everything else on this list.
2. **Judge–human calibration is unmeasured.** §5.3.
3. **Two of three ASI08 amplification attacks succeed.** Cost and wall-clock
   ceilings bound the blast radius; the content-shaped amplification itself is
   not defended against.
4. **One benchmark query is contaminated and says so.**
   `hallucination-mitigation` is well-covered by the five built-in mock papers,
   so its retrieval recall is scored against a corpus hand-picked to match it.
   The annotation is load-bearing and a test asserts it survives every edit.
5. **`citation_accuracy` scores 1.0 for a report with zero citations**, and
   never looks at an identifier — a report that invents a whole citation entry
   scores perfectly. This is demonstrated on this repository's own e2e fixture.
   ADR 0074's deterministic groundedness is the replacement and reports `None`
   with a reason code instead; the old metric is still what the eval runner
   emits.
6. **Reader coverage is shallow by construction.** A small number of papers per
   run, ranked chunks rather than whole papers, and an abstract-only fallback
   when PDF fetch, extract, chunk or rank yields nothing.
7. **Mock mode is not offline.** Five real arXiv PDF downloads per cold run.
8. **The built-in mock papers carry real third-party attribution and no
   provenance field of any kind** — five titles, real author names, real arXiv
   identifiers and live PDF URLs, with no licence or attribution recorded. See
   [`data-provenance.md`](data-provenance.md) §7.
9. **No multi-tenancy.** One shared workspace on `main`.
10. **Nothing is deployed**, so every SLO in `docs/reliability.md` is marked
    *declared, not earned*, and no runtime number exists.
11. **The lock file is not hashed.** ADR 0045 records it; the SBOM's own tool
    warns about it.
12. **Several documented claims are stale or unenforced.** The claim index in
    [`README.md`](README.md) lists them by name, including three claims that are
    false on this tree. That list is part of this card by reference.

## 8. Recourse and reporting

There is no incident-reporting channel beyond the public repository's issues,
and **no issue template carries the NIST GV-4.3-002 incident field set** — a gap
recorded in [`framework-mapping.md`](framework-mapping.md) §1. Seven runbooks
cover what an operator does when an instrument fires; nothing covers what a
*user* does when a briefing is wrong.

## Related

- [`README.md`](README.md) — the index, and the claim → enforcement table.
- [`data-provenance.md`](data-provenance.md) — every dataset, on the NIST AI 300-1 field set.
- [`framework-mapping.md`](framework-mapping.md) — NIST, OWASP, ISO 42001, EU AI Act.
- [`../../planning/08-assurance/evidence/gate-a3/README.md`](../../planning/08-assurance/evidence/gate-a3/README.md) — the dated evidence pack every number here came out of.
