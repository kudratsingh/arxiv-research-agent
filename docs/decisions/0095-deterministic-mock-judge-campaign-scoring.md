# ADR 0095: Deterministic mock-judge campaign scoring

**Status:** Accepted

**Date:** 2026-09-17

## Context

The Stage-0 campaign executed every research arm under mock mode, but its
default scorer intentionally ran only deterministic groundedness and citation
resolution. Completeness, faithfulness and retrieval recall all stopped at
their `call_llm_json` boundary. Every episode therefore recorded
`judges_run: false`, leaving three metric parsers, their campaign persistence,
and the calibration controls unexercised until a paid run.

No live judge call is authorized. `ANTHROPIC_API_KEY=local-preview-disabled`
must remain a structural refusal, and existing scripted-tier records and
goldens must not change.

## Decision

Add a default-off `python -m src.campaign run --mock-judge` mode. It is
available only when `USE_MOCK_DATA=true` and the API key is exactly the
zero-spend sentinel. The scorer installs a fixture-backed callable over the
three metric module judge sites for the duration of scoring and restores the
original callable afterwards. It never constructs a provider client.

The checked-in fixture supplies decisions rather than prose pretending to be
model output. Each generated completeness, faithfulness and retrieval-recall
response is validated by a strict Pydantic schema before the production metric
aggregator consumes it. Episode records retain all five metric results, three
mock-judge records, `judges_run: true`, zero judge model calls and zero judge
cost. A deterministic null faithfulness verdict represents abstention.

The scorer also runs `src.calibration.blinding` over the public synthetic
pairwise fixtures: case ids become blinded ids, the seeded schedule presents
every pair in both AB and BA order, and the resulting readings are recorded.
Identity-leak scanning runs over every metric prompt before the fixture may
answer it.

The existing deterministic scorer remains the default. Scripted evaluation
does not select the mock judge and keeps its committed bytes unchanged.

## Alternatives considered

- Treat the existing defensive parser unit tests as sufficient. Rejected:
  they do not prove the campaign call graph, persistence or denominator path.
- Patch `src.llm.call_llm_json` globally. Rejected: the metric module imported
  the callable into its own namespace, and a global patch would be a guard
  that the actual judge sites bypass.
- Let `USE_MOCK_DATA=true` enable mock judges automatically. Rejected: it
  would silently change the meaning and bytes of existing mock campaigns.

## Consequences

The 300-episode matrix can exercise all five research metrics, strict output
validation, blinded ids, seeded pair ordering and abstention at zero cost.
These results are harness qualification only. They are deterministic
consequences of a public fixture and provide no evidence that a real judge is
accurate or calibrated.

A real judge run still needs all of the following:

1. owner approval for model spend and expert time;
2. a representative, independently expert-labelled set with adjudication;
3. an approved human-label retention policy and evaluator access controls;
4. current judge model ids, prices, prompt and rubric locks;
5. live structured-output compatibility validation against the provider;
6. measured agreement, false-pass, false-fail and abstention by slice;
7. measured AB/BA position bias and declared thresholds before unblinding;
8. the campaign and per-episode cost caps and stop conditions in protocol 14.
