# 0096. A retention screen matches structure, not phrases (W11-F1)

- **Status**: accepted
- **Date**: 2026-09-17
- **Deciders**: owner (ruling R9), implemented by the agent-capability lane (CAP-16b)
- **Amends**: [ADR 0083](0083-runtime-event-bridge-and-artifact-adapter.md)
  (the artifact store's private-reasoning screen)
- **Record**: [`../agent-engineering/17-w11f1-retention-options.md`](../agent-engineering/17-w11f1-retention-options.md)
  — the options memo this ruling chose from, with the measurements
- **Closes**: W11-F1, opened by
  [`../agent-engineering/15-stage0-qualification-report.md`](../agent-engineering/15-stage0-qualification-report.md) §7.4

## Context

ADR 0083 gave `src/contracts/artifact_store.py` four refusals: a signed
URL, a credential shape, **raw private reasoning**, and a data class
below the run's. The private-reasoning screen was five patterns:

```python
r"(?i)</?thinking>"
r"(?i)</?scratchpad>"
r"(?i)\bchain[ _-]of[ _-]thought\b"      # <- retired here
r"(?i)\bhidden[ _-]reasoning\b"          # <- retired here
r"(?i)\breasoning_content\b"
```

The protection is real and is not in question. RFC 10 §3.2 makes
"store private chain-of-thought or hidden reasoning tokens" an explicit
non-goal; §4.2 invariant 9 makes it an invariant; and §7.1 rule 6 routes
report and source bodies to artifacts, so a store that did not screen
would make the event-level rule decorative.

Stage-0 qualification then measured what the screen cost. Three of the
four arms runnable at the time lost their briefing bytes: the evidence
path quotes source abstracts verbatim, the fixture corpus's survey paper
says "chain-of-thought prompting", and each briefing was refused and
recorded digest-only. Arm A, which quotes no abstract, was unaffected.

The options memo measured it again at the shipped defaults and found a
larger case than the qualification had recorded.

| Path | Briefing | Outcome |
|---|---|---|
| evidence path on (arms B, C, D) | 4,946 bytes | **refused, 0 bytes retained** |
| evidence path off (arm A) | 4,073 bytes | stored |

And, because `_screen_text` runs before any consideration of `role` or
`trust_class`, the same rule refused a retrieved paper's own 697-byte
abstract under **`SOURCE_DOCUMENT` / `UNTRUSTED_SOURCE`** — a role and a
trust class whose contents came from outside the system and cannot be
model reasoning by construction.

## Decision

**Option C from the memo, by owner ruling R9.** The two
natural-language patterns are removed. The three structural ones —
`</thinking>`, `</scratchpad>`, `reasoning_content` — are kept, and are
the template for anything added later.

```python
_PRIVATE_REASONING_PATTERNS = (
    re.compile(r"(?i)</?thinking>"),
    re.compile(r"(?i)</?scratchpad>"),
    re.compile(r"(?i)\breasoning_content\b"),
)
```

The distinction that survives is **origin, not subject**. A delimiter or
a provider field name is how hidden reasoning is *framed*, so its
presence is evidence about who authored the span it encloses. A bare
noun phrase is evidence about what a document is *about*, and the store
exists to hold documents that are about things.

The admission test for a future pattern is stated in the module beside
the tuple: a pattern belongs there only if a body **not** carrying
private reasoning cannot plausibly contain it.

### Lesson

> **A safety or retention screen must match structure — markers, field
> names, artifact kind, role, trust class — and never natural-language
> phrases, because product text quotes the world.**
>
> The phrase a screen forbids will appear in the material the system
> legitimately handles. Here the forbidden phrase was the name of a
> research topic, and the system is a research agent: "chain of thought"
> is in the abstracts it retrieves, the briefings it writes and the
> benchmark it is measured on. The rule therefore converted *source
> text* into a refusal.
>
> Two properties made it worse than a plain false positive, and both
> generalise:
>
> - **It was silent.** The run continued, the ledger still named the
>   candidate, and a WARNING named the rule. Nothing failed, so the loss
>   would have surfaced as a Stage-3 artifact set with holes in it.
> - **It was correlated, not random.** The lost artifacts were the ones
>   about the benchmark's own subject, and they fell on the
>   evidence-path arms and not on the control — the exact axis the
>   experiment compares. A screen whose false positives track the
>   independent variable does not add noise; it adds bias.
>
> Recorded as operating principle 11 in
> [`../agent-engineering/README.md`](../agent-engineering/README.md).

## Consequences

- **The evidence-path arms keep their briefings.**
  `tests/test_campaign_execution.py::test_every_episode_retains_its_briefing_bytes_on_every_arm`
  asserts `stored` on every artifact of all 300 mock-matrix episodes,
  which is the same fact (`store.contains`) a Stage-3 artifact sweep
  would read. It fails if a phrase pattern ever returns — verified by
  temporarily restoring the retired pattern, which turns it red.
- **A document may now discuss private reasoning.** That is the intended
  outcome rather than a regression: RFC 10 forbids *storing*
  chain-of-thought, not *mentioning* it. A briefing that surveys
  reasoning methods is exactly the deliverable this product ships.
- **The screen is not weaker against the thing it protects against.** A
  body carrying a thinking block, a scratchpad or a `reasoning_content`
  field is still refused and still not persisted for debugging, pinned
  per marker by
  `test_a_body_carrying_a_reasoning_marker_is_still_refused`.
- **Residual risk, stated.** A provider that emitted raw reasoning with
  no delimiter and no field name would pass. The retired patterns did
  not cover that case either — such a span need not contain the words —
  so this narrows the rule's *scope* without narrowing its *coverage*.
  What is genuinely given up is a defence-in-depth tripwire against a
  body that concatenated a labelled chain-of-thought into prose; judged
  low value, because such a body would almost certainly carry a
  delimiter too.
- **Upstream coverage is unchanged and independent.** ADR 0077's gateway
  already discards thinking blocks and never logs them, so the most
  likely path for real reasoning to reach a body is closed before the
  store sees it.
- **Two tests inverted, and one loosened tolerance removed.**
  `test_a_briefing_about_chain_of_thought_is_refused_storage` is now
  `..._is_stored`; the memo's `xfail(strict=True)` pin is now a plain
  passing test; and the synthetic-episode check that tolerated a
  digest-only artifact whenever the report tripped the screen is now
  unconditional, because there is no longer a case to tolerate.

## Alternatives considered

The memo carries all of them with costs and risks. In brief:

- **Allow-list quoted source text** (exempt `Evidence (abstract):`
  spans, block quotes, `source_artifact_ids`-derived bodies). Rejected:
  the exemption would be driven by the document's own formatting, and
  the document is written by the thing being screened — the screened
  party choosing its own exemption inverts a safety rule's trust
  direction. It also does not fix the `SOURCE_DOCUMENT` case, which has
  no quotation markup because it *is* the quotation.
- **Match only model-authored spans.** The most correct model of the
  problem, and the most expensive: it needs span provenance to survive
  from `src/llm.py` through the agents into the briefing, which it does
  not today, and `TrustClass` is per artifact rather than per span. Its
  highest-value part is already enforced upstream by ADR 0077. Left as
  possible later work; "C then B" is the coherent order.
- **Leave the rule as it is.** Viable, since the loss is graceful.
  Rejected because the loss is correlated with the benchmark's subject
  and asymmetric across the arms the experiment compares, which is the
  one shape of missing data an evaluation cannot reason around.

## What is not verified without a live call

Whether any real provider response has ever reached this store carrying
raw reasoning. Nothing measured here is evidence about that: the corpus
is fixture text and no funded run has happened. The argument is that the
retired patterns did not detect that case either, not that it cannot
occur.
