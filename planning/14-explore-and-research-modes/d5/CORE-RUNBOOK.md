# D5 local walkthrough and operations

D5 preview: **http://localhost:3188/workspace/today?mode=learn**.
The completed D0–D4 review remains3178; owner workspace3137 is untouched.
D5 verification3189/API8189 uses a separate database and principal. Do not use
owner services for these writes. Provider/count contacts, recurrence and paid
execution remain disabled. The preview uses copied real public metadata and
retained excerpts; example project/questions and simulated outputs are labelled.
It does not imply a fresh source check or owner usefulness approval.

## Learning walkthrough

1. Open Today in Explore & Learn; a research question is optional. Open ReAct
   through Library/Radar, or use the pinned direct Reader link below.
2. Choose **Understand**, then **Open assisted reading · local simulation**.
   Opening the panel loads metadata only. Select a depth/background and direction.
3. Expand a retained unit (page3 is useful for ReAct's evaluation context), read its
   exact quotation and extraction warnings, then explicitly include it.
4. **Preview assistance request** seals purpose, evidence, source/version, schemas,
   settings and all four stage limits. Inspect the candidate request separately
   from local integrity parents. Notes/history/preferences are excluded.
5. **Run local assistance simulation · $0** exercises draft/check and any permitted
   repair/recheck through MockTransport. Inspect claim-level simulated abstentions,
   missing evidence and stage accounting. No model answer is claimed.
6. **Open exact cited passage** jumps to the retained original page and Unicode
   range. Return to Understand; choose a follow-up direction, preview again, or
   explicitly save the result to a learning thread. Follow-up is another explicit
   local simulation; changing a field alone never dispatches.
7. Open the saved thread and **Resume saved assistance**. Reloading restores the
   durable job without rerunning it. Unsaved form changes require save/discard
   before navigation. Library's shared note also has a saved-assistance resume link.

Direct pinned example:
`http://localhost:3188/workspace/items/arxiv%3A2210.03629?mode=learn&version=arxiv%3A2210.03629%3Av3#understand`

## Research walkthrough

1. Choose Research and **Example · Reasoning, retrieval and evidence**. This is
   an agent-authored example, not the owner's question or judgment.
2. Open its exact ReAct source, then Understand → assisted reading. The current
   owned project question/revision, scope and constraints are disclosed and sealed.
3. Include one ReAct page3 unit and one Self-RAG retained unit. Each citation stays
   separate, with its own work/version/parser/scope and offsets.
4. Preview and run the local simulation. Inspect the separately cited facts,
   unverified comparison plan, assumptions, gaps and proposed experiment label.
   A citation resolving successfully is not a factual-quality pass.
5. Open either exact passage, return, and explicitly **Save simulation to project
   notes**. A shared Library note is linked without duplicating the source.
   Return via project or Library, inspect the saved simulation and reload.

Pinned research example:
`http://localhost:3188/workspace/items/arxiv%3A2210.03629?mode=research&project=project-55555555555555555555555555555555&version=arxiv%3A2210.03629%3Av3&return_to=%2Fworkspace%2Fprojects%3Fmode%3Dresearch%26project%3Dproject-55555555555555555555555555555555#understand`

## Job states and failure recovery

Queued, drafting, checking, repairing, completed-with-abstentions, failed, cancelled,
interrupted, budget-refused and stale states are durable. **Inspect stored status**
is read-only. **Recover interrupted status** fences an expired lease; it never
replays an uncertain call. **Continue saved simulation** is explicit. Cancellation
stops the loop. A network outage preserves the draft and stable mutation identity;
inspect before retrying. Failed content has no accepted result. Source drift hides
a prior result rather than substituting a newer version. Project edits require a
fresh preview. All realUSD fields remain0; byte counters are labelled synthetic.

## Local services

Dedicated Compose project `arxiv-d5-20261105`, Postgres15488, named disposable
volume`arxiv-d5-20261105_d5-data`; databases`workspace_d5`,
`workspace_d5_verify`, `workspace_d5_tests`. No worker or recurring schedule runs.
API8188/8189 and web3188/3189 use disabled-key sentinel, Mock-only D5 flag and
`ENABLE_JOB_REDRIVER=false`. API keys for these isolated principals stay in0600
local outputs files, never in committed artifacts or screenshots.

```sh
cd /private/tmp/arxiv-agent-eng-workspace-assistance
curl -f 'http://127.0.0.1:3188/workspace/today?mode=learn'
docker compose -p arxiv-d5-20261105 -f compose.workspace-d5.yml ps
```

The local runtime receipt `outputs/d5/runtime-ready.json` records owned PIDs,
immutable build and database identities. Restart only those processes after
checking their listener and cwd against the receipt. Keep Postgres/volumes and
previous immutable builds; never stop unrelated containers or use a general
`pkill`. Build from this worktree with `npm --prefix web run build`; a new build
must be copied into a new immutable runtime before switching its Node processes.
Existing workspace-everyday launch scripts target the owner workspace and must
**not** be used to start D5. The receipt/setup is local-only; a clean clone needs
an explicit public-context seed and isolated key setup, not a fallback memory DB.

## Boundaries still requiring separate work/review

- Fake results demonstrate contracts and durable interactions, not good teaching,
  semantic comparison, checker reliability or user usefulness.
- The new D5 contract has no live qualification adapter yet. The paid proposal
  discloses that integration gate; the old V8 paid runner must not be repurposed.
- Only two inherited, manually pinned PDF samples have retained excerpt support.
  Equations, figures, tables and reading order retain explicit extraction warnings.
- Browser-history recovery for broader unsaved drafts remains the existing
  documented reliability limitation; D5 does not claim to solve it.
- Human fields stay blank. Everyday assistance and recurrence need their own
  quality/authorization decision after any approved quarantined validation.
