# 0058. Learner profile store, provenance, and prompt isolation

- **Status**: accepted
- **Date**: 2026-08-30
- **Deciders**: kudratsingh
- **Follows**: [ADR 0020](0020-prompt-injection-isolation-reader.md) (untrusted
  content isolation), [ADR 0032](0032-conversation-mode.md) (the store
  pattern), [ADR 0033](0033-safety-hardening-bundle.md) (API-key auth +
  the `prior_context` isolation precedent),
  [ADR 0036](0036-per-principal-store-scoping.md) (per-principal
  scoping), [ADR 0043](0043-conversation-store-hardening.md) (store
  hardening), [ADR 0046](0046-literal-typed-config-enums.md)
  (`Literal`-typed config enums)
- **Implements**: WO-W02 in
  [`planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md`](../../planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md#wo-w02--learner-lite-profile-store-provenance-and-the-isolation-aware-serializer),
  under scope ruling **SR-02**

## Context

Phase W builds a coach around the research instrument, and a coach has
to know who it is teaching. That makes `learner_profiles` the **first
personal data this repo stores**: jobs and conversations are about
papers, this is about a person. Two consequences follow immediately,
and both are the reason this ADR exists rather than a one-line "add a
table" commit.

**Honesty.** The learner model's integrity core is the three-valued
`source` on every skill claim —
[`01-LEARNING-AGENT.md` §1.2](../../planning/07-learning-platform/01-LEARNING-AGENT.md#12-honest-updating-declared-vs-inferred-vs-assessed):

- `declared` — the learner said so. **Never overwritten by inference.**
  If an assessment contradicts it, the agent records a *second* entry
  and surfaces the tension in conversation; it does not silently
  downgrade the learner's self-image in a database.
- `inferred` — derived from behaviour. Capped at confidence 0.6,
  always shown as a guess, always carrying the session that produced
  it as `evidence_ref`.
- `assessed` — backed by a concrete assessment event whose id is in
  `evidence_ref`. The only source that may move the plan on skill
  grounds.

And the rule stated so it can be tested: **no prompt ever presents an
inferred skill to the LLM as fact.** This is the same discipline the
repo already enforces elsewhere — the reader refusing to fabricate
`source_text` from an abstract (ADR 0016/0052), the job machine's
"never invent a stage" rule — applied to pedagogy. The Phase W plan
lists it in Gate W1's honesty inventory as a **named test**.

**Privacy.** The profile carries learner-authored free text
(`profile_note`, goal statements) that flows into prompts week after
week — the cross-turn injection shape ADR 0033 closed for
`prior_context`, now with a human on the other end of it. And it
creates the first deletion promise this repo has to keep.

The obvious cheap implementation — a `skills JSONB` column, a
`source` string with a sensible default, a serializer that prints the
profile — satisfies none of that. A default on `source` is a lie
waiting to be told; a serializer that prints claims uniformly hands
the model a guess dressed as a fact on its first bad day.

## Decision

Ship the store so that the honesty violations are **unrepresentable**,
at three layers, and prove each layer with its own test.

### 1. Provenance is non-nullable, in the type and in the table

`SkillEntry` (`src/learning/profile_store.py`) is a frozen dataclass
whose `source: SkillSource` has **no default and no `None` member**. A
caller that omits it gets a `TypeError`; a stored row that omits it
raises `ProvenanceError` on read, rather than defaulting to anything —
there is no honest default for "where did this claim come from".

The same rules are `CHECK` constraints on `learner_profiles`
(`src/tools/postgres_pool.py::SCHEMA_DDL`), expressed with
`jsonb_path_exists` over the `skills` array:

| Rule | Enforced by |
|---|---|
| every claim has `skill`/`level`/`source`/`evidence_ref`/`confidence`/`updated_at` | `learner_profiles_skills_complete` |
| `source` and `level` are in the vocabularies | `learner_profiles_skills_vocab` |
| `declared` ⇒ confidence exactly `1.0`, and nothing else may reach `1.0` | `learner_profiles_skills_provenance` |
| `inferred` ⇒ confidence ≤ `0.6` | `learner_profiles_skills_provenance` |
| non-`declared` ⇒ non-empty `evidence_ref`; `declared` ⇒ empty | `learner_profiles_skills_provenance` |
| the anonymous principal owns nothing | `learner_profiles_principal_named` |

So an operator with `psql` is refused exactly as the store is. The
numeric bounds are duplicated between Python and SQL on purpose, and
a test asserts the two agree — a cap that drifts between them is a cap
that is not enforced.

### 2. A declaration cannot be overwritten by an inference

Claims are keyed by **`(skill, source)`**. A contradicting assessment
therefore lands *beside* the declaration as a second entry; the merge
function cannot address the declared row from a non-declared write.
`merge_skill_entries` is the only fold, and `replace_declared_skills`
— the only path HTTP reaches — refuses a non-declared claim outright.

The wire contract carries the same asymmetry: the **request** schema
has no `source`, `confidence`, or `evidence_ref` field anywhere, so a
client cannot state provenance and therefore cannot forge it; the
**response** schema makes `source` a required enum on every claim, so
no consumer can render a skill without knowing where it came from.

The per-skill cap evicts the **oldest guesses first, then the oldest
assessments, and never a declaration**; if only declarations remain,
the write is refused rather than trimmed. What the learner said about
themselves is the one thing a cap may not quietly delete.

### 3. The serializer verifies its own output

`render_profile_for_prompt` renders every claim with an inline
provenance marker (`[declared]` / `[assessed]` / `[inferred]`),
confines inferred claims to an explicit **"unconfirmed impressions"**
block, and then **re-reads its own output** — a marker outside its
section raises `ProvenanceError` instead of reaching a model. That
check is asserted by a named test precisely so "unreachable" is not an
assumption. It holds in both positions of `enable_prompt_isolation`:
tying an honesty rule to a security flag would make it a side effect.

Declared claims print no confidence number. "Confidence 1.0" beside
something a person told you invites the model to reason about it as a
measurement.

Learner-authored free text is wrapped by a new tag pair in
`src/security/prompt_isolation.py` —
`<untrusted_learner_text>` plus `LEARNER_TEXT_ISOLATION_INSTRUCTION` —
following the pattern ADR 0033 established for `prior_context`.
Control-plane fields need no wrapping because the store refuses
anything that is not slug-shaped: skill names, levels, sources and
evidence refs cannot carry a colon, a newline, or a tag, so there is
no control token a learner can write into. That is ADR 0020's lesson
moved from the prompt to the boundary, and it is why the flag-off path
is still structurally safe.

### 4. Keying, flags, and deletion

- **Key**: the existing `principal_key_id` (ADR 0036), per SR-02.
- **Flags**: `enable_learner_profile` (default off) and
  `learner_profile_store` (`memory` | `postgres`, default `memory`).
  A `@model_validator` refuses `enable_learner_profile` without
  `enable_api_auth` **at settings load**, so the operator sees the
  misconfiguration before traffic rather than as a 404 per request.
- **Routes**: `GET`/`PUT`/`DELETE /learn/profile`, behind
  `require_principal`. No path carries an id, so a caller can only
  address their own record — ADR 0036's scoping holds by the shape of
  the route rather than by a `_check_ownership` call a future handler
  could forget. Tests assert it with two keys anyway.
- **Flag-off**: the routes are mounted regardless and answer 404
  `learner_profile_disabled` (SR-07 keeps gating backend-only, so the
  contract snapshot and the generated types never depend on a flag).

### The privacy posture, quoted as **proposed**

From
[`01` §1.4](../../planning/07-learning-platform/01-LEARNING-AGENT.md#14-privacy-posture),
carried here verbatim in status: these are **proposals pending 01's
Q7**, not settled policy.

1. **Deletion is a first-class operation.** `DELETE /learn/profile`
   removes the whole row — declarations, goals, inferred and assessed
   claims, and the note. It returns 204 whether or not a row existed,
   so the response never confirms that a principal had a profile.
   **The promise's stated exception**: the shared paper and embedding
   caches hold public arXiv text, are not per-user, and are untouched
   (MT-01 §7.3's caveat, carried). Progress events (WO-W07) join this
   promise when that table exists; the account-level deletion is this
   operation.
2. **Retention**: raw session transcripts kept ~90 days, then dropped
   in favour of rollup summaries. **[proposed — the number is 01's
   own judgment call]**; Phase W stores no transcripts, so nothing
   here depends on it yet.
3. **The profile is untrusted input** — implemented, §3 above.
4. **No third-party disclosure**: nothing in the profile is sent
   anywhere except Anthropic's API inside prompts, which the
   deployment already does for every query.

## Alternatives considered

- **A `source` column with a default of `"declared"`.** Rejected, and
  it is the alternative this ADR exists to reject. A default makes the
  unlabelled case *representable*, and the first batch import or
  hand-edited row would then assert that the learner said something
  they never said. Non-nullable with no default costs one `TypeError`
  at a call site and buys the invariant outright.

- **Enforce provenance in Python only.** Rejected: the Python layer is
  the layer most likely to be bypassed — an admin script, a migration,
  a `psql` session during an incident. The `CHECK` constraints make the
  rules a property of the data rather than of the code path that
  happened to write it. Cost: the bounds are written twice, mitigated
  by the parity test.

- **A separate `learner_skills` table, one row per claim.** Genuinely
  attractive: `PRIMARY KEY (principal_key_id, skill, source)` would
  make "no silent overwrite" a database constraint rather than a merge
  function. Rejected for Phase W because the profile is always read
  whole (it goes into a prompt as one block), the cap is small (40
  claims), and a second table doubles the surface the deletion promise
  and WO-W07's merge order have to cover. The JSONB column with the
  `(skill, source)` key in Python plus the `jsonb_path_exists`
  constraints gets the same guarantees at Phase W's scale. If claims
  ever need to be queried across learners, the table is the migration.

- **Let the profile edit endpoint delete inferred claims.** Rejected
  for now: a learner correcting a guess *declares* something, and the
  declaration outranks the guess in every reader. Letting the edit
  surface delete evidence-backed claims would also let it delete
  assessments. Recorded as a follow-up — 01 §1.2 does say an inference
  is "always displayed to the learner as a guess they can correct",
  and "correct" may eventually want to mean "dismiss".

- **Reuse `wrap_untrusted` for learner text.** Rejected: its tag says
  `untrusted_paper_text`, and labelling a person's own words as paper
  text would be a lie inside the very mechanism that exists to make
  the boundary unambiguous. A third tag pair follows the precedent
  ADR 0033 set for `prior_context` exactly.

- **Return an empty profile on `GET` instead of 404.** Rejected:
  it would make "the learner has told us nothing" and "the learner
  told us they are a beginner" indistinguishable at the API. 404 is
  the empty state, and the client renders it as such.

- **503 for the disabled flag.** Rejected: 503 promises "try again
  later", which is a lie about a flag. 404 says the capability is not
  mounted, consistent with the repo's info-hiding discipline.

- **Build the full 01 §1.1 record** (`style_signals`,
  `preferred_days`). Rejected: every field added here is a field the
  deletion promise must cover, and `style_signals` is explicitly
  deferred in the Phase W plan's not-scheduled list. Smallest honest
  subset first.

## Consequences

**Positive**

- The four honesty rules are enforced at three independent layers
  (type, merge, table), so no single missed code path can produce a
  claim that lies about its own origin.
- Gate W1's `no-inferred-as-fact` criterion is a named test that
  passes in both flag positions, and the serializer fails loudly
  rather than silently if a future edit breaks it.
- Deletion is one row and one statement; the promise is small because
  the record is small, and its stated exception is in the handler's
  own docstring where an operator reads it.
- The contract document is identical in both flag positions, so the
  frontend's generated types never depend on a backend flag.

**Negative**

- `principal_key_id` is a **mutable display name**, not a stable owner
  id (MT-01 finding F1). A reassigned key would inherit another
  human's skill history. Phase W handles this **operationally** — SR-02
  and the WO-W17 runbook require pilot keys to be issued fresh per
  person and never reassigned — and it is honestly labelled as such
  everywhere it appears. MT-01 / L0-05 is the real fix. Nothing in
  this ADR makes that problem better; it makes it *load-bearing*,
  which is why it is stated here rather than in a follow-up list.
- Bounds live in both Python and the DDL. The parity test is the
  mitigation, not a cure.
- The per-skill cap can evict an `assessed` claim. Recoverable — the
  progress event behind it is the durable record (01 §4.4) and this
  store is a derived view — but only once WO-W07's `progress_events`
  exists. Until then, an evicted assessment is gone.
- A learner cannot dismiss an inferred claim through the API; they can
  only out-declare it or delete everything.
- Two new settings enter the Phase W config merge queue.

**Follow-ups**

- MT-01 / L0-05: re-key profiles onto a stable owner id derived from
  the secret, and migrate existing rows.
- WO-W07 appends `progress_events` after this card's DDL section; the
  deletion promise extends to cover it in the same commit.
- WO-W03 consumes `render_profile_for_prompt` +
  `profile_isolation_instruction` in the session graph's system
  prompt. The insertion point is stable; nothing in the session graph
  is built here.
- WO-W05 is the only writer of `inferred` claims, batched at session
  close with the session id as `evidence_ref`.
- A learner-facing "dismiss this guess" operation, if the pilot shows
  the need.
- Retention (proposal 2) needs 01's Q7 answered before anything
  implements it.

---

## WO-W07 — the progress-events ledger (shared record)

Folded into this ADR rather than given a number of its own, per
WO-W07's card ("ADR shared with WO-W02's or its own") and the
coordinator's ruling. The two cards describe one store family — the
same package, the same principal key, the same flag, the same deletion
promise — and splitting the record would have made the deletion
promise in particular readable in only half the places it applies.
**Implements**: WO-W07 in
[`05-WEDGE-WORK-ORDERS.md`](../../planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md#wo-w07--the-progress-events-store-and-honest-views).

### Context

[`01` §4.4](../../planning/07-learning-platform/01-LEARNING-AGENT.md#44-the-progress-record)
makes progress an **event log**: everything a surface says about a
learner is a *view* over that log — derived, recomputable, traceable
to evidence. That is the web tier's state-machine honesty rule ("the
machine never invents a stage") pointed at learning, and it only holds
if the log cannot be edited to match a claim someone wants to make.

[§4.1](../../planning/07-learning-platform/01-LEARNING-AGENT.md#41-principles)
allows three currencies of progress — assessment events, repetition
history, artifacts — and bans one: mastery percentages. "You are 87%
through Transformers" is a claim about a latent variable no LLM judge
can measure.

### Decision

**1. Append-only, with erasure as a named door.** `progress_events`
has no update path and no per-event delete path: not on the Protocol
(`PUBLIC_STORE_METHODS` pins the surface to `append`, `list_events`,
`erase_principal`), not in the module's SQL, not on the HTTP surface.
In Postgres a trigger refuses `UPDATE` outright and refuses `DELETE`
unless the connection has set `arxiv.progress_purge`, which only
`erase_principal` does and only inside its own transaction.

Correcting a recorded event means *appending* a correcting one; the
wrong event stays, because a ledger that can be rewritten is not
evidence. Appends are idempotent on `event_id`, so a retried write
re-reads the stored row rather than double-counting it.

The purge door exists because a blanket `DELETE` ban would have made
this ADR's own deletion promise a lie for this table. It closes the
follow-up recorded above: **the deletion promise now covers the
ledger, not just the profile.** The two properties are reconciled
rather than traded — editing an event is impossible, erasing a
person's whole record is a deliberate, auditable act.

**2. Evidence at the write boundary.** `evidence_ref` points at the
session transcript, artifact, or plan behind the event. For
`assessment` it is required and non-blank, enforced both by
`validate_event` and by a CHECK — the same rule
[§4.3](../../planning/07-learning-platform/01-LEARNING-AGENT.md#43-explain-back-via-the-critic-pattern)
applies to the judge (an assertion without evidence is malformed),
applied to the record instead. The views carry the `event_id`s behind
every number, so a count always expands into the events that made it.

**3. No mastery scalar can exist here.** The §4.1 ban is structural in
four places, so no single edit withdraws it:

- a CHECK rejects any payload whose JSON *keys*, at any depth, read as
  a knowledge scalar (`master`, `proficien`, `competenc`, `percent`,
  `pct`, `score`, `knowledge_level`, `skill_level`);
- `validate_event` walks the payload and refuses the same vocabulary
  before any store sees it, with a test asserting the Python list and
  the SQL alternation are the *same list* so they cannot drift;
- no view dataclass or Pydantic model has a field that could hold one,
  and the one rendered string is regex-pinned to session arithmetic;
- a test walks the generated OpenAPI properties, because a field
  banned in Python but published in the contract is a ban in name only.

The CHECK anchors on `"<key>":` rather than on free text **on
purpose**: a learner writing "I have not mastered this" in an
explain-back must remain storable. The ban is on fields, not on
speech — otherwise the honesty rule censors the evidence it exists to
protect.

What the views *do* expose is `schedule_progress`: arithmetic about
sessions, which §4.1 explicitly permits provided it is labelled as
schedule progress rather than knowledge. The field name is the label.

**4. The kind vocabulary is reserved whole, writable in part.** All
six §4.4 kinds are named in the CHECK so Phase L needs no migration,
but the three with no producer (`review_item`, `plan_approved`,
`replan`) are *refused* at the write boundary. Reserving a name is
free; accepting writes for a feature that does not exist would seed
the ledger with rows no view can read.

**5. Keying, flags, routes.** Same as the profile: `principal_key_id`
per ADR 0036 / SR-02, gated by the same `enable_learner_profile` (and
therefore the same auth validator), with `progress_event_store`
(`memory` | `postgres`) as WO-W07's only added setting.
`GET /learn/progress` carries no id in its path, is mounted regardless
of the flag, and answers the same 404 `learner_profile_disabled` while
it is off. The route holds no cached aggregate: it reads raw events
and folds them with a pure function, so the displayed record cannot
drift from the log.

### Alternatives considered

- **A blanket `DELETE` ban.** Rejected: it contradicts the deletion
  promise this ADR makes. The GUC-gated door keeps both properties.
- **`ON CONFLICT DO UPDATE` for repeated appends.** Rejected: an
  upsert is the update path this table does not have. `DO NOTHING`
  plus a read-back gives idempotency without one.
- **Storing the summary.** Rejected: a cached aggregate is a second
  source of truth that can disagree with the log, which is precisely
  the claim §4.4 makes impossible.
- **Banning the mastery vocabulary in free text as well as in keys.**
  Rejected: it would make a truthful learner transcript unstorable.
- **Accepting reserved kinds and ignoring them at read time.**
  Rejected: unreadable rows in an append-only table are permanent.
- **Its own ADR number.** Rejected by the coordinator: §5.4 assigns
  0057+ to five other cards and lists the same five as the index
  editors. One shared record, no new index row.

### Consequences

**Positive**

- Progress claims are auditable end to end: every number expands into
  events, every event points at what produced it.
- The mastery ban survives a `psql` session, not just a code review.
- The deletion promise now covers every learner table.
- Phase L adds producers for the reserved kinds without a migration.

**Negative**

- The append-only trigger means a genuinely bad event (a bug writing
  nonsense) can only be superseded, never removed short of erasing the
  whole principal. That is the intended trade, but it will feel wrong
  the first time it happens.
- The key-vocabulary CHECK is a substring rule, so a legitimate future
  field containing e.g. `score` needs the vocabulary revisited rather
  than silently renamed around.
- `evidence_ref` is a string, not a foreign key: it spans sessions,
  jobs, and plans, which live in different stores. Nothing verifies
  the target resolves.

**Follow-ups**

- WO-W03/WO-W04 wire the first producers (`session_completed`,
  `assessment`); nothing writes to the ledger until they land.
- WO-W14 runs the matching forbidden-string gate over the UI; this
  card is the same rule enforced where the data is born.
- A ledger export (00 §5.4) is Phase L3.
