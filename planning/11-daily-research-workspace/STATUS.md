# Daily research workspace — implementation status

The owner adopted this direction on 2026-11-02 and authorized W0/W1 first:
**Today → reader → saved question → return visit**, desktop and phone.
The full destination includes real grounded summaries and guided deep dives.
Paid services require a separate, concrete approval before activation.

| Card | Branch / concrete output | Evidence / remaining boundary |
|---|---|---|
| W0 | `codex/daily-workspace-preview`, base `88d283d`; unnumbered workspace ADR proposal; direction kit preserved | Shared `main` remains unchanged. Gates below pass locally. Proposal deliberately unnumbered; ADR 0103 remains reserved for LE-E |
| W1 | Opt-in `/today`, `/interests`, `/library`, `/library/items/[id]` | Connected fictional preview; browser-only continuity. Eight desktop/mobile browser cases pass, including keyboard-only completion, dark theme, export and return continuity; owner experience review pending |
| W2 | Postgres migrations/history, named principal, optimistic revisions, retry ledger, exact version notes and explicit browser/file import | Real isolated Postgres and owner A/B tests; app restart and backup/restore observed. Broader identity qualification and owner experience review remain pending |
| W3 | Five bounded metadata feeds and private manual links; page/receipt/validator transaction, conditional requests, safe pinned TLS and Retry-After | 83 real works; 5 integrated requests plus one earlier connector probe. Replay made zero requests and no duplicate works; three arXiv windows remain partial |
| W4 | Real Today and Radar, transparent lexical signals, finite editions, exclusions, read/dismiss/snooze/undo and frozen cursor pages | Chronological/keyword comparison sample has blank owner labels. Edition versions/profile/coverage are pinned. Personal usefulness remains unmeasured |
| W5 | Real source reader, retained abstracts/feed excerpts, Unicode-safe anchors, durable questions/notes/actions, source version choice and export | Desktop/mobile/keyboard and failed-save recovery observed; bounded PDF extraction helper tested with synthetic files. No new scientific full-text acquisition or inline PDF viewer |
| W6 | Durable schedules, owner/date occurrences, leased one-shot worker, bounded retries, single catch-up and atomic in-app intent | DST, racing workers, queued-before-sleep, pause/recovery tests. Recurrence remains disabled; continuous worker deployment and owner's time confirmation remain pending |
| W7 | Independent retained materials/spans; explicit factual-check boundary; actual emitted calibration artifacts; role/revision estimator; atomic spend reservations/cancellation/recovery | Model-free/fake-provider tests. No generation executor, actual provider quality measurement or historical metric certification; remaining launch conditions are in the approval packet |
| W8–W9 | Real grounded summaries and guided deep dives | Exact source/model/usage envelope and separate owner spending approval; actual retained-source/provider walkthrough required |
| W10–W12 | Questions, assumptions and experiment proposals; daily-use pilot; optional expansion | Follow observed owner workflow. No automatic code execution, publishing or external delivery |

## Autonomous batch evidence (2026-11-02)

Live follow-up branch: `codex/daily-workspace-live`, stacked on preview PR #281.
Run **`bash scripts/workspace-local.sh run`** from this worktree, then open
**http://127.0.0.1:3137/workspace/today**. The original fictional preview is on
port 3127; its new JSON export retains the browser original for explicit import.
The owner checkout remains at `dbd4bb8` with its original local changes.

| Check | Observed result | Limits |
|---|---|---|
| Preview CI diagnosis | Original run `41468750549` cancelled at the explicit 15-minute ceiling; report module 523.4 s, no evidence of a hung DB | Remaining Python stages were unrun in that original run |
| Preview CI repair | Shared real 300-episode report retains all 57 tests and 344 assertions; targeted 127 tests, 256.24 → 173.46 s; all 9 jobs green at `11154b7`, Python 15m37s | Latest `139e065` only moves the ADR proposal unnumbered; its new remote CI is tracked separately |
| Mandatory Python patch gate | 5,800 passed, 54 skipped, 53 e2e deselected; project 94.54%, reported patch 99% | 54 local legacy Postgres-binary skips remain; new workspace integration ran against real isolated Compose Postgres |
| Package coverage floors | API 88 ≥ 86, agents 96 ≥ 92, security 100 ≥ 97, eval 95 ≥ 91 | Same full-source coverage report, floors unchanged |
| Python e2e / scripted research | 53 passed; 20/20 scripted episodes, 0 errors, $0.0000 | Scripted research is a regression check, not live generated-quality evidence |
| Registry / typing / lint | 260 objects, 0 mismatches; strict mypy 153 modules; Ruff pass | No registry object or funded protocol digest changed |
| Web full coverage | 172 files, 3,658 tests; statements 98.32%, branches 94.01%, functions 91.50%, lines 99.40% | Original coverage inputs and floors unchanged |
| Real browser | 8 standalone production cases passed at desktop 1440 and mobile 390, including keyboard, durable save/reload/export, outage/recovery and receipts/axe | Source outage is controlled-test evidence; no real source outage occurred during the five integrated reads |
| Build / budgets / Storybook |Production and static Storybook pass; all six new route JS sizes 153–161 kB; CSS 16,309 B | New route ceiling 166 KiB; CSS ceiling 15,872 → 17,408 B is documented; every old JS ceiling remains unchanged |
| Security audit | 0 high/critical in production and full dependency trees; 0 exceptions | 33 moderate findings remain |
| Persistence |App restart retained real records/notes; private backup restored 83 works / 83 versions / 14 notes / 83 materials and compared equal | Restore check database removed; owner data/volume not replaced |
| Normalization correction | 75 captured arXiv records reprocessed locally at 0 requests; 83 works remain, 158 immutable versions/materials | RSS announcement dates no longer imply submission/update timestamps; original revisions and note context retained |
| Private QA cleanup | 32 timestamped browser-test notes exported and removed from active view; history retained; original pre-test notes 0 | No nonmatching owner note changed; future write-tests should use a separate verification principal |

The controlled two-worker race also passes against real Postgres: one ready
occurrence, one edition and one in-app intent. Recurrence, external delivery,
paid generation and approval records remain off. Final-source receipts are in
`outputs/workspace-live/`; screenshots are local artifacts, not committed.

See [live walkthrough](14-live-local-walkthrough.md) and the explicitly
[unexecuted generation proposal](15-grounded-generation-approval-packet.md).
The historical claim-support primary, full instrument enforcement, real checker
calibration, actual generated executor, exact token measurements, continuous
worker packaging and representative full-text acquisition remain unfinished.
Owner review of usefulness and the connected experience remains pending.

## W0/W1 checkpoint evidence (preview PR #281)

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
