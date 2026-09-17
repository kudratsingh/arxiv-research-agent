# 17. W11-F1 — artifact retention options

Status: **CLOSED — option C adopted by owner ruling R9 on 2026-09-17 and
implemented in [ADR 0096](../decisions/0096-structural-screens-not-phrase-screens.md).
Kept as the record the ruling chose from.**

Snapshot date: **2026-09-17**

Repository baseline: `18c3990` on `main`

Finding: **W11-F1**, opened by
[`15-stage0-qualification-report.md`](15-stage0-qualification-report.md)
§7.4.

Rule under discussion: `_PRIVATE_REASONING_PATTERNS` in
[`../../src/contracts/artifact_store.py`](../../src/contracts/artifact_store.py),
introduced by ADR
[0083](../decisions/0083-runtime-event-bridge-and-artifact-adapter.md).

This memo does three things and stops: it states what the rule protects,
measures what it currently costs, and lays out three ways to change it
with their costs and risks. It recommends one. **It changes no
behaviour**, and the refusal is exactly where it was.

---

## 1. What the rule protects

`src/contracts/artifact_store.py` refuses four kinds of body outright
rather than sanitising them: an expiring signed URL, a credential shape,
**raw private reasoning**, and a data class below the run's. The third is
this memo's subject:

```python
_PRIVATE_REASONING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)</?thinking>"),
    re.compile(r"(?i)</?scratchpad>"),
    re.compile(r"(?i)\bchain[ _-]of[ _-]thought\b"),
    re.compile(r"(?i)\bhidden[ _-]reasoning\b"),
    re.compile(r"(?i)\breasoning_content\b"),
)
```

The protection is real and should survive any change made here. RFC 10
([`10-trajectory-event-rfc.md`](10-trajectory-event-rfc.md)) §3.2 makes
"store private chain-of-thought or hidden reasoning tokens" an explicit
**non-goal** of v1, and §4.2 invariant 9 makes it an invariant: "No raw
secrets or private reasoning. Redaction occurs before append;
secret-bearing writes are rejected rather than repaired after
persistence."

The store's own comment states the reasoning for extending that from
events to artifacts, and it is a good one:

> a body that may not appear in an event payload may not appear in an
> artifact either — the artifact is simply where the bigger version of
> the same content would go.

Without that extension, §10.1's event rule would be decorative: anything
forbidden inline could be written to an artifact and referenced. That
argument is sound, and **nothing below proposes dropping the screen.**
The question is whether *this particular pattern* implements it.

### 1.1 Where the argument does not carry

The "same content, bigger" argument imports one bullet from §10.1's
list. Here is the list it is imported from — the things §10.1 excludes
from **event payloads**:

- credentials, signed URLs, environment dumps, raw exception locals;
- "raw user requests, learner messages, PDF bodies, source chunks,
  prompts, model outputs, **reports**, code, and tool stdout/stderr";
- "private chain-of-thought, scratchpads, hidden reasoning tokens";
- direct identifiers where a scoped `principal_key_id` suffices.

The artifact store applies the third bullet and **necessarily does not
apply the second** — because §7.1 rule 6 says where the second bullet's
content goes:

> Event payloads may include a bounded excerpt only when its event schema
> and data policy explicitly allow it; **source text, prompts, PDFs,
> transcripts, model responses, reports, and code outputs use artifacts
> by default.**

So source text and reports are excluded from events *precisely because
the artifact store is where they belong*. The store registers
`SOURCE_DOCUMENT`, `SOURCE_SPAN`, `CANDIDATE_REPORT` and `FINAL_REPORT`
as roles for exactly that reason. The private-reasoning bullet is
genuinely different in kind — it is excluded from the system altogether,
not routed — which is why extending it is right in principle.

What the pattern actually does, though, is match a **topic**, and topics
travel in the second bullet's content. A report about chain-of-thought
prompting is a report; an abstract about chain-of-thought prompting is
source text. Neither is private reasoning, and the rule cannot tell the
difference, because a bare phrase carries no information about who
authored the span it sits in.

The other four patterns do not have this problem, and the contrast is
the whole diagnosis. `</thinking>`, `</scratchpad>` and
`reasoning_content` are **delimiters and field names** — they are how a
provider *frames* hidden reasoning, so their presence is evidence about
the span's origin rather than about its subject. `chain[ _-]of[ _-]thought`
and `hidden[ _-]reasoning` are ordinary English noun phrases that are
also the names of research topics this product exists to research.

---

## 2. The measured loss

### 2.1 What Stage-0 observed

The qualification report records it as observed behaviour: three of the
four runnable arms lost their briefing bytes. Arms B, C and D run the
evidence path, which quotes source abstracts verbatim; the first fixture
paper's abstract contains "chain-of-thought prompting"; each briefing was
refused with `error_type=forbidden` and the candidate recorded
digest-only. Arm A does not quote abstracts and was stored normally.

