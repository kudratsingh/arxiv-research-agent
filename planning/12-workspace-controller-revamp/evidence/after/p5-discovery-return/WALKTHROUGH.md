# G5 — discovery and returning to saved research

Application **`ade234b48520782d32e388e16a3cb811f8a2cf2b`**, Radar work order `734773f`, baseline `2c06bde`.
The [application manifest](application-tree.json) binds the exact checked bytes
to this commit. The later evidence commit changes no application code.

Open **http://localhost:3148/workspace/radar?q=agent&days=0** or
**http://localhost:3148/workspace/library?view=notes**.
This is **Design preview · synthetic sample papers**: real local API/Postgres
persistence with deliberately authored offline records. It is not a live source
check, scientific result, generated summary or owner usefulness measurement.
The explicit synthetic flag controls wording; no hostname or ID heuristic.
Your original3137/API8137/PG15438 workspace and preferences remain separate.

## Radar → page two → Reader → return

1. Open Radar at1440×1000 or390×844. At mobile width open Queue & controls for
   filters and the results queue. The stage contains one full available abstract,
   stored matching reasons where present, and the exact evidence limit.
2. Apply `agent` with All stored dates. The preview has29 matches:20 then9.
   The first successful response pins `as_of` in the URL. Select queue rows or
   use Previous/Next and `j`/`k` outside fields. Focus-only steps do not refetch
   items or add browser history entries.
3. At the last result on the page, Next paper is disabled and the sole
   **Next page →** appears in the player area. It preserves filters/cutoff and
   clears the previous page's focus. First page remains in the sidebar.
4. Open Read. Reader receives the exact version and passage. Use **← Radar**:
   query, filters, cursor, cutoff and focus return. Reload and Back/Forward keep
   the corresponding stored window. Unknown focus resolves deterministically.
5. Search or `/` opens the compact mobile composer. Its value follows Radar's
   query. A new query preserves source/date/access/reading filters and starts a
   new observation window; paging and old focus are cleared. Local slash
   commands retain their existing behavior. Fields do not trigger paper keys.
6. An in-flight search hides the previous result. A failed request shows an
   unavailable state and explicit Retry; it is not a successful empty search.
   A successful zero-match window has its separate empty heading and Jazzy.

## Library Notes → exact passage → return

1. Choose Saved, With notes or questions, Read, Archived or All personal state
   in the single native Library view select. On mobile it is in the drawer.
   Selection closes the drawer. All means personal reading/note state, not every
   stored Radar candidate.
2. One focused paper remains in the stage. In Notes view **every notebook
   entry in that view** stays present, with the focused source first. This
   includes the separate unread source with a saved question. Other views show
   the focused work's associated questions, notes and proposed next actions.
3. Open the older-version question's **Resume this question →**. The preview
   demonstrates `arxiv:2611.99001:v1`, `abstract:36:68`, while a newer version
   remains available. Reader targets that exact source version, entry and
   passage. Nothing silently moves an annotation to a newer source.
4. Use **← Library**. Its URL remains exactly `?view=notes`, following the kit's
   strict return contract. The selection is remembered per principal/view in
   this browser session. Explicit queue choices also set `?focus=` for reload
   and history. Opening another work's note remembers that work for return.
5. Save/Unsave, Dismiss, Snooze and Undo live **only in the bottom bar**. The
   stage has no second set. Failed writes keep focus/state; successful changes
   update the queue and Undo returns to the affected source. Reading, quick add
   and import operations are mutually guarded to avoid stale snapshot races.
6. Scroll to read the remaining abstract/evidence and later notes. The final
   abstract line, evidence block and last Resume link were explicitly scrolled
   above the fixed player and checked for visibility/hit access at390px in
   both themes; no claim that all lower content fits in the first viewport.

## Quick add, explicit import and export

Quick add remains in the sidebar with its original request body. The real API
rejected reserved `.invalid` input without clearing it or writing a work; an
acceptable metadata-only placeholder was then saved twice as one logical work.
This normalization did not fetch the public page or run a model.

Open **Import preview notes** to load the transfer interface. It stays mounted
when closed, retaining pasted JSON, preview and retry state. Opening does not
preview or apply an import. Use Preview browser import or the file/paste flow,
inspect conflicts, then Confirm import. The original/export remains retained;
profile import is an explicit opt-in. The real API audit repeated the same
confirmed import without duplicating its fictional-provenance note or changing
its profile. No owner records were imported.

**Export notes as Markdown ↗** exists once, in the Shell footer. Open the mobile
drawer to reach it. The real download audit verifies questions and exact source
version/passage markers. Existing API schemas, revision and digest/idempotency
contracts are unchanged.

## Screenshots and receipts

