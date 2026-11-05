# Context API v1 — frozen implementation contract

Model-free D1–D4 contract, recorded before screen implementation. ROOT owns the
Pydantic schemas, migration010, stores/routes, OpenAPI and frontend API types.
Revisions, request-id reuse and all owned links are checked transactionally.
Existing `/workspace/state`, profile, entry, reading, import/export and generation
contracts remain compatible. No project/thread action starts a job or creates
qualification authority.

## Identity and records

URL identity: `mode=learn|research`, `project=project-<32hex>`,
`thread=thread-<32hex>`, plus existing focus/view/filter/cursor/version/entry/hash.
Defaults are learning unless the owner explicitly saves a different start-mode
preference. Unknown mode values visibly fall back; unowned/unknown projects show
unavailable context. URLs do not create records or save preferences.

- **Context preferences**: separate `{revision,data}` with `default_mode`,
  `learning_background` and `learning_goals`. Explicit save only. Reading time,
  interests, streams and the organizing question retain their existing profile
  authority; no implicit project import.
- **Project**: client-generated stable `project-<32hex>`, revision, title, question,
  scope, constraints, next actions, active/archived status and database activity
  sequence. Create-from-question explicitly previews/links the owned entry's
  exact revision. Project archive never deletes shared works, material or notes.
- **Project source/evidence**: deterministic link id, exact work/version/anchor,
  selected role (`source` or `evidence`), immutable bound identity, label and
  active/removed status. Repeated requests do not duplicate links. Unlink is
  non-destructive and retains historical references.
- **Project entry**: existing owned entry id and exact entry revision. Read its
  single shared history rather than store another note body. Show later edits
  explicitly; never silently move an old note to a newer source version.
- **Authored artifact**: observation, assumption, hypothesis, comparison or
  proposed experiment, with a manual body or existing-entry reference and exact
  evidence-link ids. These are authored records, not verified findings or executed
  experiments. No provider-created or human-review label is filled implicitly.
- **Learning thread**: stable `thread-<32hex>`, revision, title/goal/prerequisite,
  active/archived status, exact source/entry and originating return context.
  The project/source/passages survive reload/restart independently of browser RAM.
- **Resume context**: product mode, optional owned project/thread and constrained
  workspace return route. Existing entry/reading version and anchor remain
  authoritative. Context-aware writes save this association atomically alongside
  the original shared entry/reading record.

## HTTP surface

All endpoints are under `/workspace/context`, use the existing authenticated
principal, no-store privacy and rate limits. Writes carry `request_id` and the
current revision; reused ids with different content or stale revisions return409.
Unowned reads return the same404 as unknown ids. All ids and arrays are bounded.

| Method / suffix | Contract |
|---|---|
| GET `/` | Lightweight preferences/project/thread index; no full works fetch for Shell |
| POST `/preferences` | Explicit preference revision; independent of legacy profile revision |
| GET `/projects/{id}` | Project plus linked sources, entries, typed artifacts and threads |
| POST `/projects` | Create/update by stable id/revision; optional explicit initial source/entry |
| POST `/projects/{id}/sources` | Revision-guarded source/evidence attachment |
| POST `/projects/{id}/unlink` | Remove only a project link, preserving Library/material/notes |
| POST `/projects/{id}/entries` | Link an existing owned entry revision |
| POST `/projects/{id}/artifacts` | Explicit typed authored record; no execution |
| GET `/threads/{id}` | Owned durable learning thread and origin |
| POST `/threads` | Create/update with stable id/revision and exact origin |
| POST `/entries` | Existing entry write plus atomic resume context |
| POST `/reading` | Existing reading write plus atomic resume context |
| GET `/state` | Contextual workspace snapshot with authoritative `active_edition` |
| GET `/items` | Mode/project-aware discovery with existing hard filters and frozen cursors |

New frontend routes: `/workspace/projects` and `/workspace/threads/[id]`.
The existing Today/Radar/Library/Reader routes retain shared records and context.
The mode switch is visible on desktop and mobile without opening the drawer.
Editor/association forms use the existing pending-write navigation veto.

## Exact evidence and unavailable material

A whole-source link may be metadata-only; it is never a substantive support
claim. Evidence needs a nonempty retained passage. Validate work/version owner
visibility, source-version hash when supplied, material id/content hash/parser/
scope, retained page mapping and Unicode code-point bounds. Rebuild material
identity against retained bytes to refuse mutated payloads. Derive quote and
offsets server-side from that exact passage; do not search for the first matching
quote. Wrong versions, hashes, pages, unselected/missing text or empty passages
are refused. An unavailable pinned source remains unavailable; never select a
newer version automatically. Mechanical identity is not factual support.

## Editions, ranking and return behavior

Keep product mode separate from diagnostic `ranking_order`. Contextual snapshots
bind product mode, project/question revision, profile/preference revision, policy,
candidate cutoff and exact versions. Edits invalidate incompatible discovery
snapshots/cursors. Derived snapshot/cache records may be frozen on read; this
does not create a project or mutate authored preferences. Contextual state has
an authoritative active edition; never select an unrelated `editions[0]`.

One client URL builder preserves mode/project/thread, filters, focus, pagination,
version, entry and passage as appropriate. Extend the constrained Reader-return
allowlist; never accept an arbitrary external return URL. Keep mode/project/hash
out of the Reader editor remount key. App navigation is vetoed before history or
intent changes. Browser Back/Forward draft protection needs an independently
verified recovery layer; unavailable storage/full reload remains an honest limit.

Generated explanations, comparisons and deep dives remain unavailable behind
their separate qualification and approval gates. No count request, provider
client, recurrence or notification is introduced by this contract.
