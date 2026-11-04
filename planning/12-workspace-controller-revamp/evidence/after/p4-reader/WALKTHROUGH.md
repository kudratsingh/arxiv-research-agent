# P4 Reader and mobile reading walkthrough

Open **http://localhost:3148/workspace/today**. This is the isolated **design
preview · synthetic sample papers**, backed by the real local API and Postgres.
It is not a fresh literature check. The richer fixture has 14 works and a
nine-paper edition. Your original workspace remains on 3137, separately backed
by API8137/PG15438. Do not run source-refresh controls on the controller stack.
Generation and recurrence remain disabled; no key setup or provider contact.

## Desktop and mobile route

1. Open Today at 1440×1000 or 390×844, dark or light. On mobile Search starts
   collapsed. Open it with Search or `/`; Escape closes it without losing the
   query. The complete focused title and first two available abstract lines
   clear the collapsed player. A one-line abstract needs only its available line.
2. Choose another queue row (mobile: Queue & controls), or use Previous/Next.
   The edition order and `?focus=` remain stable. Read opens that paper's exact
   pinned version and passage. Missing versions never silently select the latest.
3. In Reader, Source / Understand / Your notes remain visible native links in
   main. Use Tab to reach them; Enter selects a panel. Reading actions and queue
   navigation are in the floating bar; Save question remains in its native form.
   Source preserves available text and evidence limits. Understand offers only
   the explicitly labelled synthetic workbench, loaded after it is opened.
4. Select source text, then Your notes. Choose Question, enter text and Save
   question. Check for server confirmation; session draft recovery alone is not
   a durable save. During a pending entry save the editor is temporarily read-only
   so an older response cannot erase newly typed text. Tabs and source disclosure
   remain reachable. Failed saves preserve text; conflicts do not overwrite it.
5. Use ← Today. The focused paper returns. Continue your question resumes the
   exact version/passage; reload keeps it. Library's saved question resumes that
   same entry/anchor. A source revision cannot move an existing annotation.
6. At mobile width scroll Your notes until both textarea and Save are clear of
   the floating bar. Every keyboard command also has a visible control.

No scientific or personal-usefulness claim is established by these samples.
Owner labels remain blank. Source text is separate from generated analysis;
manual reading and notes remain useful without paid generation.

## Captures (DPR 2)

| Surface | Desktop dark | Desktop light | Mobile dark | Mobile light |
|---|---|---|---|---|
| Today | [view](preview/desktop-dark-today.png) | [view](preview/desktop-light-today.png) | [view](preview/mobile-dark-today.png) | [view](preview/mobile-light-today.png) |
| Reader Source | [view](preview/desktop-dark-reader.png) | [view](preview/desktop-light-reader.png) | [view](preview/mobile-dark-reader.png) | [view](preview/mobile-light-reader.png) |
| Your notes (scrolled) | [view](preview/desktop-dark-notes.png) | [view](preview/desktop-light-notes.png) | [view](preview/mobile-dark-notes.png) | [view](preview/mobile-light-notes.png) |

These rich-preview captures are read-only. Separate write-based walkthroughs use
**controller-p4**, fresh DB **workspace_controller_p4_final_walk**, frontend3149
and API8149, with three CI works/four versions. They are not owner questions.

| Step | Desktop | Mobile |
|---|---|---|
| Select exact passage | [view](walkthrough/ci-synthetic-desktop-01-source-passage.png) | [view](walkthrough/ci-synthetic-mobile-01-source-passage.png) |
| Injected503 leaves draft | [view](walkthrough/ci-synthetic-desktop-02-injected-503-draft.png) | [view](walkthrough/ci-synthetic-mobile-02-injected-503-draft.png) |
| Confirmed revision1 save | [view](walkthrough/ci-synthetic-desktop-03-saved-question.png) | [view](walkthrough/ci-synthetic-mobile-03-saved-question.png) |
| Today return | [view](walkthrough/ci-synthetic-desktop-04-today-return.png) | [view](walkthrough/ci-synthetic-mobile-04-today-return.png) |
| Real409 retains local draft | [view](walkthrough/ci-synthetic-desktop-05-real-409-recovered-draft.png) | [view](walkthrough/ci-synthetic-mobile-05-real-409-recovered-draft.png) |

