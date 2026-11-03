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
| W5 | Real source reader, retained abstracts/feed excerpts, Unicode-safe anchors, durable questions/notes/actions, source version choice and export | Desktop/mobile/keyboard and failed-save recovery observed; bounded PDF extraction helper tested with synthetic files. Selected-page scientific sample now retained; inline PDF rendering remains deferred |
| W6 | Durable schedules, owner/date occurrences, leased one-shot worker, bounded retries, single catch-up and atomic in-app intent | DST, racing workers, queued-before-sleep, pause/recovery tests. Recurrence remains disabled; continuous worker packaged disabled; image deployment and owner's time confirmation remain pending |
| W7 | Independent retained materials/spans; explicit factual-check boundary; actual emitted calibration artifacts; role/revision estimator; atomic spend reservations/cancellation/recovery | Model-free/fake-provider tests. Fake executor and qualification-only wire adapter implemented/tested offline; actual provider quality measurement and historical metric certification remain pending; remaining launch conditions are in the approval packet |
| W8–W9 | Real grounded summaries and guided deep dives | Exact source/model/usage envelope and separate owner spending approval; actual retained-source/provider walkthrough required |
| W10–W12 | Questions, assumptions and experiment proposals; daily-use pilot; optional expansion | Follow observed owner workflow. No automatic code execution, publishing or external delivery |

## Readiness follow-up from reviewed PR283 (2026-11-03)

Verified reviewed/current remote head `a7ec430`; no subsequent changes at start.
Its nine green checks belong to that head, not this follow-up. New isolated
branch `codex/daily-workspace-readiness` is stacked on283. Owner data and all PRs
remain unmerged; provider contacts/spend0 and recurrence disabled.

- Review fixes committed `c4c2a64`: all243 authored study areas have literal
  matching terms;26 external fields and4 domains stay browse-only. Exact-version
  retained availability drives cards/Radar/Reader without rewriting immutable
  source metadata. PDF excerpts open on entry, with selected-page limits.
- Today brings a compact saved-question return above the shortlist. A390px
  browser regression checks a non-empty question and first reading title within
  the initial viewport; allocation/identifiers/receipts are disclosed on demand.
- Qualification-only actual wire adapter binds model/settings/schema/context,
  input count estimates with25% headroom, output/call limits, one named job per
  approval, reservations and split workflow/checker/unknown accounting. Contacts
  are journalled before dispatch; cancellation and lost completion are fenced.
  It reuses retained selection, structured request building and grounding checks;
  the original fake executor remains a separate zero-dollar instrument.
- Read-only packet builder exports four exact initial wire/count requests plus
  24 representative claim/span cases. Human labels and checker judgments blank.
  Dynamic check/repair bodies are sealed after prior outputs exist, never
  invented in advance. No count endpoint or provider client was contacted.
- Correct sequence: approve a bounded measurement/qualification experiment,
  measure actual checker failures, then decide about everyday generation with
  adequate quality evidence. The candidate remains3summaries/1excerpt study,
  max16Messages+16count contacts, estimated raw ceiling$0.792, reservations$1.15,
  proposed trial/day/month cap$1.25. Everything remains unapproved.

Focused checkpoint: Python66passed for adapter/packet/admission; new adapter99%
coverage, availability100%; frontend142workspace tests, strict typing/lint;
14durable browser flows and compact2/excerpt2 passed in the isolated database.
Production desktop/mobile16 and scientific excerpt4 passed on isolated real
Postgres, including automatic entry and exact saved passages. Full frontend3714
passed with zero skips and coverage floors intact; CSS17378B stays below the
unchanged17408B ceiling. The first unrestricted Python patch run caught a stale
API-equality assertion: the revised test pins immutable stored metadata/notes
while explicitly requiring the new derived availability. A superseded local
project-coverage run was interrupted to strengthen the final HTTP-construction
approval/count-receipt guard;5961passed/54skipped at interruption, no green claim.
Both full gates are repeated after that fix. Final-head local/CI results belong
to the checkpoint receipt; these focused results are not a green CI claim.

See [readiness walkthrough](20-readiness-and-qualification-walkthrough.md) and
[unexecuted trial](15-grounded-generation-approval-packet.md). The historical
follow-up below describes the earlier instrument and earlier envelope only.
Real grounded summaries and guided dives remain the next product milestone.

## Current follow-up: personal workflow and fake executor (2026-11-03)

