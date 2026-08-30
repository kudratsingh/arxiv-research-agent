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
