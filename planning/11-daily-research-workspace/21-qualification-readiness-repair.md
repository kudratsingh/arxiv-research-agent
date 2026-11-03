# Qualification-readiness repair and operator runbook

This repairs reviewed PR284 at `916f038` on a separate branch. PR284 was verified
unchanged remotely at start. The owner app and database remain in place; this
batch changes no everyday UI, preferences, notes, review labels or recurrence.
Provider contact and paid spend remain **zero**. All PRs stay unmerged.

## What changed and what the evidence establishes

The paid draft no longer exports an arbitrary mapping that the SDK closes to
`{}`. `sections` is a nonempty array of closed `{name, claim_ids}` objects.
Names are overview/prerequisites/method/assumptions/comparison/experiment. Local
semantic checks reject duplicate names, missing claim IDs and study sections in
a summary. The exact SDK-transformed schema, as well as the local model, validates
every normal draft, repair and checker fixture. The SDK drops some size/string
constraints into descriptions; local bounded validation still enforces them.
Remote acceptance is unmeasured.

The adapter checks the sealed selected spans before accepting a draft/repair,
before constructing a checker request, and again when processing a checker
response. It retains material/work/version/hash/page/offset/quote validation.
Synthetic PDF regressions test each path. A separate isolated demonstration used
the actual retained ReAct v3 material: page3-only approval refused a correct page1
reference before checker dispatch. This is a scope-boundary test, not scientific
support evidence.

A dedicated count-only adapter shares the durable journal and source/credential
fences. Its admission requires purpose `workspace-measurement-only`, four unique
named input/body digests, `count_contacts_max=4`, `messages_contacts_max=0`, and
`everyday_generation=false`. The funded adapter requires the distinct purpose
`workspace-qualification`, one named request ID and its sealed input digest.
Neither mode creates approvals. A credential or CLI flag is never approval.

Measurement reservations are zero dollars. Count completion is an estimate, not
billed workflow/checker usage. A lost contact is still recorded as uncertain and
unreplayable, even though unknown monetary liability is zero. Duplicate completed
execution returns its retained receipt without sending again. Revocation, source
drift, cancellation and process loss refuse further dispatch. A count-only policy
cannot fund a Message, even through an accidental inherited generation call.
Cache reuse requires the policy digest as well as approval ID and input digest.

## Rebuild and inspect the exact unapproved packet

From this worktree, with the existing database already migrated:

```sh
cd /private/tmp/arxiv-agent-eng-workspace-qualification-repair
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled
export POSTGRES_URL='postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace?options=-c%20default_transaction_read_only%3Don'
"$VENV_PYTHON" -m src.workspace.qualification --owner personal-local \
  --output outputs/workspace-qualification-repair/trial-packet.json
```

The packet builder opens no provider transport and writes no database record.
Read-only mode now works; previously the inherited preview attempted migration.
The packet contains:

- Four exact initial Messages and count request bodies, all selected public text,
  settings, models and digests. The ReAct study selects only its three page3 spans.
- Both local and SDK-transformed draft/repair and checker schemas and their hashes.
- Four named count-only IDs and four separately named experimental job IDs.
- Twenty-four blank claim/span review cases. Human labels, annotators, reasons
  and measured checker verdicts remain null.

V2 replaces every V1 sealed/request/count digest. The checked-in JSON proposal
records the new exact digest manifest; full public request bodies stay under
`outputs/`. Packet preparation and binding refuse source/settings/schema drift.
Later check/repair/recheck bodies depend on future outputs and are sealed/counted
immediately before contact; the packet does not pretend those outputs exist.
Private notes, reading history, drafts and preferences are excluded.

## External approval contract

No approval is active or written by this runbook. After a specific owner decision,
a separate trusted administrator must record approval in the existing
`workspace_budget_policies` table. The tool deliberately supplies no approval
writer. An administrative recorder must retain the owner's exact authorization,
use a fresh approval ID, set a bounded UTC validity period and approved-by identity,
and bind the same owner/model/scopes/contexts shown in the packet. The current
single-active-policy-per-principal store means policies are installed serially;
never replace a policy while one of its contacts is unresolved.

All policies need the existing admission fields: `approved=true`,
`approval_record={approval_id, approved_by, approved_at}`, matching table approval
ID, UTC `valid_from`/`expires_at`, `model_ids=["claude-sonnet-4-6"]`,
`source_scopes=["abstract","excerpt"]`, `allow_private_context=false`,
`transport_mode="provider"`, and `everyday_generation=false`. Generic admission
requires positive ordered cap metadata; proposed experiment caps remain
per-job0.25(summary)/0.40(study), day/month1.25. Count jobs reserve **0**, regardless
of those generic cap fields, and cannot spend via Messages.

For **measurement only**, also require:

```json
{
  "purpose": "workspace-measurement-only",
  "messages_contacts_max": 0,
  "count_contacts_max": 4,
  "count_requests": "copy the four objects from packet.measurement_only.count_requests verbatim"
}
```

The last value is an instruction, not a valid policy: it must be the actual array
of four `{request_id,input_digest,count_request_digest}` objects. No other request
is admitted. Reusing an ID or resuming a lost contact cannot send a fifth count.

