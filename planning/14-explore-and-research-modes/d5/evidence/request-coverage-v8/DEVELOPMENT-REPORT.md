# Request-coverage development controls

Offline development controls: Codex-attributed synthetic baseline, mocked quality judgments, never provider successes or independent human labels

Original machine review: 41 claims, 18 bundled findings, two lost qualifications; 7/8 requests missed. Those results are unchanged.

| Case | Original claims | Synthetic claims | Known quality defect blocks | Request complete |
|---|---:|---:|---|---|
| v8-learn-conditions | 4 | 4 | True | False |
| v8-learn-measurement | 6 | 6 | True | False |
| v8-learn-mechanism | 4 | 4 | True | False |
| v8-learn-reproduce | 6 | 6 | True | False |
| v8-research-insufficient | 4 | 0 | False | False |
| v8-research-memory | 5 | 5 | True | False |
| v8-research-retrieval | 6 | 6 | True | False |
| v8-research-verification | 6 | 6 | True | False |

## v8-learn-conditions

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Study scope and evaluated conditions — lacks_evidence
- Reported conditional findings — lacks_evidence
- Unspecified protocol and breakdowns — lacks_evidence

## v8-learn-measurement

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Measured intervention results and their conditions — lacks_evidence
- Proposed applications in this selected source — lacks_evidence

## v8-learn-mechanism

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Inputs and stated prerequisites — lacks_evidence
- Construction steps and outputs — lacks_evidence
- Unavailable method details — lacks_evidence

## v8-learn-reproduce

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Task and dataset to reproduce — lacks_evidence
- Evidence-state and stopping-judge implementation details to collect — lacks_evidence
- Dataset access, splits and controls to collect — lacks_evidence

## v8-research-insufficient

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Establish a safe learned controller for the specified application — lacks_evidence

## v8-research-memory

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Direct evidence of memory error persistence — lacks_evidence
- Valid-information retention and its metric — lacks_evidence

## v8-research-retrieval

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Compare retrieval relevance using compatible tasks and judgments — lacks_evidence
- Separately cited source evaluation context — lacks_evidence

## v8-research-verification

Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.

Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):
- Evidence of uncertainty-aware verification and calibration — lacks_evidence
- Counterevidence and missing validation — lacks_evidence
