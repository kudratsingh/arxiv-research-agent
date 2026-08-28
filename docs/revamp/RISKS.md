# Frontend revamp risk register

Updated: 2026-08-28 (Gate 2 close)

| ID | Risk | Likelihood | Impact | Current mitigation / next proof | Owner | Status |
|---|---|---:|---:|---|---|---|
| R-01 | A UI retry creates a duplicate, paid research run | Medium | Critical | Mark `POST /research` non-idempotent; no automatic retry; add state-machine/E2E proof before migration | Data/workflow WO owner | Open |
| R-02 | The active `?job=` is lost and paid work becomes invisible | High | High | Preserve job URL contract; design persistent active-run recovery and test reload/navigation | Shell/workflow WO owner | Open |
| R-03 | Frontend designs structured evidence the API cannot supply | High | High | Freeze backend shapes; use plan/stage/report trace now; put structured evidence behind a separate backend proposal | Orchestrator | Closed — confirmed by D-009 (omit, don't simulate); WO-15 ships only a documented insertion point |
| R-04 | Mobile remains unusable despite component polish | High | High | Replace fixed rail structurally; test phone/tablet reflow and landmarks in the first shell slice | Shell WO owner | Open |
| R-05 | SSE live/replay differences regress terminal reconciliation | Medium | High | Keep custom EventSource adapter; contract fixtures for live/replay/timeout/unknown events; always final-GET | Workflow WO owner | Open |
| R-06 | Generated OpenAPI types create false confidence | Medium | Medium | Generate JSON schemas only; maintain tested SSE/export/error overlays and an API drift report | Data-layer WO owner | Open |
| R-07 | Shared server principal is mistaken for end-user multi-tenancy | Medium | Critical | D-009: shared-principal model rejected as end state; real multi-tenancy is workstream MT-01 (`docs/proposals/multi-tenancy.md`, PROPOSED); revamp shell reserves identity seams but presents no accounts UI | User + orchestrator | Decision made at Gate 1; MT-01 proposal awaits its own human gate |
| R-08 | A frontend migration weakens the server-only secret boundary | Low | Critical | Retain BFF; add proxy security tests and CSP before rollout | Architecture owner | Open |
| R-09 | Dynamic plan forms and async messages fail keyboard/screen-reader use | High | High | Native controls first, selective accessible primitives, axe + keyboard + screen-reader evidence | Accessibility owner | Open |
| R-10 | Storybook/MSW mocks diverge from SSE and backend state | Medium | High | Use shared contract fixtures; deterministic stub API for EventSource; keep real Compose smoke tests | Test-foundation owner | Open |
| R-11 | Design dependencies consume bundle/performance budget | Medium | Medium | Selective primitives/icons; route budgets, bundle reports, Lighthouse CI, lazy-load export/advanced surfaces | Design-system owner | Open |
| R-12 | Source builds exceed 4 GB CX23 memory during deployment | Medium | High | Prefer CI-built images or a measured swap/build strategy; verify before paid provisioning | Deployment owner | Paused until Gate 4 |
| R-13 | Browser evidence is incomplete because in-app runtime is unavailable | Medium | Medium | Lighthouse CLI captured objective Chrome evidence; require Playwright browser matrix in Phase 4 | Test-foundation owner | Accepted for Gate 1 |
| R-14 | Failed jobs lose useful partial reports/exports in the UI | Medium | Medium | Gate 2 ruling (D-010): expose partial-report export, labelled partial on screen; locked by WO-18/WO-19 criteria and the failed-partial fixture | User + product owner | Closed at Gate 2 |
| R-15 | Broad upgrades (Tailwind 4, TypeScript 7) obscure product regressions | High | Medium | Keep them separate from the revamp unless an ADR and migration work order justify each | Architecture owner | Mitigated by scope |
| R-16 | Plan lineage is unknowable for finished runs: `src/api/runner.py:454` sets `job.plan = None` when review resolves, so the frozen API cannot say which plan produced a briefing | High | Medium | Design reports what was witnessed and never interpolates (03 §0); accepted as permanent at Gate 2 (D-010); a durable plan snapshot is a future backend proposal beside MT-01 | Orchestrator | Accepted at Gate 2 |
| R-17 | The 120 KiB font budget across eight faces (~15.0 KiB/face incl. Literata Italic 400) is at or past the achievable subsetting floor | Medium | Medium | WO-02 measures first; RC-01 ratchet rule governs any raise with a per-face table; reviewer assessed a raise as likely | Design-system owner | Open — expected to trigger the ratchet |
