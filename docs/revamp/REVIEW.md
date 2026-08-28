# Gate 1 independent review

Reviewer: separate Codex collaboration agent (`gate1_frontend_inventory`)  
Author: root orchestrator  
Review policy: no reviewer edits; file/line findings; reject until evidence is corrected

## First pass — rejected

Date: 2026-08-28  
Verdict: **REJECT pending correction**

| Severity | Finding | Resolution |
|---|---|---|
| Blocking | Browser/accessibility evidence omitted major reachable states, an actual plan-review capture, visible 404, standalone axe, and reproducible fixtures | Added an idempotent local-only Postgres/Redis seed, passing Playwright capture spec, 27 visual artifacts across major states, useful-resolution plan review, visible 404, and 12 standalone axe-core reports |
| Blocking | Candidate traces claimed a current/failing stage even though SSE emits only `node_completed`, has no intermediate replay, and terminal frames omit the node | Reframed all concepts/research around job status and **last observed completed checkpoint**; reload may be unknown; failure is after the last observed checkpoint, never “in” a claimed node |
| Major | Roadmap redefined Gates 2–4 | Restored the supplied protocol: Gate 2 after design/architecture/work orders; Gate 3 after foundation + vertical slice; Gate 4 after quality/docs before ship |
| Major | Landing copy implied review precedes all paid work | Disclosed that plan generation may be billable and review occurs before literature search/downstream research |
| Major | Companion documentation/TDD/review tooling and named community registry fallbacks were incomplete | Recorded unavailable MCP/plugin categories, native/official-doc fallbacks, and searches of skills.sh, claude-plugins.dev, and GitHub lists |
| Major | FastAPI was mislabelled 0.1.0 | Discovery now distinguishes application 0.1.0 from FastAPI 0.139.0 |
| Minor | Dependency audit had no retained artifact/reproduction command | Added exact `npm audit --json` artifact, dependency counts, exit result, and reproduction command |
| Minor | Recommended visual direction could still be generic | Kept this as a Phase 2 refinement: specificity must come from truthful plan lineage, arXiv/query language, checkpoints, and report behavior—not laboratory decoration |

## Correction evidence

```text
seed-local-baseline.sh                         exit 0
capture-baseline.spec.ts                       1 passed (13.4s)
axe-baseline.spec.ts                           1 passed (5.3s)
plan-review Lighthouse                         98 / 94 / 96
npm audit --json                               exit 0; 0 vulnerabilities
Lighthouse JSON parse                          pass
axe JSON parse                                 pass
relative Markdown links                        pass
```

The state specs use a deliberately invalid model key and local synthetic data. They never call the non-idempotent research endpoint.

## Second pass — approved

Date: 2026-08-28  
Reviewer: the original second-pass run was interrupted by a session end; a fresh independent reviewer agent re-ran the full pass against the current artifacts under the same policy.  
Verdict: **APPROVE**

All eight first-pass findings were verified as genuinely resolved against the
artifacts, not merely claimed: evidence tables match the retained Lighthouse/axe
JSONs row for row, the SSE reframing ("last observed completed checkpoint",
unknown-after-reload) survives everywhere outside this file's own finding record,
the roadmap gate definitions match the supplied protocol, landing copy discloses
billable plan generation, companion-tooling gaps and fallbacks are recorded,
the FastAPI version split is correct, the npm-audit artifact is retained, and the
anti-generic critique is deferred to Phase 2 as the first pass accepted.
Cross-checks: all relative links resolve, the baseline commit exists, the
installed skill's SHA-256 matches its documented hash, SSE event names match
`src/api/runner.py`, and the web suite passes live (12 files, 78 tests).

New findings — both minor, neither blocks Gate 1:

| Severity | File:line | Finding | Resolution |
|---|---|---|---|
| Minor | `baseline/README.md` Lighthouse section | Six of the seven Lighthouse JSONs predate the committed seed fixture: they were captured against an ad-hoc local conversation (`/c/a018b0b0ed454f1e`, default port 3000), not the seeded `baseline-populated` stack (port 13000) used for the plan-review recapture, while the README implied the fixture underlies all retained evidence. Genuine same-commit local-lab results; a provenance-disclosure gap, not falsified evidence. | Disclosure sentence added to the Lighthouse section of `baseline/README.md` |
| Minor | `02-DIRECTIONS.md` Direction C sketch | The checkpoint-ruler sketch pre-labels anticipated future stages (`READ ?`, `SYNTHESIZE ?`, `CRITIQUE ?`), presuming a fixed node vocabulary the discovery doc says must not be assumed; the surrounding prose ("maps only observed `node_completed` events") is correct. | Carried forward as a Phase 2 constraint: if C or a C-hybrid advances, tick labels must derive only from observed events or an explicitly drift-tested stage map |

Residual risks accepted at this gate: bundle-size figures and fixture-run
timings were taken on documentation trust (re-running needs the local Docker
stack; the committed specs, retained JSONs, and passing test suite make
fabrication implausible); Lighthouse evidence is single local lab runs,
disclosed as such, with field SLOs deferred; keyboard/screen-reader/reflow
quality is explicitly deferred to Phase 6 manual checks. The shared-principal
deployment model, partial-report export policy, and direction choice remain
open by design — they are the human decisions Gate 1 exists to obtain.
