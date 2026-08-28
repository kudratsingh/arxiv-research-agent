# Frontend revamp research

Research completed: 2026-08-28  
Current-version snapshot: 2026-08-27/28  
Status: Gate 1 candidate

## Research question

What interface model, accessibility/performance standard, category convention, and technology path can turn the current demo into a durable research workbench without changing its backend contracts or weakening the server-only credential boundary?

## Method and confidence

- Official standards, documentation, first-party design systems, product help centers, repositories, and package registries were preferred.
- Public product documentation can establish features and interaction models, but not every live visual, failure, or accessibility state. Unverified details are not presented as observations.
- Technology versions are a time-stamped registry snapshot, not a permanent “latest” claim.
- Product implications are analysis specific to this repository; they are not direct statements from the cited source.

## Synthesis

The strongest product model is a **durable research workspace**, not a chatbot and not an analytics dashboard. The user starts with a question, approves a plan as an explicit human-control boundary, leaves or watches a long-running pipeline, then reads and exports a document. The interface should make this trace easy to recover:

```text
question -> approved plan -> observed completed checkpoints -> report -> metrics/export
```

The most attractive category differentiator is claim-adjacent evidence. The frozen HTTP API cannot provide it structurally today, however. The near-term signature must therefore use the real plan, named pipeline events, opaque Markdown report, and aggregate metrics; a claim/source ledger belongs in a separate backend proposal.

## UX and interaction evidence

### General usability