Branch `codex/daily-workspace-next` starts at the unchanged reviewed #282 head
`403e5fa`. Shared owner checkout/data/preferences are preserved; #281/#282 stay
draft/unmerged. The workspace ADR proposal remains unnumbered.

- Review A: database-ordered latest activity, earlier-question edits, exact
  work/version/anchor return and editable pins. Two-paper, reload, Reader and
  Library cases have repository/component/desktop/390 px regression coverage.
- Review B: all eight formerly empty authored ML groups expand to inspectable
  descendant terms. Broad navigation and active/limited/unconnected monitored
  coverage are explicitly distinct; no comprehensive monitoring claim.
- Review C: exploration caps the final count, rounded down, with stored receipts
  and honest historical editions. 15/45-minute, zero and sparse cases are tested.
- Ten-item real-candidate review, blank initial judgments, explicit revision-aware
  saves and optional reasons. Read-only owner packet is under
  `outputs/workspace-next/owner-usefulness-review-10.{md,json}`.
- Executable fake-only grounded pipeline, durable request/stage/result binding,
  split workflow/checker/unknown accounting, reservations, cancellation, lease
  recovery, source invalidation, one repair plus mandatory recheck. Paid endpoint
  remains403 before SDK construction. No actual model/checker quality measured.
- ReAct v3 and Self-RAG v1 retained selected pages with immutable provenance,
  original-page/Unicode anchors and visually inspected extraction limitations.
  Exactly two PDF GETs,2,038,932 bytes; no source instructions/code executed.
- Continuous worker module, opt-in Compose profile, health, startup/shutdown and
  private backup/disposable restore path. Recurrence hard false; no worker
  container/image build or automatic delivery is claimed.
- Proposal refreshed after exact fake requests were inspectable:3summaries plus
 1excerpt study, max16calls including repair rechecks, estimated raw max$0.768,
  rounded job reservations$1.00 and proposed trial/day/month caps$1.25. These
  are unapproved design bounds, not measured tokens or spend.

Production build and all existing route/CSS ceilings pass; web3711/3711 with
zero skips, statements98.23%, branches94.28%, functions92.04%, lines99.34%.
The documented suite-count check caught stale158-file prose; README/config now
record177files/3711tests. Function coverage floor ratchets88.8→91.8; other
floors and all coverage inputs/tier selections remain intact.
Production standalone desktop/mobile14 and real scientific-PDF2 pass using only
an isolated verification principal/database. Two substantive integration defects
were reproduced and fixed: lost unknown accounting on cancelled/failed fake
completion, and relocated backup sidecars validating the wrong path. Focused
regressions pin both; no gate/floor was lowered. Final Python/full CI attribution
belongs to the final commit's receipt/checks, pending at this documentation
checkpoint; the old #282 CI is not evidence for this branch.

See [connected walkthrough and remaining sequence](16-review-and-executor-walkthrough.md),
[full-text inspection](18-fulltext-qualification.md),
[everyday operations](19-everyday-operation.md) and
[unexecuted generation proposal](15-grounded-generation-approval-packet.md).
Owner usefulness/experience review, paid adapter/token/checker measurement,
specific spending GO and optional schedule activation remain outstanding.

### CI-discovered Library correction

First remote run `41578188828` at `efd545b` passed eight jobs and failed the
new durable browser return case on both viewports. Trace data proved the edited
question was committed and present in fresh API state, but the URL said
`view=notes` while Library displayed Saved. The real-corpus local test masked
this because its edited work was already saved. The clean three-work CI seed
reproduced8passed/2failed/4notrun. This is recorded as a real UI defect.

Library now derives its filter from the reactive router query, with the required
Suspense boundary. A new unread-work regression failed before the fix and passes
afterward; the browser explicitly checks Notes on return and preserves the
edited-body/version assertions and existing timeout. The same seeded production
suite now passes14/14; full web3711/177passes with zero skips and unchanged
floors. Final Python patch gate and replacement exact-head CI follow this
source checkpoint. No blind CI rerun, lowered assertion, extra wait or owner-data
write was used to hide the failure.

## Historical autonomous batch evidence (2026-11-02)


Live follow-up branch: `codex/daily-workspace-live`, stacked on preview PR #281.
Run **`bash scripts/workspace-local.sh run`** from this worktree, then open
**http://127.0.0.1:3137/workspace/today**. The original fictional preview is on
port 3127; its new JSON export retains the browser original for explicit import.
The owner checkout remains at `dbd4bb8` with its original local changes.