The shared mobile saved list can show the earlier desktop question first. The
[extra mobile saved-question capture](walkthrough/ci-synthetic-mobile-06-saved-after-conflict.png)
explicitly shows **post-conflict remote revision2**, not the pre-conflict state.
The exact tested selection is `𝛼 + 🚀`, Unicode-codepoint anchor
`abstract:181:186`, version `ci:workspace-agent-evaluation:v2`. Real409 means
server revision2 remains distinct from the recovered stale local draft.

[Walkthrough receipt](browser-audit.json): 12/12 desktop/mobile checks, including
keyboard order, neighboring Reader draft recovery,503/reload/retry, actual saved
question, Today/reload/Library resume and409 separation. Expected injected503
and real409 console responses are recorded; no unexpected browser errors.
[Restart receipt](restart.json): both synthetic questions retain identical IDs,
text, revision, exact work/version and anchor after verification API restart.
[Notes clearance](notes-layout.json): 4/4 themes/viewports.
[Reader axe](axe.json): Source/Understand/notes × two themes × two widths,
12 checks, zero violations. [Today density](today-density-regression.json):
30/30 initial/queue/return cases, including explicitly labelled layout-only
long-title and short-abstract overrides. No fixtures become scientific evidence.

## Run and reproduce

The services are already running. Open:

```bash
open 'http://localhost:3148/workspace/today'
```

Use the [isolated Mac launch commands](../g3-today/WALKTHROUGH.md#run-commands-and-isolation)
for frontend3148/API8148/controllerPG15458, **not** the old Linux kit port recipe.
Do not start a second process on an occupied port or re-seed an existing DB.
After any future production rebuild, **before starting** the standalone server,
copy its static assets from `web/`:

```bash
cp -R .next/static .next/standalone/.next/
```

Starting before the copy can make Next's startup asset inventory return404s even
after files later arrive. Restart only the isolated frontend after copying.
The explicit frontend `WORKSPACE_SYNTHETIC_PREVIEW=1` flag must stay enabled.
The disabled-key sentinel and `WORKSPACE_SCHEDULE_APPROVED=false` apply to every
service. No launch agents, cron, external notifications or provider trial start.

Read-only scripts from the worktree root:

```bash
export NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-controller/web/node_modules
node planning/12-workspace-controller-revamp/evidence/after/p4-reader/preview-audit.cjs
node planning/12-workspace-controller-revamp/evidence/after/p4-reader/notes-layout.cjs
node planning/12-workspace-controller-revamp/evidence/after/p4-reader/axe.cjs
```

Scripts write receipts under ignored outputs/. `audit.cjs` is the **write-based**
12-case walkthrough: it refuses a different origin/principal/fixture. Reproduce
only against a fresh disposable CI database and controller-p4 service on3149;
do not point it at the rich preview or owner data. It creates verification
questions and advances revisions, including a deliberate remote revision.
The existing live regression similarly uses its own freshly seeded isolated DB.
Its final [raw output](live-e2e.txt) is retained.

Source attribution and exact local checks: [STATUS](../../../STATUS.md).
CSS remains the explicitly permitted interim E27 overrun for G7 consolidation;
JS ceilings are unchanged. P5+ and the separate API qualification session are
outside this checkpoint. No GitHub CI result is inferred from local success.

If browser session storage is unavailable, the UI explicitly asks you to keep
this tab open or copy/save the text. Same-tab links and document unload are
protected; client-side browser Back/Forward is not guaranteed to be intercepted
in that failure condition. Do not rely on it as a substitute for a confirmed
server save. Ordinary recoverable-draft history/return behavior is tested.
