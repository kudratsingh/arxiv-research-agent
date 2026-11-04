# Single-paper Today walkthrough

Open **http://localhost:3148/workspace/today**. This is the isolated controller
**design preview with synthetic sample papers**, not a live literature check.
The notice stays present across the workspace. Your existing daily workspace
remains at http://localhost:3137/workspace/today with its own data/preferences.

The rich fixture has a nine-paper edition and real local API/Postgres persistence
under the isolated `e2e` principal. Sample source statuses establish no freshness,
coverage, scientific result, or personal usefulness. Generation and recurrence
remain disabled. Do not use source-refresh controls on this test stack; Today
explicitly disables its live refresh in design-preview mode.

## Desktop: queue → paper → Reader → return

1. Open Today at 1440 × 1000. One paper appears in the reading stage. Its full
   available abstract, rationale and evidence limit belong to the pinned version.
2. Select the third queue row. The highlight, position and `?focus=` change
   together. Use Previous/Next or `j`/`k` with focus outside a text field; the
   controls stop at the boundaries. In a collapsed sidebar the numbered queue
   remains selectable. The paper title is never copied into a second article.
3. Use Save, Dismiss or Snooze one day in the bottom bar. The status confirms a
   save only after the server acknowledges it. Dismiss/Snooze advance to the
   next available paper; removing the last falls back to its predecessor. Undo
   restores the changed paper and selects it, including after another selection.
4. Open Read in the bottom bar (or press `o`). Inspect the exact `version`,
   `return_to` and passage hash in the Reader URL. Source text, evidence scope,
   notes, failure recovery and existing keyboard order remain available.
5. Use **← Today**. The same focused paper/version returns. Reload keeps its
   `focus` URL; browser Back/Forward restores the corresponding route selection.
6. The continuation strip resumes the latest saved question or reading passage;
   Source and pin options expose its exact version/anchor. A failed note save
   remains a draft. To try a question, use Reader → Your notes → Save question
   on this synthetic verification account, then return to Today.

## Mobile: 390 × 844

Use browser responsive mode at 390 × 844, or open the loopback preview in a
browser on this Mac. The viewport emulation is not a claim of testing a physical
phone or remote network access.

- The full initial title must fit above the floating player, not merely start
  above 800 px. The synthetic notice and source summary remain visible.
- Open **Queue & controls**, choose a paper and return to the stage. The drawer
  closes; the selected row and focused paper agree. Queue/settings remain in
  this drawer; the top navigation remains available when it is closed.
- Read, Save, Dismiss, Snooze and navigation have visible controls. Search also
  has a submit button. `/library` and other local slash commands use the same
  current enabled controls as keyboard shortcuts. Typing in a field does not
  trigger paper commands.
- Scroll to inspect rationale/evidence and Edition details. The stage has bottom
  clearance so the floating bar does not prevent reaching the final content.
- Open Reader and use ← Today; verify the selected paper and pinned passage.
  Reader's broader controller redesign is a later phase, outside this batch.

## Run commands and isolation

The verified services are already running. Open the preview with:

```bash
open 'http://localhost:3148/workspace/today'
```

To run the same built frontend in a terminal **only after its existing isolated
3148 process has been stopped**, use:

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller/web
WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1 WORKSPACE_SYNTHETIC_PREVIEW=1 \
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
WORKSPACE_SCHEDULE_APPROVED=false NEXT_TELEMETRY_DISABLED=1 \
API_INTERNAL_BASE=http://127.0.0.1:8148 \
ARXIV_API_KEY=sk_e2e_local_preview_disabled HOSTNAME=127.0.0.1 PORT=3148 \
node .next/standalone/server.js
```

This requires the existing isolated API on 8148 and controller Postgres on 15458,
DB `workspace_rich`. Its isolated Compose project is `arxiv-controller-p0`, using
`/private/tmp/arxiv-controller-stack/compose.yaml`. Do not stop or reconfigure the
owner's 3137/8137/15438 services. Do not re-seed an existing rich DB: repeating the
hand-written feed seed can add blog versions. Use fresh disposable DBs for tests.

If the isolated API needs restarting in another terminal:

```bash
cd /private/tmp/arxiv-agent-eng-workspace-controller
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
ENABLE_WORKSPACE=true ENABLE_API_AUTH=true WORKSPACE_SCHEDULE_APPROVED=false \
API_KEYS=e2e:sk_e2e_local_preview_disabled OMP_NUM_THREADS=1 \
POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_rich \
WORKSPACE_RATE_DATABASE_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace_rich \
/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
-m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8148 --no-access-log
```

The rate-database variable above is a **runtime** setting. Python verification
uses `WORKSPACE_TEST_POSTGRES_URL`, not the runtime rate-governor override.

Reproduce the bounded nine-paper browser audit from the worktree root:

```bash
NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-controller/web/node_modules \
ANTHROPIC_API_KEY=local-preview-disabled \
node planning/12-workspace-controller-revamp/evidence/after/g3-today/audit.cjs
```

The committed audit script, browser record and screenshots below are the review
evidence. It writes the detailed JSON receipt under ignored outputs/. Its deliberate 503 is failure
injection; reversible Save/Dismiss/Snooze/Undo actions use only the synthetic
account. Revisions and activity receipts advance even when the original reading
fields are restored. No owner data or preferences are rolled back or overwritten.

## Captures and verification

- [Dark desktop](desktop-dark-today.png) · [light desktop](desktop-light-today.png)
- [Dark mobile](mobile-dark-today.png) · [light mobile](mobile-light-today.png)
- [Mobile queue](mobile-dark-queue-open.png)
- [Reader return](desktop-dark-reader-return.png)

Final source attribution, measured gates and limitations are recorded in
[STATUS](../../../STATUS.md). The first visual check found a real title/player
collision despite a passing title-top check; the repaired browser gate requires
that the **entire title** clear the player on initial load, queue selection and
Reader return. This remains local fixture evidence, not owner experience approval
or model-quality qualification.
