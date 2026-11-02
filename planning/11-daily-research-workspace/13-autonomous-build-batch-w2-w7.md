# Next autonomous build batch

Prepared 2026-11-02 after the first connected preview. This is an additive
assignment for the implementation agent that already has the repository and
direction kit. The owner will be away for several hours and wants substantial
reversible progress with concrete evidence on return.

## Copyable assignment

Continue from your existing workspace implementation. Preserve the connected
Today → reader → saved question preview, the editable interest streams and
research question, and the explicit boundary between fictional and real data.
The next outcome is **a usable local research workspace backed by durable
storage and real, bounded source metadata**, with grounded summaries and guided
deep dives still explicit in the implementation sequence.

I will be away for several hours. Continue through the independent work below
without stopping after the next small milestone or waiting on optional design
preferences. Make reasonable reversible choices and record them. If one path
needs owner input, mark the dependency and advance another authorized path.
Complete and verify as much of this ordered batch as practical; report
unfinished work honestly rather than stretching completion claims.

### Current baseline and working rules

The reviewed checkpoint is draft PR #281, branch
`codex/daily-workspace-preview`, head `e000ef7`, based on `88d283d`.
Recheck the actual head and concurrent changes before writing. Do not repeat
the original discovery/kit-writing phase or reset the owner's shared checkout.
Use the kit's W2-W7 cards, architecture and Q gates as the detailed contracts.

The current preview and local test receipts demonstrate a fixture experience.
They do not establish live source coverage, durable storage or generated
research quality. Its visual direction can guide this batch, but the owner's
final experience review remains pending. Preserve the design system; focus
new UI work on making real states, filters, source health and notes usable.

Keep PR #281 reviewable as the first preview. Use bounded follow-up commits
and separate/stacked draft PRs where appropriate. Preserve logical boundaries
for CI repair, storage, intake and user-facing integration. Reconcile the
proposed ADR 0103 number with the existing LE-E reservation before any merge;
use a clearly provisional filename if the allocator cannot be resolved while
I am away. Never overwrite another ADR. Do not merge while I am away.

You may delegate independent work to focused subagents if available. Assign
clear file ownership and one owner for shared migrations, configuration and
API contracts. Integrate and verify the composed application sequentially;
several individually green branches do not establish a working whole.

### 1 Complete one bounded CI diagnosis

As checked for this assignment, run `41468750549` finished with eight successful
jobs and a cancelled Python coverage job after roughly fifteen minutes.
Investigate the logs and identify whether this is a slow test, subprocess,
database lifecycle, coverage cost, environment difference or job ceiling.
Measure before changing enforcement. One focused diagnostic pass is more useful
than repeated blind reruns.

Fix a reproduced defect in a separate slice. If the test work legitimately
exceeds the present stage bound, use measured stage timings to propose or make
a justified bounded pipeline split/ceiling correction. Preserve every tier,
coverage input, project/package/patch floor, artifact and failure signal. Do
not skip tests, weaken assertions, add blanket exceptions or claim local
success means CI passed. If the inherited issue cannot be safely resolved,
record its precise cause/remaining uncertainty and continue feature work.

### 2 Replace browser-only state with durable personal storage

Implement the narrow W2 Postgres repositories, migrations, API contracts and
frontend integration for:

- versioned interests, selected streams, reading-time preference and the
  organizing research question;
- canonical works, source observations and distinct versions;
- owner-scoped save/read/archive state, reading anchors, questions, notes and
  next actions;
- the source-health and edition metadata required by the next slices.

Use the existing principal boundary, server-only proxy, typed error envelope,
Postgres pool and generated TypeScript contracts. A personal local operator
must have a stable explicit identity. Preserve separate auth-off fixture/demo
configurations and loopback binding. Avoid designing the entire future account,
collaboration and knowledge-graph platform before this flow works.

Provide an explicit, retry-safe import of the preview's browser record. Preview
what will be imported, show conflicts, retain originals/export until success,
and prevent duplicate notes on retry. Do not silently transfer browser notes,
overwrite server edits or erase browser data. Handle schema versions, malformed
input, revision conflicts, failed saves and export. An API outage must not
display a successful durable save. Retain unsaved text and offer recovery.

Verify save → server restart → reload → return to the same question/source,
and owner A/B isolation even though the first runtime is single-user. Test
idempotency and concurrent/repeated updates. Do not replace scoped persistence
with a global JSON file or hide a fake in-memory store behind the live UI.

