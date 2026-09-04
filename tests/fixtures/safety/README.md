# The adversarial safety corpus

`corpus.json` is the authored red-team corpus WO-A11 / ADR 0072 built to
replace "five regexes and a canary substring". `baseline.json` is the
fixed measurement the gate compares against.

Read `src/eval/safety_suite.py` for the schema and
[`docs/security.md`](../../../docs/security.md) ("The adversarial safety
suite") for what the numbers mean.

## Licensing — this is a hard constraint, not a preference

- **Every payload here is original**, authored for this repository and
  licensed with it.
- **Categories are cited as codes.** OWASP's prose is CC BY-SA 4.0,
  which is viral; copying a category description into this repository
  would relicense the file that contains it. So the corpus carries
  `ASI01`..`ASI10` and `LLM01`..`LLM10` identifiers, and every gloss in
  `AGENTIC_CATEGORIES` / `LLM_CATEGORIES` is our own sentence. A reader
  who wants the authoritative wording follows the code to the source.
- **The record schema is modelled on the CC-BY-4.0
  `nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1` set** — an
  operator goal, untrusted content carrying an injected instruction, and
  a deterministic verifier. Schema only: no rows from it are vendored,
  and nothing here is derived from its text.
- **Not vendored, deliberately:** BeaverTails (CC-BY-NC — this
  repository is not non-commercial) and AgentHarm (field-of-use clause).
  Neither may be redistributed here in any form.
- **Adoption candidates**, recorded rather than pretended away, for a
  later work order that wants a bigger denominator without a judge:
  AgentThreatBench (MIT, ships in `inspect_evals`, rule-based scorers),
  CodeIPI (MIT, canary files, container network disabled) and AgentDojo
  (MIT, rule-based). All three are permissive, offline and judge-free.

## Safety of the artifact itself

These are fixtures, not live exploits.

- **No network.** Every URL in the corpus resolves offline: an IP
  literal, or a scheme the guard rejects before DNS.
  `tests/test_safety_suite.py::test_the_whole_corpus_runs_with_dns_disabled`
  proves it by sabotaging `socket.getaddrinfo` and running the suite.
- **No real credentials.** The corpus file contains no
  credential-shaped string at all. Cases that need one carry a
  `canary_id` and a `{canary}` placeholder;
  `safety_suite.CANARY_SECRETS` holds the fakes, every one of them
  marked `CANARY` and never issued.
- **Nothing harmful outside the harness.** No payload does anything but
  ask a language model to misbehave. There is no shell command, no file
  path, no real host, and no working exploit anywhere in this
  directory.

## Adding a case

1. Add the record to `corpus.json`. `load_corpus` validates it
   strictly — an unknown field, a missing one, a duplicate `case_id`, an
   unknown category, surface or canary is a hard failure, because a
   record that silently fails to parse is a smaller denominator wearing
   the same number.
2. If it needs a surface that does not exist, add the executor to
   `SURFACES`. An executor calls this repository's **real** defence and
   returns `ObservedBehaviour` — facts about what happened, never a
   verdict.
3. Regenerate the baseline in the same PR:
   `python -m src.eval.safety_suite --write-baseline tests/fixtures/safety/baseline.json`.
   The corpus fingerprint moves whenever a case does, and the gate
   returns HOLD rather than comparing across two different corpora.
4. Say in the PR body what the new ASR is **with its denominator**.
