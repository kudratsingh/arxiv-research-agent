# Daily research workspace — implementation status

The owner adopted this direction on 2026-11-02 and authorized W0/W1 first:
**Today → reader → saved question → return visit**, desktop and phone.
The full destination includes real grounded summaries and guided deep dives.
Paid services require a separate, concrete approval before activation.

| Card | Branch / concrete output | Evidence / remaining boundary |
|---|---|---|
| W0 | `codex/daily-workspace-preview`, base `88d283d`; ADR 0103; direction kit preserved | Shared `main` remains unchanged. Gates below pass locally. ADR number is proposed pending reconciliation before merge |
| W1 | Opt-in `/today`, `/interests`, `/library`, `/library/items/[id]` | Connected fictional preview; browser-only continuity. Eight desktop/mobile browser cases pass, including keyboard-only completion, dark theme, export and return continuity; owner experience review pending |
| W2 | Next: principal-scoped Postgres interests, canonical items and reading state | Browser preview data must have an explicit import/export path; no silent migration |
| W3–W6 | Bounded arXiv/approved RSS metadata intake, finite ranking, manual reading, local catch-up | Source selection, adapter terms, schema/identity/restart gates and schedule confirmation before activation |
| W7 | Independent source spans, factual-support/settings/artifact/cost corrections and admission | Required before generated-quality claims; fixes listed in the dated state review remain open |
| W8–W9 | Real grounded summaries and guided deep dives | Exact source/model/usage envelope and separate owner spending approval; actual retained-source/provider walkthrough required |
| W10–W12 | Questions, assumptions and experiment proposals; daily-use pilot; optional expansion | Follow observed owner workflow. No automatic code execution, publishing or external delivery |

## Baseline

- Remote `main` verified at `88d283d`; shared checkout at `dbd4bb8`, six commits behind.
- Incoming kit/archive compared byte for byte; archive integrity passed.
- Latest remote CI `41434132708` failed the dependency audit and cancelled its
  Python test job. This is not a green baseline.
- W0 production audit initially found Next.js critical plus sharp and
  source-map-js high. Isolated branch updates Next.js/config to 16.4.4, sharp
  to 0.35.5, source-map-js to 1.2.2. Production high/critical count after these
  updates is zero. Development-tree high findings were also repaired through a compatibility-tested
  Lighthouse/browser update and compatible patches. Both high/critical audits
  pass with zero exceptions; the audit implementation is unchanged.
- Preview uses no API, provider or source connector. Existing workbench and
  auth/demo surfaces remain reachable in their original route groups.

## Runnable owner walkthrough

From this branch's `web/` directory, run `npm run dev:workspace` and open
`http://127.0.0.1:3126/today`. It binds to loopback and forces the disabled key.

1. Open Interests. Search or browse the full catalogue; use the suggested ML
   lens or select your own topics. Add a custom research question if useful.
2. Return to Today, choose a reading budget and inspect the source-check gap
   and the reason attached to the first item.
3. Open “Read & investigate”. Inspect the attributed fictional abstract and
   the explicit unavailable full-text/generation boundaries.
4. In Your notes, edit and save a question. Return to Today; follow its thread
   back to the source. Reload and reopen from Library to test continuity.
5. Export your notes as Markdown. On a phone, use Source / Understand / Your
   notes to move between panes; the selected section is retained.

The fictional material is a design instrument, not current news or a research
result. Source originals will be real links only after bounded intake exists.
No paid approval is requested to review this milestone. Initial interests and
current research questions are being collected asynchronously and remain editable.

## Final local evidence for W0/W1

| Gate | Observed result |
|---|---|
| Clean `npm ci --ignore-scripts` | Pass with the repository's npm version |
| Typecheck, lint, generated API types | Pass; no API/schema change |
| Complete web + Storybook suite | 3,600 passed across 169 files |
| Web coverage | Statements 98.56%, branches 95.32%, functions 90.98%, lines 99.50%; all existing floors retained |
| Browser walkthrough | 8 passed at desktop and 390 px; axe, keyboard-only flow, source failure, dark theme, export, reload and back/forward |
| Production screenshot receipt | Zero API requests and zero page errors; desktop/mobile source, interests and Today captures |
| Production build and route budgets | Pass; all existing JavaScript ceilings retained; four new route ceilings and documented CSS movement |
| Storybook static build | Pass with patched tooling |
| Production and full dependency audits | Zero high/critical findings, zero exceptions; 33 moderate findings remain visible |
| Python coverage/diff gate | 5,582 passed, 54 skipped, 53 deselected; total coverage 94.14%. No Python source lines changed, so patch coverage is not applicable |
| Python mock workflow tier | 53 passed |
| Scripted research regression | 20/20 succeeded, zero errors, $0.0000; no live model evidence |
| Registry parity | 260 objects, zero mismatches; no registry changes |
| Ruff | Pass |

Local review artifacts live under `outputs/workspace-preview/` in the isolated
worktree. They include clean production screenshots and the walkthrough receipt.
`http://127.0.0.1:3127/today` is the production preview while its process is running;
use `npm run preview:workspace` to restart it after `npm run build`.

The default application keeps the preview disabled. Its browser suite lives
outside the seeded stack's test directory and has a dedicated, bounded CI step,
so neither suite accidentally runs with the other's configuration. No local
Docker stack or owner container was touched. No model, paid service, deployment,
external notification or merge was activated. The next meaningful review is
the briefing density and reader/notebook balance before expanding navigation.
