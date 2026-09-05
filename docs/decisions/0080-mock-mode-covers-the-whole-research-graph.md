# 0080. Mock mode covers the whole research graph

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent-capability lane (CAP-07)
- **Depends on**: ADR
  [0041](0041-retrieval-and-degradation-honesty.md) (`MOCK_PAPERS` is
  reachable only under `use_mock_data`; the plan fallback),
  [0016](0016-evidence-store-source-text-verifier.md)
  (`EvidenceClaim.source_text`),
  [0074](0074-deterministic-groundedness.md) (the check a briefing is
  scored by), [0075](0075-scripted-research-tier-and-paired-claims.md)
  (the scripted research tier, whose own follow-up this closes half of)

## Context

`USE_MOCK_DATA` did half of what its name says.

It swapped arXiv search for five fixture papers
([`src/agents/search.py`](../../src/agents/search.py)) and gave the
tutor and the assessment judge deterministic branches. It did **not**
touch [`src/llm.py`](../../src/llm.py), and the research graph's
planner, reader, synthesizer, critic and verifier called
`call_llm_json` under it exactly as they do in production.

The assurance lane's frontend survey measured what that costs. On the
seeded stack with no credential, `POST /research` returns **202**, and
four seconds later the job is **`failed`**, `error_type=upstream_model`,
`llm_calls=0`. There was no path from `docker compose up` to a briefing
without a paid key — so the product could not be demonstrated, evaluated
or screenshotted by anyone who had not first bought a credential, and
the failure a first-time reader met was the one failure mode that says
nothing at all about the product.

Three consequences, each of which someone has already paid for:

1. **The e2e tier cans four agents by hand.**
   [`tests/e2e/conftest.py`](../../tests/e2e/conftest.py) has carried
   `research_llm_surface` since WO-A15 and a paragraph explaining why.
2. **The research lane's per-PR gate scripts the model's words.** ADR
   0075 built `simulate_research` with a scripted surface over the four
   agents' `call_llm_json` names, an `ExitStack` restore, and a
   tripwire — and named the honest cost in its own consequences: *the
   report text in a scripted record is the harness's*, so the tier
   measures the pipeline around the model and can never be quoted as a
   quality number. Its alternatives section calls this ADR's change
   "the cleanest possible answer", rejected there only for scope.
3. **The asymmetry has to be re-explained everywhere.** The same
   paragraph appears in `docs/eval.md`, `docs/testing.md` and the e2e
   conftest, because a reader who missed it writes a test that spends
   money.

## Decision

Each of the five research agents gets a `settings.use_mock_data` branch,
placed **before** its model call, returning a deterministic output
derived from the run's own inputs. The generators live in one pure
module, [`src/agents/mock_mode.py`](../../src/agents/mock_mode.py).

### 1. Where the branch goes, and why it is an early return

`src/llm.py` is untouched. The guard is the same setting the search
agent already reads, checked in the agent — so the gateway keeps exactly
one job (call the provider) and mock mode keeps exactly one meaning
(this run has a different source of truth).

Four of the five are an early `return` at the top of the node function.
The reader's sits at the top of `_analyze_paper`, ahead of
`_gather_ranked_chunks` rather than merely ahead of `call_llm_json`,
because that helper calls `parse_pdf` and the keyless path has to be
*offline* as well as free: the reader is the only node that would
otherwise leave the machine.

Early returns rather than a `parsed = mock() if … else call()`
restructure, deliberately: the diff adds lines and reindents none, so
the live path's bytes are unchanged and a rebase over a sibling lane
editing the same call sites does not conflict structurally. The cost is
that the critic's message format string appears twice, which is stated
in a comment rather than hidden.

### 2. What each agent produces

| Agent | Mock output | Derived from |
|---|---|---|
| planner | ADR 0041's plan-fallback shape: the raw query as the single sub-question and search query | the query |
| reader | one analysis per paper, `key_findings` verbatim from the abstract; with the evidence store on, claims whose `claim` and `source_text` are the same verbatim abstract span | the paper |
| synthesizer | a briefing whose sections follow the plan and whose inline `arXiv:<id>` references and citation entries name the papers on the state | the state |
| critic | approve at a fixed constant, `revision_needed=False` | nothing |
| verifier | `verified=True`, no unsupported claims, no missing evidence | nothing |