You may start isolated local Postgres/Redis/application services using existing
tooling when needed. Inspect running services first, use distinct project names,
ports and disposable data volumes, and preserve unrelated containers, volumes
and processes. Follow the repository's stack commands; never use a bare
Compose shutdown or delete an owner data volume to make a test pass.

### 3 Implement bounded real metadata intake

Build W3 adapters and ingestion receipts around the existing arXiv tool and the
verified feed seeds. For this batch, small read-only public metadata/feed
fetches are permitted for arXiv cs.LG/cs.AI/cs.CL, Hugging Face Blog and Google
Research Blog. Other topics/sources remain selectable but show their actual
coverage. Reverify endpoint/access rules before activation. No account, paid
quota, subscription, paid search or new credential is authorized.

Use a conservative manual-refresh path first, for example at most 25 items per
configured feed/check and a seven-day default candidate window, with bounded
pages and concurrency. Treat these as configurable batch defaults, not a
claim of exhaustive coverage. Avoid one query per taxonomy leaf and any full
archive backfill. Respect provider rules, shared arXiv rate limits,
Retry-After, ETag/Last-Modified, size and timeout bounds. Validate initial and
redirected URLs, DNS/address policy and feed HTML before rendering.

Store publication/update/first-seen/fetched times with their precision, source
IDs, cursors and requested/successful coverage windows. Do not advance a
successful watermark on a failed or partially uncommitted page. Preserve late
arrivals through a bounded overlap policy. Treat unknown dates as unknown.

Normalize DOI/arXiv identity and versions. A journal/preprint relation requires
reliable identity evidence. A topic-similar paper, news item, code release and
model release remain distinct objects, even when shown in one related story.
Ambiguous titles must not hard-merge. Keep source records inspectable.

Support manual arXiv ID/DOI/URL save through the same controlled boundary.
Unsupported/paywalled material remains a real link/metadata record with an
honest access state. No blanket full-text crawler or paywall bypass.

Acceptance includes controlled tests for duplicates, versions, absent dates,
late indexing, quota exhaustion, malicious URLs/feed markup, source failure
and restart at page/cursor commits. In addition, retain a small real metadata
receipt with request counts, item IDs, timestamps and limitations. A replay
must not create duplicate logical works or briefing entries.

### 4 Make Today and Radar respond to the actual interests

Wire the durable profile and real candidates into the existing visual flow.
Add Radar if it adds real search/filter behavior. Keep the fictional preview
reachable in a clearly separate mode; live pages must never quietly fill gaps
with fictional items or a hard-coded “5 of 6 sources checked” notice.

Start with transparent deterministic relevance: explicit topics/watch terms,
exclusions, source scope, project/question matches, recency, already-seen state,
duplicate grouping and a bounded exploration allocation. Explain the actual
matching signals. Do not invent semantic confidence or learn the user's
interests from a single click. Topic-to-source mappings must be explicit;
unsupported fields show limited/unconnected coverage rather than fabricated
matching results. Preserve custom interests.

Implement real source/date/access/read-state filters, stable pagination and
back navigation. Make the 5/15/45-minute controls choose a genuinely bounded
edition. Saving, dismissing, snoozing and undo should persist and affect the
intended future view. Distinguish “nothing new matched” from “sources could
not be checked.” A failed connector leaves a usable partial edition with its
real coverage gap. Keep historical edition inputs/cutoffs stable.

Use chronological and keyword baselines and hand-reviewed fixtures to verify
ranking mechanics. Prepare a candidate sample for my later usefulness labels;
do not invent my approval or a personal precision score while I am away.

### 5 Finish the real manual reader and research continuity

Integrate the library and reader with real work/version records, original
source links, available abstracts or permitted extracted text, saved questions,
notes and next actions. Keep a useful manual reading path when generation is
disabled. Use safe extracted text initially; inline PDF rendering is optional
and must not block durable notes/source access.

Preserve the source version and actual anchor behind an annotation. Show an
updated work without silently moving a note to another version. Article,
abstract, excerpt and full-text states must remain distinct. For a small
permitted scientific-document sample, prepare bounded extraction with real
page/section/offset references and extraction-quality status; do not fetch
PDFs for the whole inbox. Existing parser/cache capabilities are the baseline.

Make export preserve authored notes, questions, next actions, source identifiers
and version/anchor context. Reopening Today/Library must resume actual saved
work, not a fixture thread. Retain user text through network, parser and source
failures. Add meaningful desktop/mobile/keyboard tests for this real API path,
including import, error recovery, reload, restart, version change and export.

### 6 Build local scheduling and recovery without surprise activation

