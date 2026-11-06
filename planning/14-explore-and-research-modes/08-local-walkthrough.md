# Isolated two-mode workspace walkthrough

This branch keeps the completed controller and uses durable local Postgres.
Owner3137/API8137/storage15438 are not the verification environment. No model,
token-count, source-refresh, recurrence or notification is started by this guide.

## Preview and data identity

- Personal preview: `http://127.0.0.1:3178/workspace/today?mode=learn`.
  Database `workspace_modes`, principal `modes-preview`, API8178, Postgres15478.
  Its interests/reading window are an isolated copy of the actual saved profile,
  not the design-preview profile. The organizing question is preserved and is
  ignored by Learn ranking; it does not silently create a project.
- Browser verification:3179/API8179/database `workspace_modes_browser`, principal
  `modes-browser-r15`. Its copied interests/time are real, but the organizing question
  is explicitly empty for the question-free learning test. Authored test content
  and two labelled synthetic Unicode/version fixtures are verification data,
  never owner judgments or real additional papers.
- Public corpus:40 retained real works, including the previously acquired ReAct
  and Self-RAG samples. Most records have no authoritative publication/update
  date. No new acquisition or fresh monitoring is implied by creating an edition.
  Source health and the exact reading scope remain visible.
- New projects, preferences, notes and threads in these previews belong to their
  isolated principals. They do not update the owner workspace.

Use the same URL at1440×1000 and390×844, in both themes. The narrow mode switch
stays outside the drawer. The drawer contains the queue/settings; the focused
paper and compact player retain their controller layout.

## Connected manual journey

1. Open Explore & Learn Today. No question or project is required. Select an
   edition paper and inspect matching reasons and source/evidence scope.
2. Open Reader. Source, Understand and Your notes remain separate. Retained
   excerpts are not presented as full-paper acquisition; generated assistance
   remains unavailable.
3. Select a passage, save an explicit question, and inspect its exact version and
   anchor. Failed saves retain the draft; browser recovery is not server storage.
4. Expand **Investigate this · learning and project links**, explicitly choose the
   saved question, and create a project. Review the carried source/note revision
   before submitting. Opening the form creates nothing.
5. Open the saved Research project. Edit question, scope, constraints and next
   actions. All changes use revisions and retry identities; conflicts require
   reviewing the server revision before explicitly reapplying local text.
6. Search project sources. Research prioritizes question/scope matches, including
   those outside declared interests. The actual copied-question eligibility
   receipt identifies `arxiv:2610.40740` atP0/Q3; that is a lexical match, not an
   owner relevance judgment or proof it answers the question. An explicit date
   window excludes unknown dates; all stored dates includes them.
7. Open a result's exact Reader version, select a retained passage and attach it
   as evidence. A whole-source or metadata-only reference is a different role;
   it cannot become substantive evidence merely because its source id resolves.
8. Save an observation, assumption, hypothesis, comparison or proposed experiment
   explicitly. Every record is manual and unverified. No experiment runs.
9. Choose **Learn this prerequisite**. Declare a goal and preserve its originating
   project/source/passage. The thread is durable, not an execution job. Return to
   project restores the exact originating Reader passage and project context.
10. Reload, restart the isolated API, then resume through Library. Shared papers
    and notes are links, not copied into projects. Archiving a project or removing
    a project link preserves Library records and old source versions.

The browser evidence records which steps actually passed; this guide alone is
not acceptance evidence. Owner usefulness, comprehension and longitudinal use
remain unjudged. Working-store Back/Forward recovery passes. If storage is unavailable, a full
reload loses unsaved text after a visible warning; that limit remains unresolved.
Physical OS keyboards/Safari/IME remain outside these Chromium checks.

## Exact local start commands

Run from `/private/tmp/arxiv-agent-eng-workspace-mode-build`. Inspect existing
listeners first; do not kill a process merely because it owns a port.

```bash
docker compose -p arxiv-modes-d0-20261105 -f compose.workspace-modes.yml up -d --wait
```

Use the existing isolated database and local service credential. This is a
random local workspace API credential, not a provider key. Do not print it.
In an API terminal:

```bash
MODE_LOCAL_KEY="$(cat outputs/modes-d0/.workspace-api-key)"
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
ENABLE_WORKSPACE=true ENABLE_API_AUTH=true \
API_KEYS="modes-preview:$MODE_LOCAL_KEY" \
POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15478/workspace_modes \
WORKSPACE_SCHEDULE_APPROVED=false JOB_REDRIVER_ENABLED=false \
PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD \
/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  -m uvicorn src.api.app:create_app --factory --host 127.0.0.1 --port 8178
```

