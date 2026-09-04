# 0069. Property-based testing as a tier, with pinned Hypothesis profiles

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: kudratsingh

## Context

The repository had **zero** property-based tests against 2,204 passing
example tests — and its parsers are exactly the shape that generated
input finds bugs in. A section-aware chunker over PyMuPDF output, five
regex redaction rules, an inline-citation extractor over text a model
wrote, 39 numerically-bounded settings fields, a hand-rolled SSE
encoder: in every one of those the input space is enormous and the
invariant is a single sentence.

The instinct was already in the suite. `tests/test_log_redaction.py:25`
writes one property by hand — *the secret is never in the output* — for
six credentials somebody chose. Six is enough to prove a rule runs. It
is not enough to prove a rule holds, because the credential that leaks
is by definition the one nobody wrote down.

Two things made now the moment. WO-A02 landed a harness
(`tests/conftest.py`) that makes the network, a real model client and a
developer's `.env` unreachable from a test, so generated input cannot
wander into a paid call; and it registered a `property` marker with
zero members, which is a promise with nothing behind it.
`planning/08-assurance/02-STANDARDS.md` §6 had already adopted
Hypothesis (MPL-2.0) with one instruction attached: `deadline=None` in
CI.

The assumption that would change this answer: that the modules named
above stay pure. A property tier over functions that reach a database
or a model is a fuzzing harness pointed at a bill.

## Decision

Adopt `hypothesis` as a **fourth purpose marker in its own directory**,
`tests/property/`, with six modules and 36 properties covering the
areas §3.4 of the assurance architecture names. They expand to 126
collected tests, because the settings sweeps are parametrized over
every field rather than sampling one.

### 1. What a property in this repository is

Each one states its invariant in the **first sentence of its
docstring**, and that sentence is the deliverable as much as the code
is: a property whose invariant cannot be said in a sentence is usually
two properties, and a property nobody can restate is one nobody will
maintain.

| Module | Properties | The invariants |
|---|---|---|
| `test_property_chunker.py` | 5 | No chunk over budget; header-free text is lossless; chunking is idempotent; section labels ignore whitespace around headers; `chunk_index` restarts per section |
| `test_property_citations.py` | 6 | Every supported inline style resolves; the metric never raises; every unresolved citation is one the report contains; bracket-free prose cannot change a score; cite keys round-trip |
| `test_property_redaction.py` | 8 | Each of the five rules destroys its generated secret; credential-free prose survives byte-for-byte; redaction is idempotent; `redact_url` answers for any string |
| `test_property_config.py` | 7 | Every bounded field accepts its range and rejects outside it; every `Literal` accepts exactly its members; the lease pair is accepted *iff* three refresh cycles fit |
| `test_property_sse.py` | 4 | Encode-then-decode is the identity; one call is exactly one frame; encoding is deterministic; `closes_stream` is wider than `is_terminal_event` by exactly one name |
| `test_property_schemas.py` | 6 | A bounded plan survives JSON; an over-bound plan is refused; arbitrary JSON raises only `ValidationError`; the three review verbs and nothing else |

Every module carries a tier marker plus `property`; two also carry
`security` and `contract`, because the axes are orthogonal
(`docs/testing.md`).

Two rules follow from the standards' warning that a property asserting
nothing falsifiable is worse than no test:

- **Both directions, wherever the invariant has two.** The five
  redaction properties would all pass against a function that returned
  `"***"` unconditionally, so a sixth asserts that ordinary prose comes
  back unchanged. The `Literal` rejection sweep would pass against a
  field that rejected everything, so its companion enumerates the
  members. The lease invariant is stated as an equivalence, because
  half of it is that the check does not *over*-reject a configuration
  an operator wrote deliberately.
- **Bounds are derived, never restated.** `test_property_config.py`
  reads its ranges off `Settings.model_fields`, so a field added
  tomorrow is swept the day it lands and a widened bound is checked
  against the new range. A hand-maintained copy of 39 ranges is a
  second source of truth, and the second source is the one that goes
  stale.

### 2. Profiles: three, differing only in how many examples run

Registered in `tests/property/conftest.py`:

| Profile | `max_examples` | `derandomize` | When |
|---|---|---|---|
| `ci` | 100 | yes | the per-PR gate (`CI` is set) |
| `dev` | 200 | yes | local default |
| `explore` | 2,000 | no | opt-in, `HYPOTHESIS_PROFILE=explore` |

`derandomize=True` in the two gating profiles is what makes this tier
admissible **as a gate**: the examples are a pure function of the
test's name and its strategies, so a CI failure reproduces on a laptop
from the node id alone — no seed to copy out of a log that may have
been truncated, and no question of whether a fix worked or the input
merely changed. It also implies `database=None` in Hypothesis, which
is why that setting is not passed alongside it.

`explore` exists because derandomization is a real cost: a fixed
example set stops finding new things. It is deliberately not what any
gate runs, and it is where hunting happens — it is also what found the
one defect in this work order's own first draft (see Consequences).

`deadline=None` everywhere, per standards §6. A per-example deadline
measures wall clock on a shared runner, so it fails on machine load
rather than on anything about the code; `pyproject.toml`'s 60-second
per-test timeout is the real ceiling, it applies uniformly, and it
names the test that hung.

### 3. Placement and naming

`tests/property/` is a package (`__init__.py`), because `tests/` is
one: with it, pytest names these modules `tests.property.test_*` and a
file here can never collide with a same-named module in `tests/`.

