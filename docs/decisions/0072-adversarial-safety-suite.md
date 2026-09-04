# 0072. Gate safety on a regression delta and behavioural assertions, not on an absolute rate and a canary

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: WO-A11 (Phase A assurance)

## Context

The whole adversarial evidence base was five regexes in
`src/security/prompt_isolation.py:83`, exercised by about six synthetic
payloads, plus a literal-canary substring check on two of fifteen
learning scenarios (`src/eval/learning_benchmark.py:910,1095`).

That is not a weak measurement, it is the wrong *kind* of measurement.
The substring check asks a question about spelling. Obedience is not a
spelling. **A model that obeys an injection and paraphrases the canary
scores as contained**, and no quantity of additional payloads fixes it.
Before MCP and further tools widen the attack surface, the instrument
has to change.

Two published findings then rule out the obvious replacement.

1. **Attack success rate is a property of the deployment surface, not
   of the model.** Measurements put one model near 0% in a constrained
   environment and near 79% by attempt 200 in a permissive one. An
   absolute threshold is therefore not portable, not even across our
   own surfaces.
2. **At small n an ASR threshold flips on noise.** At n=100 an observed
   3% carries a Wilson interval of roughly 1.0%–8.5%, so a gate at
   "ASR < 5%" is a coin toss. An authored corpus does not reach n=100.

And a third rules out the obvious *scorer*: content-preserving wrappers
flip 57–100% of LLM-judge verdicts, which makes a judge inside a gate
an attack surface rather than a control.

There is also a hard licensing constraint. OWASP's prose is CC BY-SA
4.0, which is viral: copying a category description into this
repository would relicense the file that carries it.

## Decision

A first-class corpus (`tests/fixtures/safety/`), a deterministic scorer
and gate (`src/eval/safety_suite.py`), and a `security`-marked test
tier (`tests/test_safety_suite.py`).

**1. Behavioural assertions.** A case is scored on `ObservedBehaviour`
— which node the router dispatched to, which control-token values
survived, which egress destination was accepted, what the profile store
holds afterwards, what left the process as text. Seven executors, each
running this checkout's real defence, model-free and offline. The
substring check survives as `canary_substring_contained`, kept for one
purpose: `test_an_obedient_paraphrasing_agent_fails_containment` shows
it calling an obedient paraphrasing agent contained on the same
behaviour the new checks call three categorical breaches.

**2. Total-compliance simulation, not a paid model.** Each case carries
an `obedient_output`: what a fully-compromised model emits when it
obeys the payload. Rather than pay a model to *maybe* disobey, we
assume total compliance and assert that the system contains it. This
also makes the number mean the right thing — §3.4's point is that ASR
measures the surface, and this measures the surface directly.

**3. Categories cited as codes.** Primary mapping to the OWASP Top 10
for Agentic Applications (`ASI01`–`ASI10`), secondary to the LLM Top
10, with every description written here. The record *schema* is
modelled on the CC-BY-4.0
`nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1` set — schema
only, no rows. BeaverTails (CC-BY-NC) and AgentHarm (field-of-use) are
not vendored, and `tests/fixtures/safety/README.md` records
AgentThreatBench, CodeIPI and AgentDojo as permissive adoption
candidates rather than pretending they do not exist.

**4. Absolute zero for three categorical classes only.**
`secret_exfiltrated`, `unauthorised_tool_call`,
`egress_to_non_allowlisted_host`. These are categorical, not
statistical, so they need no baseline and get no advisory exemption.

**5. Everything else is a regression delta.** A committed
`baseline.json`, a Newcombe (Wilson-based) difference interval, and a
refusal to compare across different corpus fingerprints or checks
versions. Three states:

| | |
|---|---|
| **ROLLBACK** | a hard violation (veto, evaluated first), or a difference-interval lower bound above zero |
| **HOLD** | no comparable baseline, or a rise inside the interval |
| **PROMOTE** | flat or better |

**6. Advisory by default, veto always binding.** `--enforce` makes the
delta half blocking. The veto blocks either way — see "the one thing
the work order left open" below.

**7. Zero model calls inside the gate.** Asserted twice: by parsing the
module's imports, and by sabotaging `src.llm` and running the corpus.

**8. The pedagogy deny-list becomes a campaign metric.**
`PEDAGOGY_DENY_LIST` moves from `tests/test_simulate_learner.py` into
`src/eval/safety_suite.py`, `compute_outcomes` scans learner-facing
copy with it, and scripted rows carry `pedagogy_clean` /
`pedagogy_violations`. A violation is now an unmet structural
expectation, so `scripted_tier_check` fails on it instead of only
pytest.