| Surface | Desktop dark | Desktop light | Mobile dark | Mobile light |
|---|---|---|---|---|
| Radar | [view](preview/desktop-dark-radar.png) | [view](preview/desktop-light-radar.png) | [view](preview/mobile-dark-radar.png) | [view](preview/mobile-light-radar.png) |
| Library Notes | [view](preview/desktop-dark-library-notes.png) | [view](preview/desktop-light-library-notes.png) | [view](preview/mobile-dark-library-notes.png) | [view](preview/mobile-light-library-notes.png) |

[Dark mobile drawer](preview/mobile-dark-library-drawer.png) ·
[light mobile drawer](preview/mobile-light-library-drawer.png).
Captures use DPR2. Viewports are emulated, not physical-phone acceptance.

The [guarded walkthrough](walkthrough-audit.json) uses a **different** DB and
principal (`controller-p5`,3149/API8149), with27 synthetic works before its two
named question writes. Its actual backend window is20+6, distinct from the
preview's20+9. [Page-two captures](walkthrough/ci-synthetic-mobile-dark-radar-page2.png)
and [Notes captures](walkthrough/ci-synthetic-mobile-dark-library-notes.png)
belong to that CI fixture, not owner questions. The separate [tools audit](tools-audit.json)
then adds one manual metadata work and one preview work/note, ending at29 works
and three synthetic questions. It preserves the two original verification
questions, source versions and profile; human usefulness labels remain blank.

[Raw live regression](live-e2e.txt) · [preview audit](preview-audit.json) ·
[lower-content reachability](reachability.json) · [P5 axe](p5-axe.json) ·
[Today density](today-density.json) · [Reader baseline axe](reader-baseline-axe.json) ·
[verification summary](verification.json) · [fixture setup](fixture-setup.json).
The setup receipt explicitly distinguishes direct backend-function fixture
checks from the later browser/API acceptance results.

## Start or reproduce locally

The preview is already running:

```bash
open 'http://localhost:3148/workspace/radar?q=agent&days=0'
open 'http://localhost:3148/workspace/library?view=notes'
```

After stopping **only the existing isolated3148 frontend**, restart its built
server from this worktree. After a future production build, copy static/public
assets completely **before** starting Next:

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller/web
cp -R .next/static .next/standalone/.next/
WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1 WORKSPACE_SYNTHETIC_PREVIEW=1 \
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
WORKSPACE_SCHEDULE_APPROVED=false NEXT_TELEMETRY_DISABLED=1 \
API_INTERNAL_BASE=http://127.0.0.1:8148 \
ARXIV_API_KEY=sk_controller_p5_preview_local_preview_disabled \
HOSTNAME=127.0.0.1 PORT=3148 node .next/standalone/server.js
```

If the isolated API needs restarting, use a second terminal. Preserve the
existing populated database; never seed over it:

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
ENABLE_WORKSPACE=true ENABLE_API_AUTH=true WORKSPACE_SCHEDULE_APPROVED=false \
API_KEYS=controller-p5-preview:sk_controller_p5_preview_local_preview_disabled \
POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p5_preview \
WORKSPACE_RATE_DATABASE_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_controller_p5_preview \
OMP_NUM_THREADS=1 /Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
-m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8148 --no-access-log
```

Controller Postgres is the existing isolated `arxiv-controller-p0` Compose
project at15458, config `/private/tmp/arxiv-controller-stack/compose.yaml`.
The previous P4 `workspace_rich` DB remains preserved. Do not touch owner
3137/8137/15438, and do not use source-refresh controls on this synthetic stack.

Read-only audit commands from the worktree root:

```bash
export NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-controller/web/node_modules
node planning/12-workspace-controller-revamp/evidence/after/p5-discovery-return/preview-audit.cjs
node planning/12-workspace-controller-revamp/evidence/after/p5-discovery-return/axe.cjs
node planning/12-workspace-controller-revamp/evidence/after/p5-discovery-return/reachability.cjs
node planning/12-workspace-controller-revamp/evidence/after/p5-discovery-return/today-density.cjs
```

`walkthrough.cjs` and `tools-audit.cjs` perform guarded writes and require fresh,
isolated CI data. They are not read-only reproduction commands and refuse the
preview/owner principal. The existing live suite likewise needs its fresh
three-work CI fixture and production-wording configuration. Never re-run them
against a used owner account or pretend the seeded papers are real intake.

## Unresolved reliability and later phases

If browser session storage is unavailable, Library return selection can fall
back to the first eligible source; explicit `?focus=` still works. The P4
**browser-storage / client-side Back-Forward limitation remains unresolved**:
Reader protects unsafe same-tab links and document unload, but cannot guarantee
intercepting every Next history transition. Keep the tab open and save or copy
unrecoverable text before history navigation. Session recovery is not a durable
server save. P5 does not claim this reliability follow-up is solved.

CSS consolidation remains G7. G5 is ready for experience review; P6 is not
started. Provider contacts/spend remain zero, recurrence disabled, no new PR,
no merge, no real-key setup or qualification execution. The broader G7/G8
matrix and actual model/checker quality remain outside this checkpoint.
