# Grounded summary and guided deep-dive qualification proposal

Refreshed 2026-11-03 after the actual wire adapter became testable with mocked
transport. **Unapproved and unexecuted.** Neither this packet nor its JSON
companion is an approval record. Provider calls and spend remain zero;
recurrence is disabled. All workspace PRs remain unmerged.

## Two different decisions

A bounded measurement/qualification experiment needs its own explicit approval.
It may use an **unqualified** checker to discover its failure modes. Checker
qualification is an outcome to measure, never a circular prerequisite for
running that experiment. Experimental outputs remain quarantined and labelled;
they cannot enable everyday generation. Real grounded summaries and guided deep
dives are the next product milestone, conditional on measured quality and a
separate everyday-use decision.

1. Review the source/context, initial wire requests and blank claim/span cases.
2. Optionally approve **measurement only**: at most four initial
   `/v1/messages/count_tokens` requests, no generation. This transmits the same
   selected public text, instructions and schema. No contact is authorized now.
3. Separately approve the candidate **three summaries and one excerpt study**:
   at most sixteen Messages requests and sixteen paired count requests, one
   job/call at a time. If measurement-only happened first, the combined maximum
   is twenty count contacts plus sixteen Messages contacts. Initial counts are
   deliberately repeated to keep execution's admission check current.
4. Human review assesses claims, support checks, omissions, source scope and
   usefulness. Retain disagreements and abstentions. Four jobs do not establish
   a reliable false-pass bound. If quality evidence is insufficient, prepare a
   larger, separately approved checker experiment; keep everyday use closed.