Implement W6's durable schedule, occurrence/task ledger, short leases, worker
command and in-app delivery intent. Reuse the current jobs/SSE appropriately,
but do not mistake the existing failed-orphan redriver for a durable scheduler.
Keep network calls outside database row locks and make stages replay-safe.

Implement IANA timezone/DST rules, duplicate occurrence suppression, source
cursor recovery, pause/resume, bounded retries and one bounded catch-up edition
after local sleep/offline time. Add an operations view with the actual next
check, last success, queued/failed work and coverage gaps.

The recurring schedule remains disabled until I confirm a time. Implement and
test it using controlled clocks and isolated workers while I am away. Manual
refresh remains usable. No external email, push, SMS, chat message or notification
destination is enabled. Do not claim delivery while the local machine is off.

### 7 Prepare grounded generation and repair its foundations

When the main durable live metadata/reading loop works, continue the highest
value W7 work without model calls:

- retain versioned source material/spans independently of policy evidence flags;
- correct the claim-support definition so resolving a citation ID cannot pass
  a false factual claim;
- enforce the actual sealed settings/source scope at execution, including the
  intended judge temperature/schema path;
- repair calibration input against actual `episode-record.json` nesting and
  grouped chunks, with a real emitted-artifact integration test;
- fix estimator role/revision semantics and actual model routes; preserve
  separate workflow/judge/unknown costs;
- implement atomic per-job/day/month admission/reservations, bounded fan-out,
  retries, cancellation and recovery for later generated work.

Use injected providers, adversarial/abstract-only cases and the zero-spend
sentinel. Scope generated summaries/deep dives as explicit jobs and source
sets. Prepare typed API/UI states, disabled generation controls, source-span
navigation, output caching/invalidation and the representative benchmark.
The no-approved-budget path must refuse before provider-client construction.

Prepare a concrete W8/W9 approval packet for my return: candidate models,
prices verified against current official sources, permitted source/private
context, call/token envelope, tiny qualification sample, estimated low/typical/
high cost, exact proposed ceilings, overshoot/unknown handling and acceptance.
Do not supply an approval record yourself or spend against an existing key.
Approved real grounded summaries and guided deep dives remain required later
milestones. Fixtures cannot satisfy their provider-backed evidence row.

### Boundaries while I am away

Proceed autonomously with reversible local code, migrations on isolated test
data, free bounded public reads, tests, documentation and draft changes under
the repository's existing authorization. Do not add a new paid dependency,
buy API credits, start funded inference, provision hosting, publish content,
send external messages, delete owner data or run arbitrary repository/model
code as a side effect of reading. External writes and account changes need
their own instruction. Preserve current ownership, privacy and secret rules.

If there is a real hard boundary, leave the dependent part disabled with a
clear reason and advance other work. Missing aesthetic preferences, an owner
schedule time, hardware details or paid-generation approval must not stop all
remaining authorized work. If a required local service is unavailable, record
the real gap and complete contracts, adapters, UI states and independent tests;
do not claim an unrun integration succeeded.

Use task-appropriate checks and the mandatory gates. Keep audit, accessibility,
test and coverage enforcement intact. Document any justified performance-budget
movement with measurements. Avoid adding test volume that merely repeats the
implementation. Focus verification on ownership, persistence, replay, source
identity, honest coverage, safe fetching, API/UI integration and evidence/cost
boundaries. No repeated whole-suite runs without a change or unresolved concern.

### What to leave for my return

1. A clean run command and a working loopback desktop/mobile walkthrough showing
   real source intake, edited interests, durable notes/questions, restart/reload,
   source failure, import/export and local catch-up behavior.
2. Focused screenshots at desktop/390 px and a concise record of the real flow.
3. Reviewable commits/draft PRs and an updated status table distinguishing
   implemented, tested, observed live, awaiting owner input and still missing.
4. Relevant test/coverage/audit/build/CI receipts tied to exact commits. State
   skipped, failed, cancelled and unrun checks explicitly.
5. Source receipts and a diagram of the actual data path. Clearly label what is
   real, fixture-only, generated-disabled or still browser-only.
6. The generated-summary/deep-dive approval packet, without executing it.
7. A short list of consequential decisions I need to make next. Keep routine
   implementation choices out of that list.

The priority is a substantial connected research tool I can actually use when
I return. Do not spend the session only producing plans, adding disconnected
pages or polishing a fictional feed while persistence and real intake remain
untouched. A partial result is acceptable when it is substantial, reviewable
and accurately described; elapsed hours alone are not an acceptance criterion.