| Source | Relevant evidence | Product implication |
|---|---|---|
| [Nielsen Norman Group — 10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) | Visibility of system status, user control, consistency, error prevention, recognition, and recovery are general interaction foundations. | Preserve the active run in URL and navigation; expose job status, last observed completed checkpoint, and last update; never auto-retry a paid submission; keep recovery beside the retained work. |
| [NN/g — Complexity vs. Simplicity in Application Design](https://www.nngroup.com/articles/complex-application-design/) | Complex work benefits from progressive disclosure and strong information hierarchy rather than indiscriminate removal. | Keep the initial question simple, but retain plan details, event diagnostics, cost, quality, and exports behind contextual disclosure. |
| [NN/g — Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/) | Useful errors identify the problem in plain language and provide a constructive recovery path near the cause. | Normalize inconsistent backend errors into a small user vocabulary while retaining technical detail in disclosure; distinguish expired, offline, unauthorized, rate-limited, and failed. |
| [NN/g — Empty State Interface Design](https://www.nngroup.com/articles/empty-state-interface-design/) | Empty states should explain the system and provide an appropriate next action, while distinguishing first use from no results. | Separate first conversation, empty history, no filter match, expired job, and failed partial-result states. |
| [NN/g — Form Design Placeholders](https://www.nngroup.com/articles/form-design-placeholders/) | Placeholders do not replace labels and disappear during entry. | Keep a visible question label; use examples outside the field; show the 8,000-character limit and submission/cost context persistently. |
| [Laws of UX — Hick's Law](https://lawsofux.com/hicks-law/) and [Jakob's Law](https://lawsofux.com/jakobs-law/) | Choice time grows with undifferentiated options; familiar conventions reduce learning cost. | Offer one dominant “New research” action and conventional thread/history navigation, then reveal advanced constraints progressively. |
| [Laws of UX — Fitts's Law](https://lawsofux.com/fittss-law/) | Important targets should be adequately sized and easy to reach. | Approval, revision, cancel, export, mobile navigation, and recovery need clear hierarchy and robust targets—not icon-only hover affordances. |
| [Refactoring UI](https://www.refactoringui.com/) | Practical visual hierarchy comes from deliberate spacing, typography, color roles, and component construction. | Build semantic tokens and density scales before restyling individual screens; use borders/cards only where they clarify grouping. |

### Long-running and AI-assisted work

Category research points to five stable expectations:

1. The work persists while the user leaves and returns.
2. The system shows only status/checkpoints it actually observed, not a theatrical “thinking” animation.
3. Human approval is separate from the transcript when it changes cost or scope.
4. Partial progress and failure retain useful work.
5. Sources and exports stay connected to the research artifact.

The UI must not display a determinate percentage without a real denominator. This API emits `node_completed` after work, not `node_started`; after reload it has no intermediate backlog, and terminal frames do not identify a failing node. The truthful default is job-level status, elapsed time, last update, and the **last observed completed checkpoint** when one exists. Running after reload may have no known checkpoint; failure means “failed after the last observed checkpoint,” not “failed in this stage.” Incoming progress should update a stable region instead of pushing the report or moving controls.

## Accessibility research

The target is WCAG 2.2 AA plus task-based keyboard and screen-reader proof, not a perfect automated score.

| Standard or pattern | Relevant requirement | Product application |
|---|---|---|
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Current W3C accessibility recommendation; includes focus, target size, consistent help, redundant entry, and accessible authentication criteria in addition to earlier WCAG requirements. | Use AA as the release baseline and document any criterion that is not applicable to the private workspace. |
| [WCAG 1.4.10 Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) | Content should reflow without two-dimensional scrolling at a 320 CSS px equivalent, except where two-dimensional layout is essential. | Replace the permanent phone sidebar; wrap report tables in labelled horizontal regions rather than making the entire page pan. |
| [WCAG 1.4.11 Non-text Contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) | Required visual information in controls and graphics needs sufficient contrast. | Validate focus rings, input borders, stage rails, chart/status marks, and disclosure indicators—not text alone. |
| [WCAG 4.1.3 Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) | Status messages can be conveyed without moving focus when appropriate. | Announce material transitions such as awaiting approval, reconnected, failed, and complete; do not announce every SSE frame. |
| [WAI-ARIA APG — Landmarks](https://www.w3.org/WAI/ARIA/apg/practices/landmark-regions/) | Landmark regions need meaningful structure and labels. | Add skip link, labelled navigation, one `<main>`, and a report/article region; the current audit confirms `<main>` is missing. |
| [APG — Disclosure](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/) | A disclosure is a button with `aria-expanded` and optional `aria-controls`, with simple keyboard activation. | Use for history turns, advanced query controls, event diagnostics, and metric detail; connect triggers to stable panel IDs. |
| [APG — Menu Button](https://www.w3.org/WAI/ARIA/apg/patterns/menu-button/) | Menu roles carry specific focus and arrow-key behavior. | Either implement export with a tested accessible menu primitive or use a simpler disclosure/list of normal links; do not apply menu roles halfway. |
| [APG — Dialog Modal](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/) | Modal dialogs must contain focus, provide a labelled structure, and restore focus. | Use a dialog only for destructive confirmation or a truly blocking decision, not as the progress surface. |
| [APG — Alert](https://www.w3.org/WAI/ARIA/apg/patterns/alert/) | Alerts are for important, usually time-sensitive messages and should not be overused. | Use for submission/review failures, not routine progress. Persistent failures should also remain visible as ordinary content. |
| [APG — Tabs](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/) | Tabs require predictable focus/selection and are best when switching is fast. | If report/trace/source panels become tabs later, keep panels locally available and test automatic activation latency. |
| [APG — Grid](https://www.w3.org/WAI/ARIA/apg/patterns/grid/) | ARIA grid shifts keyboard navigation responsibility to the application. | Prefer a semantic table for future paper results; adopt a grid only if editable/cell-navigation behavior is genuinely required. |

### Required evidence later

- Automated: axe at component and route level, contrast checks, landmark/name/value checks.
- Keyboard: skip link, rail, composer, plan arrays, approve/revise/cancel, event disclosure, report headings/links/tables, export, deletion, error recovery.
- Screen reader: VoiceOver + Safari on macOS/iOS and NVDA + Firefox or Chrome on Windows.
- Reflow: 320 CSS px equivalent, phone landscape, 200%/400% zoom, long unbroken report content.
- Motion: `prefers-reduced-motion`, no motion-dependent status meaning, no live-region event spam.

## Performance research

| Source | Relevant evidence | Product implication |
|---|---|---|
| [web.dev — Core Web Vitals](https://web.dev/articles/vitals) | The recommended field thresholds are LCP ≤2.5 s, INP ≤200 ms, and CLS ≤0.1 at the 75th percentile, assessed separately for mobile and desktop. | Adopt these as product SLOs once real traffic exists. Local Lighthouse is only lab evidence. |
| [web.dev — Optimize LCP](https://web.dev/articles/optimize-lcp) | The LCP resource should be discoverable early and rendering/resource delays minimized. | Server-render the stable shell and initial history where practical; defer advanced export/visualization code. |
| [web.dev — Optimize CLS](https://web.dev/articles/optimize-cls) | Reserve space for dynamic content and manage font/image shifts. | Reserve stable progress, alert, and report-skeleton regions; do not insert stream notices above the reader's position. |
| [web.dev — Optimize INP](https://web.dev/articles/optimize-inp) | Break up or yield long main-thread work and avoid unnecessary rendering. | Batch stream updates; do not re-render a long Markdown report for every event; keep plan edits and navigation urgent. |
| [web.dev — Code splitting](https://web.dev/articles/reduce-javascript-payloads-with-code-splitting) | Route- and component-level splitting can reduce startup JavaScript. | Lazy-load advanced telemetry and future preview/graph surfaces; keep the question, plan, progress, and report core direct. |
| [web.dev — Virtualize long lists](https://web.dev/articles/virtualize-long-lists-react-window) | Large DOM lists can hurt rendering; windowing limits mounted rows. | Paginate conversations first; virtualize only when measured, with accessible result counts, focus, and scroll restoration. |
| [web.dev — bfcache](https://web.dev/articles/bfcache) | Eligible pages can restore navigation state rapidly. | Investigate the current conversation bfcache failure and preserve selected turn, filters, scroll, and draft on return. |

The measured local baseline already meets lab speed targets, so the revamp's performance risk is regression from new dependencies and rich surfaces—not a slow initial page. Accessibility and mobile usability are much more urgent than chasing an extra Lighthouse point.

## Mature design-system patterns

| Source | Transferable pattern | Use here |
|---|---|---|
| [Carbon — Data Table](https://carbondesignsystem.com/components/data-table/usage/) | Dense scanning, attached toolbar, selection, pagination, expandable detail | Future structured papers should use a semantic table with adjacent filters/actions, not card spam. |
| [Carbon — Loading](https://carbondesignsystem.com/components/loading/usage/) | Skeletons suit known structures; multiple simultaneous spinners add noise | Use one contextual run indicator and report/thread skeletons, not a spinner on every node. |
| [Carbon — Progress Bar](https://carbondesignsystem.com/components/progress-bar/usage/) | Determinate and indeterminate progress communicate different knowledge | Use a count/fraction only when backend events supply a denominator; otherwise show job status, elapsed time, and last observed completed checkpoint. |
| [Carbon — Progress Indicator](https://carbondesignsystem.com/components/progress-indicator/usage/) | User workflow steps differ from system-process progress | Question → Plan → Run → Report can be a trace; Run may disclose completed checkpoint events, while its current internal node remains unknown. |
| [Atlassian Design System — Components](https://atlassian.design/components) | Navigation, headers, tables, filters, empty states, flags/messages, skeletons, tokens, and focus have distinct roles | Define purpose-built primitives and severity semantics instead of one generic card/status style. |
| [Atlassian — Navigation System](https://atlassian.design/components/navigation-system/) | Current navigation supports structured product hierarchy and responsive behavior | Use a collapsible desktop rail and labelled mobile control, preserving selected-state and page identity. |
| [Elastic UI — Data Grid](https://eui.elastic.co/docs/components/data-grid/) | Grids can support many uniform columns, sorting, visibility, virtualization, fullscreen, and pagination | Start with a table; adopt heavier grid behavior only if real paper contracts and column needs justify it. |
| [Elastic UI — Page Template Guidelines](https://eui.elastic.co/docs/components/templates/page-template/guidelines/) | Stable page geometry and distinct empty/loading/error states improve continuity | Keep the workspace frame stable; permission, first-use, zero results, and system error must not share one placeholder. |
| [Elastic UI — Side Navigation](https://eui.elastic.co/docs/components/navigation/side-nav/) | Side navigation can become a compact labelled mobile disclosure | Replace the current always-visible 256 px mobile rail. |

## Analog-product comparison

| Product | What public first-party material establishes | Friction or boundary | Lesson for this product |
|---|---|---|---|
| **Elicit** | Persistent projects/sessions, an agent that plans and shows sources, leave/return, effort controls, systematic-review stages, table-centric evidence, exports | Multiple overlapping starting modes can increase mode selection; exact live error/a11y states were not verified | Strongest analog for durable work and human review. Keep one clearer session model and make the approved plan/cost trace explicit. |
| **Consensus** | Research Agent/Deep Search, Threads/history, compact evidence, citations, filters, multi-step reports | Product/mode naming changes can create ambiguity; detailed live failures were not publicly documented | Use compact scholarly scanning and visible research timeline, but fewer modes and a clearer approval boundary. |
| **Semantic Scholar** | Familiar paper-result hierarchy, sorting/filters, TLDR, influential citations, library/feeds, citation export, reader | Work context spans search, paper, reader, library, feed, and dashboard | Reuse scholarly conventions if structured papers arrive, while keeping report and research trace in one workspace. |
| **Connected Papers** | Seed search, similarity graph, selected-paper detail, prior/derivative discovery, accessible parallel paper list | Graph proximity is discovery, not claim-level evidentiary support; synthesis is outside the main workflow | A graph may be a later secondary artifact, never the primary report/provenance model. |
| **SciSpace** | Literature/deep review, tables and filters, structured summaries, cited reports, excerpts, notebooks, follow-up, export | A broad suite of tools can fragment the mental model and context | Keep source excerpts and reusable artifacts if the backend exposes them, but organize around one evolving session. |

### Analog sources read

- Elicit: [workflow chooser](https://support.elicit.com/en/articles/14757543-getting-started-with-elicit-which-workflow-or-tool-should-i-use), [Research Agent](https://support.elicit.com/en/articles/14756886-elicit-s-research-agent), [systematic reviews](https://support.elicit.com/en/articles/14759154-systematic-reviews-in-elicit), and [export](https://support.elicit.com/en/articles/14758189-export-your-data-from-elicit).
- Consensus: [product changelog](https://help.consensus.app/en/articles/11954907-consensus-product-changelog), [advanced search filters](https://help.consensus.app/en/articles/9922799-advanced-search-filters), and [Responsible AI](https://consensus.app/home/resources/consensus-responsible-ai/).
- Semantic Scholar: [product overview](https://www.semanticscholar.org/product), [FAQ](https://www.semanticscholar.org/faq), and [Semantic Reader](https://www.semanticscholar.org/product/semantic-reader).
- Connected Papers: [About](https://www.connectedpapers.com/about), [FAQ](https://www.connectedpapers.com/faq), and a [live graph example](https://www.connectedpapers.com/main/70acb0ee229593fffe73885f3004f24df38f74ec/A-Survey-of-Deep-Learning-for-Scientific-Discovery/graph).
- SciSpace: [Deep Review](https://scispace.com/help/en/articles/10864812-how-to-use-deep-review-for-advanced-literature-analysis-in-scispace) and [Literature Review](https://scispace.com/help/en/articles/10660587-how-to-conduct-a-literature-review-using-scispace).

Public analog documentation is evidence for interaction conventions, not permission to copy visual appearance, proprietary language, or unsupported backend features.

## Technology research

### Current and candidate versions

Versions below were verified against official package registries on 2026-08-27/28.

| Area | Repository now | Verified candidate | Recommendation |
|---|---:|---:|---|
| [Next.js](https://www.npmjs.com/package/next) | 16.3.3 | 16.3.3 | Retain; same-origin route handler is a security and stream/download boundary |
| [React](https://www.npmjs.com/package/react) | 19.2.8 installed | 19.2.8 | Retain; no evidence supports a framework rewrite |
| [TypeScript](https://www.npmjs.com/package/typescript) | 5.9.3 installed | 7.0.2 | Defer; TS 7 is a compiler/platform migration and should not be hidden inside the UI revamp |
| [Tailwind CSS](https://www.npmjs.com/package/tailwindcss) | 3.4.19 installed | 4.3.3 | Keep 3.x initially with semantic CSS variables; treat 4.x as a dedicated, reversible migration |
| [Vitest](https://www.npmjs.com/package/vitest) | 4.1.11 | 4.1.11 | Retain; add explicit coverage include/thresholds |
| [Testing Library React](https://www.npmjs.com/package/@testing-library/react) | 16.3.2 | 16.3.2 | Retain for behavior-focused component tests |
| [Radix Primitives](https://www.radix-ui.com/primitives) | — | root 1.6.7; Dialog 1.1.23 | Selective use for compound focus-intensive widgets; native controls otherwise |
| [TanStack Query](https://tanstack.com/query/latest) | — | 5.102.2 | Candidate for JSON server state; paid `POST /research` must explicitly disable retry; keep EventSource custom |
| [React Hook Form](https://www.react-hook-form.com/) | — | 7.86.0 | Candidate for dynamic plan fields, not the trivial question input |
| [Zod](https://zod.dev/) | — | 4.4.3 | Candidate for form/client schemas; not a substitute for API contract tests |
| [Storybook for Next.js/Vite](https://storybook.js.org/docs/get-started/frameworks/nextjs-vite) | — | 10.5.10 | Add for documented state matrix and interactions; production Next webpack build remains authoritative |
| [Mock Service Worker](https://mswjs.io/) | — | 2.15.0 | Add for JSON integration tests; use a deterministic stub HTTP/SSE service for EventSource if interception proves incomplete |
| [Playwright](https://playwright.dev/docs/intro) | — | 1.62.1 | Add desktop/mobile and Chromium/Firefox/WebKit projects |
| [axe-core](https://www.npmjs.com/package/axe-core) | transitive only | 4.13.0 | Add direct component/browser adapters; supplement with manual keyboard/screen-reader evidence |
| [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci) | — | 0.15.1 | Add state-specific budgets after deterministic browser fixtures exist |
| [size-limit](https://github.com/ai/size-limit) | — | 13.0.3 | Candidate for route/client entry budgets; generate a readable report in CI |
| [openapi-typescript](https://openapi-ts.dev/) | — | 7.13.0 | Generate JSON endpoint types and detect drift, with manual SSE/export/error overlay |
| [openapi-fetch](https://openapi-ts.dev/openapi-fetch/) | — | 0.17.0 | Lightweight typed client candidate behind the repository's own normalization layer |

Alternative: [Orval](https://orval.dev/) 8.26.0 can generate client and mocks, but openapi-typescript/openapi-fetch is a smaller fit for this compact, irregular API. Neither tool can infer the undocumented auth, SSE, export, or error behavior.

### Preliminary stack recommendation

This is research input, not a Gate 2 architecture decision:

- Next 16 + React 19 + TypeScript 5.9.
- Tailwind 3 for layout utilities, backed by semantic CSS custom-property tokens and component-owned styles.
- Native HTML first; selected Radix primitives for dialog/menu/popover/tooltip only when their full interaction model is needed.
- TanStack Query for idempotent JSON reads and carefully configured mutations; the existing custom EventSource adapter remains separate.
- React Hook Form + Zod only for the dynamic plan editor.
- Storybook + Vitest/Testing Library + MSW for component/integration states.
- Playwright with a deterministic stub API/SSE server for cross-browser E2E and visuals.
- axe, Lighthouse CI, and route-size budgets as independent gates.
- OpenAPI generation for the documented JSON surface plus handwritten/tested overlays.

### Why not upgrade everything first

Tailwind 4 changes browser floors, PostCSS/import setup, Preflight behavior, default borders/rings/shadows/radii, and hover handling. TypeScript 7 is a native rewrite with material tooling implications. Combining either with a mobile shell replacement, data-layer migration, and visual system would make regressions harder to isolate and rollback. They should be separate ADR-backed changes only if their benefit exceeds migration cost.

## Design requirements derived from research

1. Persistent, responsive workspace shell with labelled navigation and one dominant New Research action.
2. Question-first composer with visible constraints and no automatic paid retry.
3. Dedicated plan-review surface outside chat bubbles.
4. Truthful checkpoint trace, job status, elapsed/last-update context, explicit unknown-after-reload state, reconnect, and stable diagnostics disclosure.
5. Report-first reading hierarchy with section navigation, contextual metrics, and nearby export.
6. Distinct first-use, empty history, expired job, offline, rate-limit, unauthorized, partial failure, full failure, and success states.
7. Keyboard-visible actions, semantic landmarks, restrained live regions, reduced motion, and phone reflow.
8. Semantic design tokens and a signature research trace; no generic dashboard card grid.
9. Deterministic state fixtures and independent evidence before backend or deployment work.
10. No simulated claim/source evidence until the API exposes a contract for it.

## Open research questions

- Do users need one shared private workspace or future per-user ownership? This materially changes navigation, deletion, privacy copy, and deployment.
- Should failed jobs with a non-empty partial report remain readable/exportable?
- Which backend pipeline event names are stable product language and which should be mapped to user-facing stage names?
- Can a future API expose structured papers, citations, evidence claims, and plan snapshots without parsing Markdown?
- What real mobile usage and report-length distribution should set virtualization and responsive priorities?
- What production field telemetry is acceptable for a private research tool, and where should it be hosted?