The API applies immutable migrations; it does not erase existing data.
Never install packages into the shared locked virtual environment.

The production frontend is built with the disabled-key sentinel. The release
receipt names its exact immutable runtime directory/build id; start that recorded
`server.js` with `HOSTNAME=127.0.0.1 PORT=3178`, `WORKSPACE_LIVE=1`,
`WORKSPACE_PREVIEW=1`, `WORKSPACE_DESIGN_PREVIEW=0`,
`API_INTERNAL_BASE=http://127.0.0.1:8178` and `ARXIV_API_KEY` set from the same
local credential file. Do not serve an old standalone directory while replacing
its static assets. The final status records the exact command and runtime path.

Exact recorded frontend invocation (only when3178 is free):

```bash
MODE_RUNTIME="$PWD/outputs/modes-runtime/T8_ju09AUeIr5jhzAjpoG"
MODE_LOCAL_KEY="$(cat outputs/modes-d0/.workspace-api-key)"
cd "$MODE_RUNTIME"
ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true \
HOSTNAME=127.0.0.1 PORT=3178 WORKSPACE_LIVE=1 WORKSPACE_PREVIEW=1 \
WORKSPACE_DESIGN_PREVIEW=0 API_INTERNAL_BASE=http://127.0.0.1:8178 \
ARXIV_API_KEY="$MODE_LOCAL_KEY" node server.js
```

The retained runtime is an existing build artifact in this worktree. On a fresh
checkout, build the verified application with the same disabled gate and copy
both standalone server and static assets together; never mix build identities.

If3178/8178 are already healthy, use the running preview instead of starting a
second copy. Ctrl-C stops a foreground process. Stopping this Compose project
without `--volumes` preserves its data; never operate `arxiv-workspace-live` here.

## Backup and restore boundary

Use only the isolated Compose project above for
`pg_dump -Fc --no-owner --no-acl -U workspace -d workspace_modes`;
keep the dump private (`umask 077`) and retain a
SHA256 sidecar. A restore check must create a new `workspace_modes_restore_*`
database and compare works, versions, notes, reading, context preferences,
projects, links, artifacts, threads and accounting tables. Never restore over
`workspace_modes`, `workspace_modes_browser` or owner storage. The release
evidence records the actual restart/restore results, not just dump creation: both
API and Node restarted, a fresh browser recovered exact durable content, and
all38 workspace tables/sequences matched the disposable restore. See
[accepted receipts](evidence/d1-d4-browser/README.md).

## Remaining authority

Everyday generation, checker qualification, recurrence and notifications are off.
The stopped evaluation remains$0.109967 estimated cumulative usage,9Messages/
15counts/6jobs,unknown0; q01 development,q02–q04 failed,q05–q10 unrun. Historical
packets and a configured provider key do not authorize dispatch. Grounded
learning explanations, Research comparisons and guided deep dives remain D5,
with a separate reviewable quality and spending decision.

## Readable examples and review recording

The3178 preview includes3 explicit **Example** projects with saved questions and
learning threads, all agent-authored. They use real retained sources and do not
represent your judgments. Long mechanical fixtures are separate on3179.

Open Today → Continue reading → Your notes → Open project workspace → inspect
question/next actions/evidence → open the linked prerequisite thread → Return to
project → Library → choose With notes or questions (drawer on mobile) → Resume
this question → Source context. The last action opens the exact passage; the
saved-question resume intentionally opens the question first.

Full readable recordings are local under
`evidence/d1-d4-browser/owner-walkthrough/62c761a/{desktop,mobile}-{light,dark}/connected-example.webm`.
They include the copied personal profile and are omitted from remote publication.
Committed [browser evidence](evidence/d1-d4-browser/README.md) includes labelled
example screenshots, exact request/source receipts and neutral navigation clips.

To explicitly create the initial examples in this existing isolated environment:

```bash
ANTHROPIC_API_KEY=local-preview-disabled \
PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD \
/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python - \
  < planning/14-explore-and-research-modes/tools/seed-walkthrough-examples.py
```

The verb verifies modes-preview on8178, reuses stable identities, preserves edited
examples by refusing overwrite, and leaves profile/health/owner3137 unchanged.
It reuses public retained text; it never fetches a source or calls a provider.
