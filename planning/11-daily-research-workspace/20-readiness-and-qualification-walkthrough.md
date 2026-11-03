# Daily workflow and qualification readiness checkpoint

This follow-up starts at reviewed PR283 `a7ec430`, verified unchanged remotely.
The branch is `codex/daily-workspace-readiness`, stacked on283. All PRs stay draft
and unmerged. Provider contacts/spend are zero and recurrence stays disabled.

## Everyday desktop and390px path

Use the existing loopback workspace at `http://127.0.0.1:3137/workspace/today`.
Do not start a second instance on occupied ports. Check the current launcher:

```sh
cd /private/tmp/arxiv-agent-eng-workspace-readiness
curl -fsS http://127.0.0.1:8137/healthz
# If already running, open the URL. To start after a normal shutdown:
bash scripts/workspace-everyday.sh run
```

Keep the terminal running; Ctrl-C stops its API/web process, preserving data.
Backups/restores and disabled-worker operation remain in
[everyday operations](19-everyday-operation.md). The checkpoint receipt states
which checkout/process serves3137; do not assume a new commit changes an already
running process. The isolated verification principal never writes owner notes.

1. On Today, return to the saved question near the top. Source/version/anchor and
   editable pinning are in **Source and pin options**. The exact passage remains
   attached through Reader, reload and Library return.
2. The finite shortlist follows source-health status. Failures remain visible;
   open source checks for coverage limits and use **Check sources now** to retry.
   Detailed allocation is under **Edition details** after the shortlist.
3. In Interests select `study:17/machine-learning` or another authored area.
   Literal/descendant terms are inspectable. External domains/fields are broad
   navigation anchors; selecting them alone does not invent monitoring coverage.
4. In Radar choose **Excerpt**. ReAct's retained exact version is included even
   though its original observation remains metadata-only. Reader opens its PDF
   excerpts directly. Selected original pages, omitted material and extraction
   warnings remain explicit. A new version does not inherit the old excerpts.
5. Save a question at an exact passage, return, reload and resume through Library.
   Failed saves keep a recoverable local draft; an outage never becomes a false
   server-save success. Owner usefulness judgments remain untouched.

The real intake corpus/receipts are retained from the earlier bounded fetches;
this batch adds no feed fetch, invented candidate or owner relevance label.
Fictional preview stays separately labelled. The existing ten-item usefulness
review remains available at `/workspace/review`, with owner labels blank.

## Exact qualification preview, no provider contact

From the worktree root with its existing local `POSTGRES_URL`, run:

```sh
POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace \
ANTHROPIC_API_KEY=local-preview-disabled \
/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  -m src.workspace.qualification --owner personal-local \
  --output outputs/workspace-readiness/trial-packet.json
```

This reads retained public context and writes a local packet only. It does not
write approvals, jobs or labels. Inspect four exact initial wire/count bodies,
model/settings/schemas, selected source bytes, digests and24blank review cases.
The qualification adapter is not exposed as a paid reader action. The current
Understand workbench remains explicitly fake; no fake output is presented as a
real grounded summary or calibrated factual result.

[The trial packet](15-grounded-generation-approval-packet.md) discloses count
requests, the candidate3summary/1study envelope and proposed$1.25cap. No request
has been made. First approve measurement/qualification contacts, then measure;
checker quality remains unknown until reviewed. Everyday generation stays closed
until adequate quality evidence and a separate decision. A larger negative-case
study may be needed;24engineering cases and four outputs cannot certify a low
false-pass bound. Human and checker judgments are null, never inferred.

## Verification and remaining evidence

New regression coverage spans authored/external/ML catalogue types, exact-version
availability/filtering, automatic PDF entry, saved-question layout, transport
binding and response limits, known/unknown usage, cancellation/restart and packet
privacy. Existing durable browser cases still check two-paper questions, earlier
edits, exact anchors, reload, Library return and failed-save recovery.

Final-head local/CI results and screenshots are in the checkpoint receipt under
`outputs/workspace-readiness/` and the PR checks. Earlier green CI is attributed
to its exact earlier head. Failed, skipped and unrun checks stay explicit. This
checkpoint is not actual token measurement, remote schema acceptance, model
quality, human usefulness, whole-paper PDF support or owner experience approval.
The two hard-coded PDF samples' limits are in
[the full-text inspection](18-fulltext-qualification.md).