Token counting is currently documented as free and rate limited, but it is
still provider contact and requires approval. Its result is an estimate, not
an invoice or a guarantee of subsequent usage.
[Official counting documentation](https://platform.claude.com/docs/en/build-with-claude/token-counting).

## Model, settings and accounting

The deliberately narrow initial route is `claude-sonnet-4-6` for both workflow
and checking, with an exact repository capability row. The official model page
was checked 2026-11-03: active/legacy, ordinary input/output prices **$3/$15 per
million tokens**. Prices remain **ESTIMATE**, not measured spend. Other routes
are outside this adapter/approval and require their own binding/measurement.
[Official model specification](https://platform.claude.com/docs/en/models/sonnet-4-6/overview).

Wire settings: draft/repair temperature0.2, checker0.0, thinking disabled
(field absent), effort absent, structured JSON, prompt caching absent, no tools,
redirects or automatic retries. Hard wall timeout30s, response bound128KiB,
concurrency one, one repair with mandatory recheck. The SDK's public schema
transform and the gateway's request builder are reused; no SDK client is built.
Actual remote schema acceptance remains untested. MockTransport tests provide
synthetic usage integers, never measured tokens or invoice-backed costs.

Workflow, checker and unknown liability remain separate. Atomic Postgres
admission binds approval provenance, one named request ID, sealed input digest,
model, settings, schemas, retained material hashes and selected spans. Changing
a request ID cannot start another approved job. Each request/count body and its
digest is journalled before transport; source, settings and policy are rechecked
before contact. A lost contact is uncertain, fenced and never automatically
replayed. Cancellation can discard a late output while retaining its usage
receipt. Known response usage is priced provisionally; unknown billing reserves
the unconsumed envelope and prevents further admission. Caps are admission/stop
controls, not a promise that an external provider can never overshoot.

## Exact public source/context

The JSON companion retains the four source identities, hashes, parser versions
and study span selection. Run the **read-only, zero-contact** packet builder:

```sh
cd /private/tmp/arxiv-agent-eng-workspace-readiness
POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15438/workspace \
ANTHROPIC_API_KEY=local-preview-disabled \
/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python \
  -m src.workspace.qualification --owner personal-local \
  --output outputs/workspace-readiness/trial-packet.json
```

This exports exact **initial** Messages and count bodies, schemas, settings,
digests, all selected source characters and24 unlabelled claim/span cases. It
writes no approval, job, note or judgment. Later checker/repair requests depend
on future outputs: their construction rules are reviewable now, but their exact
bodies can only be sealed, retained and counted immediately before dispatch.

| Candidate | Actual retained context | Scope |
|---|---|---|
| Summary1 | KEEPER, `arxiv:2610.41482`, metadata revision `e5c832a06d88973f` | Abstract only |
| Summary2 | Knowledge-relation extraction, `arxiv:2610.41552`, revision `1c364e8ae805a931` | Abstract only |
| Summary3 | Google Research sleep-framework revision `42d6cea8785311a4` | Feed excerpt only |
| Guided study | ReAct `2210.03629v3`, three selected spans on original PDF page3 | Excerpt only; not a whole-paper study |

Private notes, drafts, preferences, implicit questions, reading history and
unrelated files are excluded. No source instruction is executed. The guided
study separates findings, labelled inference, assumptions, limitations and
proposed experiments. Proposals are never reported experimental results.

## Proposed envelope and ceilings

Uniform stage ceilings replace the earlier draft's differing per-stage limits,
so the exact adapter contract and arithmetic are easy to inspect. The study
input ceiling is intentionally smaller; if its complete request does not fit,
stop and return for a revised selection/approval rather than truncate evidence.

| Job | Input/output per call | Max generation/count contacts | Raw max workflow/checker | Raw total | 1.25× | Reservation |
|---|---:|---:|---:|---:|---:|---:|
| Each summary | 8,000 /1,200 | 4 /4 | $0.084 /$0.084 | $0.168 | $0.210 | $0.25 |
| Excerpt study | 12,000 /2,400 | 4 /4 | $0.144 /$0.144 | $0.288 | $0.360 | $0.40 |

Three summaries plus one study total raw maximum **$0.792**, margin-adjusted
**$0.990**, rounded reservations **$1.15**. Proposed trial/day/month ceiling
remains **$1.25**. No discount or cached-token saving is assumed. A two-call
path has half the four-call envelope; actual usage and usefulness are unknown.

Before **each** generation call, its exact model-specific count estimate times
1.25 must fit that call's input ceiling. Output `max_tokens` is sent on the
wire. Record actual response usage separately; stop on missing, negative,
boolean, unpriced cached, excessive or unknown usage. No fake byte counter can
satisfy token measurement. If the count or structured schema is rejected, stop
without trying a looser schema or a different model.

## Representative review and acceptance

The24 cases cover verbatim source statements, unsupported generalizations and
numbers, missing evidence, wrong versions, scope violations, extraction faults,
and labelled experiment proposals. Every human label/reason/annotator and checker
verdict starts null. Engineering challenge names are not ground-truth labels.
Mechanical identity/scope rejection is recorded separately from factual support.
The initial24-case pool uses three text sources; scientific PDF region review
remains in the extraction inspection and must be sampled separately for a larger
checker qualification. Cases sharing a source are correlated; that binomial illustration is not a
qualification bound for this pool. The cases are prepared for review, not automatically sent
to a provider by the four-job experiment.

Human review should inspect every emitted claim/span pair, missed major claims,
unsupported assertions, abstentions, wrong-version use, fabricated numbers,
privacy/context leakage, scope disclosure and whether the result helps the
research question. Preserve denominators. A0-error tiny sample is not a
qualification: even assuming independent labels,0false passes among12negative labels has an approximate
one-sided95% upper bound of22%. Everyday quality criteria and an adequate
representative negative set must be approved before declaring qualification.

Stop immediately on revoked approval, source/model/settings/schema drift,
request/call/token/budget limits, unknown completion, cancellation, failed JSON,
fabricated source/number or unsupported factual finding. A repair consumes one
of four calls and is always checked again; unresolved claims remain visibly
unsupported/abstained in the quarantined result.

## What is established and what remains

Established locally: durable manual reading; selected material retention;
model/settings/schema/source binding; actual wire serialization; mocked-transport
count/admission/response handling; reservations; split accounting; bounded repair
and recheck; cancellation and uncertain completion fences; exact initial request
export. These are mechanical tests, not model-quality evidence.

Awaiting a separate owner decision: any provider contact (including counts),
actual token/remote-schema measurements, the bounded paid experiment, human
claim/span and usefulness judgments, subsequent checker qualification and an
everyday-use policy. No approval row, credential or recurring schedule has been
created by this batch. Paid `/workspace/generate` still refuses before client
construction. The real adapter is only reachable through an explicitly
configured qualification harness, not the public reader controls.
