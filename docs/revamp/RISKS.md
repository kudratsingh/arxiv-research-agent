# Frontend revamp risk register

Updated: 2026-08-28

| ID | Risk | Likelihood | Impact | Current mitigation / next proof | Owner | Status |
|---|---|---:|---:|---|---|---|
| R-01 | A UI retry creates a duplicate, paid research run | Medium | Critical | Mark `POST /research` non-idempotent; no automatic retry; add state-machine/E2E proof before migration | Data/workflow WO owner | Open |
| R-02 | The active `?job=` is lost and paid work becomes invisible | High | High | Preserve job URL contract; design persistent active-run recovery and test reload/navigation | Shell/workflow WO owner | Open |
| R-03 | Frontend designs structured evidence the API cannot supply | High | High | Freeze backend shapes; use plan/stage/report trace now; put structured evidence behind a separate backend proposal | Orchestrator | Mitigated at Gate 1; human confirmation pending |
| R-04 | Mobile remains unusable despite component polish | High | High | Replace fixed rail structurally; test phone/tablet reflow and landmarks in the first shell slice | Shell WO owner | Open |
| R-05 | SSE live/replay differences regress terminal reconciliation | Medium | High | Keep custom EventSource adapter; contract fixtures for live/replay/timeout/unknown events; always final-GET | Workflow WO owner | Open |
| R-06 | Generated OpenAPI types create false confidence | Medium | Medium | Generate JSON schemas only; maintain tested SSE/export/error overlays and an API drift report | Data-layer WO owner | Open |
| R-07 | Shared server principal is mistaken for end-user multi-tenancy | Medium | Critical | Confirm private shared-workspace intent at Gate 1; do not present accounts/ownership UI unsupported by deployment | User + orchestrator | Decision pending |
| R-08 | A frontend migration weakens the server-only secret boundary | Low | Critical | Retain BFF; add proxy security tests and CSP before rollout | Architecture owner | Open |
| R-09 | Dynamic plan forms and async messages fail keyboard/screen-reader use | High | High | Native controls first, selective accessible primitives, axe + keyboard + screen-reader evidence | Accessibility owner | Open |
| R-10 | Storybook/MSW mocks diverge from SSE and backend state | Medium | High | Use shared contract fixtures; deterministic stub API for EventSource; keep real Compose smoke tests | Test-foundation owner | Open |
| R-11 | Design dependencies consume bundle/performance budget | Medium | Medium | Selective primitives/icons; route budgets, bundle reports, Lighthouse CI, lazy-load export/advanced surfaces | Design-system owner | Open |
| R-12 | Source builds exceed 4 GB CX23 memory during deployment | Medium | High | Prefer CI-built images or a measured swap/build strategy; verify before paid provisioning | Deployment owner | Paused until Gate 4 |
| R-13 | Browser evidence is incomplete because in-app runtime is unavailable | Medium | Medium | Lighthouse CLI captured objective Chrome evidence; require Playwright browser matrix in Phase 4 | Test-foundation owner | Accepted for Gate 1 |
| R-14 | Failed jobs lose useful partial reports/exports in the UI | Medium | Medium | Resolve product rule at Gate 1/2 and lock it with fixtures | User + product owner | Decision pending |
| R-15 | Broad upgrades (Tailwind 4, TypeScript 7) obscure product regressions | High | Medium | Keep them separate from the revamp unless an ADR and migration work order justify each | Architecture owner | Mitigated by scope |