### The one thing the work order left open

`02-STANDARDS.md` §3.4 says "advisory-by-default behind a flag" without
saying whether the safety veto is included. **It is not.** Advisory
mode softens only the delta. A hard violation blocks in either mode,
because absolute zero is not a statistical claim and there is nothing a
trusted baseline could add to it — the flag exists to buy time for a
baseline nobody trusts yet, and the veto never depended on one.

### Measured at adoption

**Attack success rate 3/42 = 7.14%**, Wilson 95% 2.46%–19.01%, against
`origin/main` at df89abc. All three zero-tolerance classes at zero. The
three successes are the residuals named in `docs/security.md`; they are
recorded in the corpus with `known_residual: true` rather than removed,
because a corpus that scores zero is a corpus that is not trying, and a
baseline of zero is a baseline that can only get worse.

## Alternatives considered

- **Gate on an absolute ASR threshold** — the obvious design, and the
  one both published findings above rule out. At n=42 a one-case move
  is inside the interval; a threshold gate would call it a regression
  and be ignored within a month.
- **Score with an LLM judge** — richer verdicts, and an attack surface.
  Content-preserving wrappers flip 57–100% of judge verdicts, so the
  thing being gated could rewrite the gate's verdict without changing
  its own behaviour. Also unaffordable: this must run per-PR at zero
  spend.
- **Vendor an existing corpus.** AgentThreatBench, CodeIPI and
  AgentDojo are permissive and offline and would give a bigger
  denominator — but none of them knows this system's tool surface, and
  a case that cannot name a real defence cannot be scored
  behaviourally. Recorded as adoption candidates for a later work
  order; a mixed corpus wants its own fingerprint and its own baseline.
- **Keep extending the canary check.** More scenarios, more probes.
  Cheaper, and it leaves the fatal shape intact: the check is asking
  about spelling.
- **Run the real graphs end to end.** The most faithful executor and
  the least runnable: it needs a model, so it costs money, is
  non-deterministic, and cannot be a per-PR gate. Total-compliance
  simulation gets the same behavioural facts for free.
- **Import the boundary rules instead of re-typing them.**
  `AUTHORISED_NODES` would come from `src.agents.supervisor`, the
  session write boundary from `src.api.runner`. Both would pull the
  model client or the whole API into a module whose defining property
  is that it reaches neither. Re-typed instead, with drift tests that
  read the originals — the technique WO-W03b already uses to keep the
  pedagogy deny-list in step across two languages.
- **Score the pedagogy deny-list as part of the ASR corpus.** It has no
  runtime containment — the campaign records violations rather than
  blocking them — so every such case would score as a success and
  inflate the rate without measuring a defence. It is a campaign
  metric, which is what WO-A11 asked for.

## Consequences

- **Positive.** A paraphrasing obedient model now fails. The three
  categorical breach classes have named, absolute-zero gates. The rate
  is published with its denominator and its interval, so a reader can
  see how little a 42-case corpus can support. Three real residuals are
  written down instead of being absent from a green report. The
  pedagogy rule is visible to the campaign gate. `pytest -m security`
  grows from 172 tests to 307 and is runnable as a standalone gate.
- **Negative.** The corpus is hand-authored, so it grows only when
  somebody writes a case, and its denominator is small enough that the
  interval is wide — honest, and not satisfying. Four constants are
  re-typed from other modules and one from TypeScript, each carrying a
  drift test that is itself maintenance. The `profile_write` executor
  mirrors `src/api/runner.py`'s write boundary rather than importing
  it, which is a second copy of a rule. `wilson_interval` duplicates
  arithmetic that WO-A09 is introducing in `src/eval/stats.py` — the
  safety gate cannot depend on a module that does not exist on its
  branch, and consolidating is a follow-up.
- **Follow-ups.**
  - Fold `wilson_interval` into `src/eval/stats.py` once WO-A09 lands,
    and bump `CHECKS_VERSION` if any verdict moves.
  - Close `asi08-unbounded-section-list` by capping the length of
    `request_more_sections`, and re-baseline.
  - Close `asi08-attacker-named-section` by validating requested
    section names against the paper's actual sections, the way
    `src/agents/tutor.py` already validates plan sections against the
    briefing's allowed set.
  - Wire the gate into CI as an advisory step, then flip `--enforce`
    once the baseline has survived a few campaigns.
  - Evaluate AgentThreatBench and CodeIPI as a second, separately
    fingerprinted corpus.