| Check | Observed result | Limits |
|---|---|---|
| Preview CI diagnosis | Original run `41468750549` cancelled at the explicit 15-minute ceiling; report module 523.4 s, no evidence of a hung DB | Remaining Python stages were unrun in that original run |
| Preview CI repair | Shared real 300-episode report retains all 57 tests and 344 assertions; targeted 127 tests, 256.24 → 173.46 s; all 9 jobs green at `139e065`, Python 15m47s | Original cancellation remains recorded; every tier, coverage input and floor is retained |
| Live follow-up CI checkpoint | All 9 jobs green at `5353eff`, run `41494092381`: Python 5,855 passed / 1 skipped / 53 deselected, patch 99%; Python e2e 53 passed; fixture browser 8 passed; full legacy browser matrix 410 passed / 73 skipped | This checkpoint predates the additional durable browser CI stage; later-head results are tracked separately, never inferred from this run |
| Mandatory Python patch gate | 5,814 passed, 54 skipped, 53 e2e deselected; project 94.54%, reported patch 99% | 54 local legacy Postgres-binary skips remain; new workspace integration ran against real isolated Compose Postgres |
| Package coverage floors | API 88 ≥ 86, agents 96 ≥ 92, security 100 ≥ 97, eval 95 ≥ 91 | Same full-source coverage report, floors unchanged |
| Python e2e / scripted research | 53 passed; 20/20 scripted episodes, 0 errors, $0.0000 | Scripted research is a regression check, not live generated-quality evidence |
| Registry / typing / lint | 260 objects, 0 mismatches; strict mypy 153 modules; Ruff pass | No registry object or funded protocol digest changed |
| Web full coverage | 172 files, 3,658 tests; statements 98.32%, branches 94.01%, functions 91.50%, lines 99.40% | Original coverage inputs and floors unchanged |
| Real browser | 8 standalone production cases passed at desktop 1440 and mobile 390, including keyboard, durable save/reload/export, outage/recovery and receipts/axe | Source outage is controlled-test evidence; no real source outage occurred during the five integrated reads |
| Durable browser CI wiring | Same eight cases run in the existing isolated API/Postgres CI stack, with an explicit zero-request synthetic metadata seed; PR trigger also covers stacked `codex/**` bases | Synthetic CI metadata is separate from observed live-feed evidence; results must match the exact head |
| CI seed preservation | 12 focused real-Postgres checks pass: stable replay, versions/editions, private edits/anchors, zero requests, guards before pool lookup and refusal of another owner's private non-fixture data | Superseded local full gate was interrupted to add the last preservation regression; the fresh mandatory gate passed with 5,814 tests. Eight cases also passed against a new isolated API/database with this seed (7.3 s), then its services/database were removed |
| Build / budgets / Storybook |Production and static Storybook pass; all six new route JS sizes 153–161 kB; CSS 16,309 B | New route ceiling 166 KiB; CSS ceiling 15,872 → 17,408 B is documented; every old JS ceiling remains unchanged |
| Security audit | 0 high/critical in production and full dependency trees; 0 exceptions | 33 moderate findings remain |
| Persistence | App restart retained real records/notes; initial restore compared 83 works / 83 versions / 14 QA notes / 83 materials. After normalization and QA cleanup, all 20 workspace tables compared equal: 83 works / 158 versions / 0 active notes / 158 materials | Each restore used a new disposable database, removed afterward; owner data/volume not replaced; both private backups retained |
| Normalization correction | 75 captured arXiv records reprocessed locally at 0 requests; 83 works remain, 158 immutable versions/materials | RSS announcement dates no longer imply submission/update timestamps; original revisions and note context retained |
| Private QA cleanup | 32 timestamped browser-test notes exported and removed from active view; history retained; original pre-test notes 0 | No nonmatching owner note changed; future write-tests should use a separate verification principal |

The controlled two-worker race also passes against real Postgres: one ready
occurrence, one edition and one in-app intent. Recurrence, external delivery,
paid generation and approval records remain off. Final-source receipts are in
`outputs/workspace-live/`; screenshots are local artifacts, not committed.

See [live walkthrough](14-live-local-walkthrough.md) and the explicitly
[unexecuted generation proposal](15-grounded-generation-approval-packet.md).
The historical claim-support primary, full instrument enforcement, real checker
calibration, paid adapter/settings/token enforcement, exact token measurements and real checker
qualification remain unfinished. The follow-up above adds a fake executor, disabled
worker packaging and a bounded scientific extraction sample.
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