Output *shapes* are identical to the live path, so the compiled graph,
the SSE frame sequence, the export, the checkpoint and the eval record
layout are unchanged. Both of the synthesizer's paths have a mock
counterpart; the evidence path changes which text the briefing prints
under each paper and changes nothing about either citation surface, so
the two score identically under ADR 0074.

### 3. The briefing says what it is, in its first line

Exactly `Mock mode: fixture papers, no model call.`

The search agent has announced its fixture corpus in a node message
since ADR 0041, and a node message is the right place for a fact about
*this run*. A report is different: it is exported, checkpointed, and
pasted into other documents, so it outlives the run and travels away
from every log line that described it. The label therefore goes in the
document, first, exactly — not "contains", not "starts with", because a
label a reader has to scroll to find has not done its job.

### 4. Derived, never invented

The rule ADR 0041 set for retrieval — *fabricating sources is never
acceptable* — is what this module is built to. Analyses and evidence
claims are verbatim slices of the paper's own abstract, located by index
so a returned span is findable in the source rather than reconstructed
near it. Citations carry the identifiers the run actually retrieved.
The planner reuses the raw-query fallback rather than inventing a
decomposition, because a mock decomposition would be a guess about the
topic dressed as an analysis of it — and because that fallback is
already the one plan this repository accepts as honest when no model
spoke.

The briefing **quotes nothing**. `groundedness.extract_quotes` reads any
six-word span inside double quotes as a claim; with no full text to
check it against, every such claim is undecidable, so a quoting mock
briefing would buy a column of exclusions and no information.
`quote_verbatim_rate` therefore reports `null` with reason `no_quotes`,
which is true. ADR 0075's scripted synthesizer declines quotes for the
same reason.

### 5. The scripted research tier keeps its meaning

The branch is checked before the call, so it would pre-empt any surface
that patches `call_llm_json` — including `simulate_research`'s. Left
alone, that tier's `scripted_llm_calls` would fall to zero and
`scripted_tier_check --lane research` would fail the one assertion
separating "free" from "absent".

So `scripted_surface` additionally rebinds `settings` on the four
modules it scripts to a `use_mock_data=False` copy, leaving
`src.agents.search` on `True`. The two halves of the setting are
separable because `settings` is bound per module. The tier keeps
measuring what ADR 0075 says it measures, and its committed baseline
stays byte-identical — `script_digest()` covers the responders, not the
context manager, so `dataset_version` does not move either.
`tests/e2e/conftest.py::research_llm_surface` does the same thing for
the same reason.

Replacing that surface with the product's own mock branch is ADR 0075's
follow-up. It is a rebaseline rather than a refactor — the report's
words change, so every content column moves — and it belongs to the
lane that owns `src/eval/`.

## What this does NOT claim

**Nothing produced here is a quality signal.** Not one number, and the
critic's score least of all.

- The critic's `quality_score` is a constant. It is deliberately the
  same constant the e2e fixture and the scripted tier already use, so a
  mock run is numerically indistinguishable from a canned one in that
  column — which is exactly why the honesty is carried by the banner and
  by the critique text (`"no model judged this briefing, so this score
  carries no quality signal"`) rather than by a number a reader would
  have to know a convention to decode.
- The verifier's `verified=True` is not a finding. It is what "nobody
  looked" has to be encoded as on a state field whose consumers read
  `True` as "no follow-up needed"; the message says so in words.
- A mock briefing is not a synthesis. It groups restated abstract
  sentences under the plan's headings. It compares nothing, reconciles
  nothing, and identifies no gap.
- A green mock run says the **pipeline** is wired: five nodes, in order,
  each one's output reaching the next, citations surviving to the state,
  and `$0.0000`. It says nothing whatever about prompts, about the
  model, or about whether a real briefing would be any good.

## Alternatives considered