### 2.2 Reproduced here, at the shipped defaults

Rebuilt from the shipped fixture corpus (`src/agents/search.py::MOCK_PAPERS`)
through the shipped briefing assembler, at the shipped
`reader_max_claims_per_paper` default of 5:

| Path | Briefing | Screen hits | Outcome |
|---|---|---|---|
| evidence path on (arms B, C, D) | **4,946 bytes** | 1 | **refused — 0 bytes retained** |
| evidence path off (arm A) | 4,073 bytes | 0 | stored |

One sentence causes it. The phrase enters the document here:

```text
Evidence (abstract): Generation-time methods include retrieval-augmented
generation (RAG), constrained decoding, and chain-of-thought prompting.
```

That is a verbatim quotation of a retrieved paper's abstract, introduced
by the label `Evidence (abstract):`. The run did not author that
sentence, and the store has no way to know that.

Three properties of the loss matter more than its size:

1. **It is correlated with the benchmark's subject.**
   `research-policy-v1` is twenty LLM-research questions. The artifacts
   lost are the ones about reasoning methods — not a random sample.
2. **It is asymmetric across the experiment's own axis.** The loss falls
   on the evidence-path arms and not on the control. Arm A is the
   comparison arm; it keeps its bytes because it quotes nothing.
3. **It is silent by design.** The run continues, the ledger still names
   the candidate, and a WARNING says which rule fired. Nothing fails, so
   the gap shows up in Stage 3 as an artifact set with holes in it.

### 2.3 The loss is not limited to reports

The screen runs in `_screen_text`, before any consideration of `role` or
`trust_class`. Storing the fixture paper's own 697-byte abstract:

| Role | `trust_class` | Outcome |
|---|---|---|
| `source_document` | `untrusted_source` | **refused** |
| `source_span` | `untrusted_source` | **refused** |
| `evidence_record` | `tool_generated` | **refused** |
| `candidate_report` | `system_generated` | **refused** |
| `final_report` | `system_generated` | **refused** |

`SOURCE_DOCUMENT` under `UNTRUSTED_SOURCE` is a role and a trust class
that, by definition, contain no model reasoning — the bytes came from
outside the system. They are refused anyway. This checkout therefore
cannot store a retrieved paper about chain-of-thought prompting under any
role at all, which is a strictly larger problem than the one Stage 0
found, and the one that decides the recommendation below.

### 2.4 Pinned by a test

`tests/test_stage0_qualification.py::TestTheCandidateRoleCannotReachEvaluationMaterial::test_w11f1_a_briefing_quoting_a_source_abstract_keeps_its_bytes`

It builds the evidence-path briefing above and asserts it is **stored** —
the behaviour this memo recommends and the repository does not have. It
is `@pytest.mark.xfail(strict=True)` with W11-F1 as the reason, so it
xfails today and turns into a loud `XPASS(strict)` **failure** the moment
the rule is narrowed. That is deliberate: whoever changes the rule is
made to come back to this memo and to ADR 0083 rather than leaving a
stale pin behind. Verified both ways — it xfails on this tree, and
temporarily dropping the one pattern makes it fail as `XPASS(strict)`.

The existing sibling test
(`test_a_briefing_about_chain_of_thought_is_refused_storage`) pins the
refusal itself on a hand-written body and is untouched. The two are
complementary: one says the rule fires, the other says what that costs.

---

## 3. Options

All three keep the delimiter and field-name patterns
(`</thinking>`, `</scratchpad>`, `reasoning_content`) exactly as they
are. They differ in what replaces the two English-phrase patterns.

### Option A — allow-list quoted source text

Exempt spans the document marks as quotation: the `Evidence (abstract):`
label, Markdown block quotes, fenced blocks, or a body whose
`source_artifact_ids` say it derives from a stored source.

- **Cost.** Small in the store; a span-classifier over Markdown plus a
  decision about which labels count.
- **Risk — high, and it is the wrong shape of risk.** The exemption is
  driven by the document's own formatting, and the document is written by
  the thing being screened. A synthesizer that labels a span
  `Evidence (abstract):` gets it past the screen. That inverts the
  trust direction of a safety rule: the screened party chooses the
  exemption. It also breaks the moment briefings are not Markdown.
- **Does not fix §2.3.** A raw `SOURCE_DOCUMENT` has no quotation
  markup at all — it *is* the quotation — so the abstract is still
  refused.

### Option B — match only model-authored spans

Keep the phrases, but apply them only to spans attributable to the
model: reasoning delivered in a provider's thinking block or in a
`reasoning_content` field, identified where the gateway parses the
response rather than by scanning assembled bytes downstream.