For a **quarantined experimental job**, a separate approval record instead requires:

```json
{
  "purpose": "workspace-qualification",
  "request_id": "copy this job's proposed_request_id",
  "request_digest": "copy this job's input_digest"
}
```

The funded record permits only that named job, up to4Messages+4paired counts,
including optional repair and mandatory recheck. The owner may approve the four-
job experiment as a whole, but the external recorder must bind each named job
serially within that authorization; the CLI cannot expand scope. Count-only
permission and results never become funded permission.

## Invocations after a separate explicit approval — not executed

Use a protected environment for a real key only after the applicable approval.
Do not paste it into shell history or change the everyday app's sentinel. The
following commands intentionally contain **no key**. They refuse with the current
sentinel, disabled flag default or missing approval before HTTP-client creation.
For an authorized run, use a writable isolated experiment database with the
reviewed public materials and separately recorded policy, not an owner-data test.

Measurement-only (exactly the four named initial count bodies; no Messages):

```sh
"$VENV_PYTHON" -m src.workspace.qualification_run \
  --owner APPROVED_EXPERIMENT_PRINCIPAL \
  --packet outputs/workspace-qualification-repair/trial-packet.json \
  --mode measurement --allow-provider-contact \
  --output outputs/workspace-qualification-repair/count-result.json
```

Single named funded job, only under its distinct authorization:

```sh
"$VENV_PYTHON" -m src.workspace.qualification_run \
  --owner APPROVED_EXPERIMENT_PRINCIPAL \
  --packet outputs/workspace-qualification-repair/trial-packet.json \
  --mode experiment --request-id QUALIFICATION_ID_FROM_PACKET \
  --allow-provider-contact \
  --output outputs/workspace-qualification-repair/experiment-result.json
```

`POSTGRES_URL` must name the experiment database without read-only mode for these
commands. `--allow-provider-contact` only records operator intent; it cannot
create an approval, bypass the sentinel or enable everyday generation. The runner
rebuilds and compares every initial body/digest with the retained source. An
interrupted running job is fenced, not resumed. On error inspect the existing
job/contact journal; never delete or rename its ID to retry. Revocation sets the
external record unapproved; cancellation/recovery use the existing admission
control. A possibly sent contact needs explicit reconciliation and a new owner
decision if additional scope is needed. No automatic retry or renewal exists.

## Offline demonstration and regression commands

All approval-writing helpers below exist **only in tests**, inside disposable
schemas. Set `WORKSPACE_TEST_POSTGRES_URL` to a disposable verification database,
never the owner's workspace. No production command creates mock approval.

```sh
ANTHROPIC_API_KEY=local-preview-disabled "$VENV_PYTHON" -m pytest \
  tests/test_workspace_qualification_repair.py \
  tests/test_workspace_measurement.py \
  tests/test_workspace_provider_adapter.py \
  tests/test_workspace_qualification.py \
  tests/test_workspace_admission.py -q
```

The measurement end-to-end case runs four approved mocked counts, repeats the
command without new contacts, refuses a funded start, then proves separately
approved experimental execution. The experiment runner case completes
`draft → check → repair → check` using wire-valid responses. Another case tests
CLI output without a permission writer. Transport faults, source drift,
revocation, cancellation, duplicate IDs and uncertain restart are covered.

The local `mocked-roundtrips.json` artifact demonstrates both modes against four
copied public source records in disposable Postgres: four mocked counts plus
four complete draft/check/repair/recheck jobs. Every normal fixture is validated
against its exact outgoing wire schema and the local model. Synthetic usage and
unsupported verdicts are test inputs, not token measurements or quality evidence.

## Limits and remaining explicit decisions

The scope remains three summaries and one selected-excerpt study. Proposed caps
stay unchanged: at most16Messages+16paired counts for the experiment, optional
four earlier count-only contacts (20counts+16Messages combined), raw estimate
0.792USD, 1.25× estimate0.990USD, rounded reservations1.15USD, trial/day/month cap
1.25USD. Prices remain the prior **ESTIMATE**; no lookup or measurement this batch.
Input caps8k(summary)/12k(study), output1.2k/2.4k, response128KiB,30s timeout,
no redirects/retries, one repair and mandatory recheck remain enforced.

Separate owner approval is still required for any provider token-count or
Messages contact. Actual token counts, remote schema acceptance, model claim
support, checker error rates and usefulness are **unmeasured**. Twenty-four
correlated blank review cases and four experimental jobs cannot certify a low
false-pass bound. A further checker experiment may be required. Retained ReAct
and Self-RAG pages remain two hard-coded samples, not general full-paper support.
Real grounded summaries and guided deep dives remain the next product milestone;
this repair does not qualify or activate everyday generation.


Local final gate:6074passed,54existing skips (53legacy Postgres-binary
fixtures and one deferred fault),53e2edeselected; patch99%,22missing of3800
changed lines. Package floors API88/agents96/security100/eval95 pass without
changes. Workflow tier53passed; parity260objects/0mismatches; Ruff and strict
mypy165sourcefiles pass. The focused repair/admission suite comprises98tests.
Final-head CI is recorded in the PR and checkpoint receipt; a local gate is
not a remote green result. The running owner app was not restarted or modified.