- **Fix it in `src/llm.py`** — return a canned payload from
  `call_llm_json` under mock mode. Rejected: the gateway would have to
  know which agent called it to produce a schema-valid answer, which is
  a dispatch table on prompt text, and it would silently disarm the
  spend guard for every future caller including ones that should fail.
- **Make the branch defer to an installed surface** — take the mock
  path only when `call_llm_json` is still the real one. Rejected: that
  is production code inspecting whether it has been monkeypatched. The
  harnesses turn the branch off themselves instead, which puts the
  decision in the harness where a reader can see it.
- **Let the mock branch pre-empt the scripted tier and let that tier's
  proof-of-work assertion fail** until the assurance lane rewrites it.
  Rejected: a gate that fails by design is not a gate, and the window
  would be however long the follow-up takes.
- **A separate setting** (`MOCK_RESEARCH_AGENTS`). Rejected: two
  settings for one intent, a matrix of four states of which two are
  incoherent, and a compose file that has to set both. `use_mock_data`
  already means "this run has a different source of truth".
- **Forcing the recovery signal to `analysis_complete=False`** on the
  reader's mock path, matching what the live abstract-only path does.
  Rejected: under mock mode there is no full text to recover, so the
  supervisor would spend a round asking for something no configuration
  can supply.
- **Quoting the abstract inside the briefing** so ADR 0074's quote half
  has a denominator. Rejected — see §4. A denominator the harness
  manufactured measures the harness.
- **Per-node log events** (`planner_mock_plan_served`, …). Not done
  here: `KNOWN_EVENTS` in `src/observability/logging.py` is a closed
  registry owned by another work order. A mock run is already announced
  three times without them — `search_mock_data_served` fires once per
  run, every node stamps `(mock data)` on its state message, and the
  briefing carries the banner. Recorded as a follow-up.

## Consequences

- **Positive.** `docker compose up` with no credential produces a
  visibly-labelled briefing end to end. The product can be demonstrated,
  screenshotted and clicked through by someone who has bought nothing,
  and the first thing a new reader meets is the product rather than
  `error_type=upstream_model`.
- **Positive.** The e2e tier gains a module that drives the *product's*
  keyless path with no canned agent at all
  (`tests/e2e/test_mock_mode_keyless.py`), which is the one
  configuration every other test in that directory replaces before it
  runs.
- **Positive.** ADR 0075's headline limitation becomes fixable. When the
  assurance lane deletes the scripted surface, the report text in a
  scripted record becomes the *product's* mock branch — the same
  property the learning lane's tier already has, and the reason its
  scripted tier has caught regressions.
- **Negative.** A mock briefing is a plausible-looking document that
  contains no analysis. The banner is the whole defence, which is why
  it is asserted as an exact first line in three places and why the
  critique text repeats the point where a score is displayed.
- **Negative.** Two harnesses now have to remember to turn the branch
  off, and a third that forgets would silently test the fixture rather
  than the product. Both existing sites say so in prose at the patch.
- **Negative.** Mock mode covers the *fixed pipeline's* five agents. The
  supervisor (`src/agents/supervisor.py`), the query refiner, and ADR
  0076's `verify` and `repair` nodes still call the model under
  `use_mock_data`, so a keyless run with `ENABLE_SUPERVISOR=true` or
  `RESEARCH_POLICY=fixed_verify_repair` still fails. The fixed pipeline
  is the shipped default and the demo path; the rest is a follow-up.
- **Follow-ups.**
  - Delete `simulate_research`'s scripted surface and rebaseline the
    tier (ADR 0075's own follow-up). Owner: the assurance lane.
  - Update the "mock mode is not an LLM stub" paragraphs in
    `docs/eval.md` and `docs/testing.md`, which describe the world as it
    was before this change. Owner: the assurance lane.
  - Register the five per-node mock log events in
    `src/observability/logging.py`. Owner: whoever holds that registry.
  - Extend the branch to the supervisor, the query refiner and ADR
    0076's repair policy, so a keyless run is possible under every
    graph shape rather than only the default one.