The suite's file-walk tier census in `tests/test_harness_guards.py`
globs `tests/test_*.py` and does not recurse, so it does not see this
directory; the **per-item** census does, through
`pytest_collection_modifyitems`, and that is the check that actually
binds. No change to either was needed.

Hypothesis writes its storage under `.hypothesis/`, creating a
`.gitignore` of `*` inside it on first use, so nothing had to be added
to the repository's ignore rules.

## Alternatives considered

- **Properties alongside the example tests, in `tests/test_*.py`** —
  no new directory, and the property sits next to the examples for the
  same module, which is a real advantage. Rejected because the tier has
  a *configuration*: profiles, an example budget, a runtime target. A
  conftest that applies to `tests/` applies to all 98 modules, and the
  first time somebody debugged a 60-second unit test they would find
  Hypothesis settings they never opted into.
- **One property module per source module** — mirrors the existing
  `tests/test_chunker.py` ↔ `src/tools/chunker.py` convention.
  Rejected for now only because five of the six areas map to one module
  each anyway; the sixth (`redaction`) spans `logging.py` and its
  callers. Worth revisiting when the tier is twice this size.
- **`mutmut` / mutation testing as the gate instead** — the honest
  measure of whether a test is load-bearing. Rejected per standards §6:
  Google does not gate on mutation score, the runtime is minutes per
  module, and the same evidence is available cheaply as a **manual
  seeded-mutant check in the PR body**, which is what this work order
  did (six mutants, six caught).
- **Hypothesis `RuleBasedStateMachine` on the checkpointer** — adopted
  *selectively* by standards §6 and genuinely the place stateful
  testing pays. Out of scope here: it needs a checkpoint backend
  fixture, which puts it in the integration tier, and it is a work
  order rather than a property.
- **Schemathesis against the FastAPI app** — attractive (`from_asgi`
  drives the app in-process with no server) and rejected upstream in
  standards §6: it hard-requires `pytest>=9`, so adopting it forces a
  pytest major bump as a side effect.
- **Randomized (`derandomize=False`) profiles in CI** — finds more over
  time, and is what most projects do. Rejected because a gate whose
  input set changes between runs cannot answer "did my fix work?", and
  because a flaky gate is a gate people learn to re-run. `explore`
  keeps the capability without putting it on the critical path.

## Consequences

- **Positive.** Thirty-six invariants now hold over generated input
  rather than over 2,204 chosen examples. The tier runs in **≈14 s** locally
  (`dev`, 200 examples) and **≈11 s** under the `ci` profile, against a
  60-second target, and it is reproducible: two consecutive runs of
  `pytest -m property` produce identical results by construction.
  `make test-property`, which WO-A02 shipped pointing at an empty
  selector, now selects 126 tests.
- **Positive.** Six seeded mutants — an off-by-one chunk window, a
  one-character gap between windows, a narrowed `sk-` rule, a
  pretty-printed SSE payload, a dropped `et al.` spelling, and a
  loosened lease margin — were each caught by a different property,
  with a shrunk counterexample in the failure output. That is the
  evidence that these are load-bearing rather than decorative.
- **Negative.** A property is harder to read than an example, and a
  failing one arrives as a shrunk counterexample rather than as a
  scenario. The mitigation is the invariant sentence: the docstring has
  to be enough to reconstruct the intent without reading the strategy.
- **Negative.** The strategies encode assumptions about the input
  domain, and a wrong assumption produces a *false* failure that looks
  like a bug in `src/`. This happened once during the work order: the
  losslessness property's first placement algorithm took the latest
  admissible position for each chunk, which is not optimal when the
  text repeats, and the `explore` profile falsified it on
  `'a aaa aaaaaa. a a a a a a a aa.'`. The chunker was correct; the
  test was wrong. The fix — carry the single largest frontier, which
  provably dominates — is documented in `advance()`, and the episode is
  the argument for running `explore` before opening a PR.

### Findings this tier recorded rather than fixed

Neither is in this work order's scope; both are written down here so
the next person does not rediscover them.

1. **`CHUNKER_OVERLAP_TOKENS` may exceed `CHUNKER_MAX_TOKENS`.** The
   fields validate independently (overlap `0..500`, budget
   `100..4000`), so `CHUNKER_MAX_TOKENS=100` with
   `CHUNKER_OVERLAP_TOKENS=500` is an accepted configuration in which
   `_split_by_budget` advances one character per iteration and emits
   roughly one chunk per character of the paper. This is the same shape
   as `_check_lease_invariant`: two individually valid values that
   combine into a broken pair, and therefore a cross-field validator's
   job. `budget()` in `test_property_chunker.py` draws only the healthy
   regime and says why.
2. **`format_sse` does not sanitise its event name.** A name containing
   a newline would split one frame into two on the wire. It is not
   reachable today — every name comes from a closed set the runner
   publishes, and `tests/test_contract_sse_events.py` pins that set —
   so the properties here are stated over the closed set, as WO-A05
   specifies. It becomes reachable the day an event name is derived
   from anything a client supplies.

### Follow-ups

- The stateful `RuleBasedStateMachine` over the checkpointer that
  standards §6 adopts selectively — a work order of its own.
- Hypothesis 6.167.1's shrinker raised `ValueError: <n> is not in list`
  from `minimize_duplicated_choices` when two string draws with
  *different* alphabets held equal values during shrinking. It affects
  only the reporting of a failure, never whether one is detected, and
  it did not recur after the property that provoked it was corrected.
  Worth re-checking on the next Hypothesis bump.