- **Cost.** Largest of the three, and it is not confined to the store:
  it needs span provenance to survive from `src/llm.py` through the
  agents into the briefing, which today it does not. `TrustClass` is per
  *artifact*, not per span.
- **Risk.** Medium. It is the most *correct* model of the problem — the
  question really is who authored the span — and correspondingly the
  easiest to get subtly wrong, with a failure mode that leaks rather
  than over-refuses.
- **Note.** ADR 0077's gateway already discards thinking blocks and never
  logs them, so the highest-value part of this option is arguably
  **already enforced upstream**, which weakens the case for paying for
  the plumbing.
- **Does not fix §2.3** on its own without the span plumbing reaching
  source documents too.

### Option C — a structural rule, on frame rather than topic

Delete the two English-phrase patterns
(`chain[ _-]of[ _-]thought`, `hidden[ _-]reasoning`). Keep and, if
wanted, extend the structural ones — the patterns that match how hidden
reasoning is *framed*: `</thinking>`, `</scratchpad>`,
`reasoning_content`, and any further provider-specific delimiters or
field names as they appear.

- **Cost.** Smallest: a constant edit plus tests. No new plumbing, no
  new concepts, no signature changes.
- **Risk.** A body that discusses private reasoning in prose is stored.
  That is the intended outcome, not a regression: §3.2 and invariant 9
  forbid *storing chain-of-thought*, not *mentioning* it. Residual risk
  is a provider that emits raw reasoning with no delimiter and no field
  name — and against that, the phrase patterns never helped, because
  such a span need not contain the words either. The pattern was
  catching the topic, not the leak.
- **Fixes §2.3 completely.** Source documents, source spans, evidence
  records and reports all store again, regardless of subject.
- **What it gives up.** A defence-in-depth tripwire against a
  hypothetical path that concatenates a labelled chain-of-thought into a
  report body. Judged low value: such a body would almost certainly carry
  a delimiter too, and if it did not, the phrase would only catch it by
  luck.

### Not recommended, for the record

**Leave the rule as it is.** Viable — the loss is graceful and the
campaign still runs — and rejected because the loss is correlated with
the benchmark's subject matter and asymmetric across the arms the
experiment compares. A funded run would produce an artifact set whose
holes line up with the axis being measured, which is the one shape of
missing data an evaluation cannot reason around.

---

## 4. Recommendation

**Option C**, with the two English-phrase patterns deleted and the
structural patterns kept.

> **Adopted by owner ruling R9 on 2026-09-17**, and implemented in
> [ADR 0096](../decisions/0096-structural-screens-not-phrase-screens.md).
> This memo stands as the record the ruling chose from, so §2's
> measurements describe the state *before* the change.

The reasoning is §2.3. The rule refuses a retrieved paper's own abstract
under `SOURCE_DOCUMENT`/`UNTRUSTED_SOURCE` — bytes that entered from
outside the system and cannot be model reasoning by construction. No
amount of allow-listing (A) or span attribution (B) repairs that, because
neither has anything to attribute: the artifact is source text through
and through. The only fix is to stop matching the topic.

It is also the option that best preserves what ADR 0083 was protecting.
The protection was never "no document may mention reasoning"; it was "the
artifact store must not become the loophole that makes §10.1 decorative".
A delimiter-and-field-name rule holds that line — a body carrying a
provider's thinking block is still refused — while a topic rule holds a
line RFC 10 never drew, at the cost of the product's own subject matter.

If the owner prefers more coverage than C alone, **C then B** is the
coherent order: fix the false positive now with a constant edit, and
treat span provenance as its own work order with its own ADR, priced
against how much ADR 0077's existing thinking-block handling already
covers. A and B both leave §2.3 broken, so neither is a substitute for C.

### What changing this rule would require

Not done here, and listed so the work is priced rather than discovered:

- an ADR amending ADR 0083, stating the narrowed rule and why;
- deleting or rewriting
  `test_a_briefing_about_chain_of_thought_is_refused_storage`, which pins
  today's refusal;
- the `XPASS(strict)` failure from §2.4, which is the intended signal to
  come back to this memo;
- `tests/test_stage0_qualification.py`'s `PRIVATE_REASONING_FALSE_POSITIVE`
  guard and the synthetic-episode assertion that tolerates a digest-only
  artifact because of it;
- a note in §7.4 of
  [`15-stage0-qualification-report.md`](15-stage0-qualification-report.md)
  closing W11-F1.

### What this memo does not establish

Whether any real provider response has ever reached this store carrying
raw reasoning. Nothing measured here is evidence about that: the mock
corpus is fixture text and no funded run has happened. The argument for C
is that the phrase patterns do not detect that case either, not that the
case cannot occur.
