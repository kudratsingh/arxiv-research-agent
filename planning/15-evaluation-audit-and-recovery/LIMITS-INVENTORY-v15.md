# D5 v15 prospective limits inventory — baseline before changes

This is a source inventory of frozen application commit `b17bb4f29c094d0c033de9db342c8dce9f643add`, not an approved v15 policy, provider fit measurement, execution receipt, or quality finding. Paths and lines below refer to that commit. The stopped v14 evidence at `arxiv-evidence/campaign-live-v14-20261114T000552Z` is immutable. The supplied accounting baseline is 36 jobs, 70 messages, 95 counts, $2.110597 known estimated usage and $0.875066 retained holds; it is not a fresh ledger census. Do not confuse output tokens with characters, bytes, or provider billing, or treat timeout as remote cancellation. Replacement values and approval remain coordinator policy pending.

| Surface and BEFORE value | Enforcement, inheritance and consequence |
|---|---|
| Selected evidence: 8 units, each up to 1,600 Unicode characters | `src/workspace/assistance_contract.py:37`, `:111`, `:567`; sentence packing does not split long sentences silently. Each claim has 1–3 handles (`:166`). |
| Draft: 6 claims, each text up to 360 Unicode characters; 1–3 gaps and questions; 360-character prose fields, 180-character abstention | `src/workspace/assistance_contract.py:39`, `:166`, `:177`, `:233`, `:330`, `:421`. Six is repeated, not just one constant: compact IDs `c1`–`c6`, references ≤6 and claims 1–6 at `src/workspace/assistance_compact_draft.py:46`, `:55`, `:178`; procedural references and coverage status shapes repeat limits at `src/workspace/assistance_contract.py:406`, `src/workspace/assistance_coverage.py:127`, `src/workspace/assistance_coverage_shapes.py:49`. The `claim_budget` label literally says six (`assistance_coverage.py:49`); prompt instructions repeat it (`assistance.py:252`). Omitted coverage is not evidence absence. |
| Requested parts: 1–8, each request ≤4,000 characters; ordered p1…p8; coverage references ≤6 | `src/workspace/assistance_policy.py:42`, `src/workspace/assistance_coverage.py:55`, `:68`, `:109`, `:127`; compact groups each cap 8 and must cover each sealed part once (`assistance_compact_draft.py:66`, `:241`). |
| Draft 8,000 UTF-8 bytes at multiple layers | Raw text is capped in D5 response validation (`src/workspace/d5_adapter.py:1043`); decoded JSON payload is serialized with `ensure_ascii=False` and default separators and checked at `src/workspace/assistance_compact_draft.py:237`, `:278`, `src/workspace/assistance_coverage.py:252`, `src/workspace/assistance_policy.py:172`; normalized models also validate `model_dump_json()` bytes (`assistance_contract.py:198`, `:277`, `:460`). These are different representations, so one passing does not imply all pass. Wire descriptions include whitespace and local limits (`assistance_contract.py:329`, `:351`). |
| Compact checker reasons: nonblank, ≤96 Unicode characters, ≤120 raw UTF-8 bytes, ≤120 JSON-escaped UTF-8 bytes excluding surrounding quotes | `src/workspace/assistance_compact_checks.py:24`, `:34`, `:43`. `json.dumps(..., ensure_ascii=False)` accounts for escaping. Prompt repeats 96 characters and 120 JSON bytes (`assistance.py:265`); normalized legacy rows also cap reasons at 240 characters (`assistance.py:145`, `:153`, `assistance_coverage.py:354`). Local validation remains necessary after SDK schema transform. |
| Compact checker cardinality: ≤6 claim rows, ≤8 part rows, ≤10 findings; indexed prose 0–2 | `src/workspace/assistance_compact_checks.py:67`, `:90`, `:99`. Unique claim/part IDs and prose locations are required. Every claim has support, atomicity and four qualification judgments; normalization duplicates the shared reason and claim identity into support and quality rows (`:132`). Existing `CoverageChecks` independently caps 6 support, 6 quality, 8 part and 10 prose rows (`assistance.py:168`, `:206`). Exact inputs and locations are checked by `assistance_coverage.py:401`, `assistance.py:193`, `d5_adapter.py:1037`; absence or excess is not a passing default. |
| Compact and expanded checker output each ≤8,000 UTF-8 JSON bytes, independently of raw text cap | Compact canonical serialization uses no spaces (`assistance_compact_checks.py:112`, `:117`); after expansion and legacy validation it is checked again (`:142`, `:162`). Raw original text including whitespace is separately ≤8,000 (`d5_adapter.py:1043`). Example only: preserved v14 contract describes a legal maximum-cardinality location selection with 120-byte reasons yielding 6,581 compact and 7,973 expanded bytes; 27 bytes of remaining headroom is not a universal worst-case proof (`planning/15-evaluation-audit-and-recovery/CHECKER-COMPACT-CONTRACT-v14.md:83`). |
| Schema conversion | Local dynamic schemas bind selected handles and part IDs (`assistance_contract.py:565`, `:620`, `:624`; `assistance_compact_draft.py:76`); SDK `transform_schema` produces a distinct wire schema. Fixed enum conversion exists because transform drops `const` (`assistance_coverage_shapes.py:26`). Draft/checker construction and transformed-schema binding occur in `assistance.py:222`, `:458`, `d5_adapter.py:350`, `:363`, `:717`. Constraints absent on wire still apply locally; no inference of provider acceptance from an offline transform. |
| Raw transport vs model-output payload | Sealed D5 HTTP response cap 131,072 bytes (`d5_adapter.py:248`, `:535`); streaming accumulation rejects over that size (`provider_adapter.py:614`, `:634`). This is the entire HTTP body and is not the 8,000-byte text, compact or normalized JSON budget. Opus structured verdict permits up to 16 content blocks, optional thinking blocks followed by exactly one text verdict (`d5_operations.py:81`). D5 rejects malformed or duplicate-key/nonfinite JSON (`d5_adapter.py:1009`), incomplete or incorrect completion via inherited contact processing (`provider_adapter.py:614`). |
| Output and input tokens | v14 routes inherit Sonnet 5.5 draft/repair 20,000 input, 4,000 output and Opus 5.5 check/recheck/probe 20,000 input with output raised from 3,200 to 8,000 (`d5_operations.py:26`, `d5_campaign_v14_policy.py:16`); Opus output includes thinking. Paired token count must be ≤16,000 (80% of the 20,000 raw input cap): `provider_adapter.py:591`, `:733`, `d5_measurements.py:165`. Post-call usage is capped at 20,000 input and the selected wire max tokens (`d5_adapter.py:1057`). Count is a distinct provider contact, not an offline byte estimate. |
| Four-stage workflow and reservation arithmetic | Draft → mandatory check → at most one repair → mandatory recheck; `d5_adapter.py:727` rejects a fifth step. `assistance.py:294` constructs per-stage serialized input envelopes with a **hardcoded 6 ×** selected-unit size, output 8,000 bytes per call and 4 × reservation; internal output ≤64,000, maximum stage ≤128,000 and total ≤512,000 bytes. Per-phase actual bodies checked at `d5_adapter.py:791`; offline fake path also checks `assistance.py:737`. Changing claims, units, reason size or representations requires re-deriving these bounds, not just changing schema fields. |
| Local fake executor budgets and lease, distinct from provider | `_size` counts serialized UTF-8 bytes despite counter names; per-call input/output 64,000/32,000, totals 256,000/128,000, source 8,000 bytes and 4 spans for summary; deep-dive multiplier 2 (`executor.py:232`, `:236`). The local fake execution enforces per-call and aggregate limits before stages (`:763`, `:818`); 120-second fake lease and late-worker fence (`:46`, `:798`, `:887`). These are not evidence of a 120-second provider lease. |
| Deadline, cancellation, recovery | Count/draft/repair 30 seconds, check/recheck 120 seconds, overall workflow 480 seconds measured from durable reservation creation (`d5_deadlines.py:10`, `:32`, `:48`); each contact gets the lesser of its stage limit and remaining workflow time; outer wrapper also checks remaining time (`d5_adapter.py:499`). In-flight cancel/recover conservatively retains unknown exposure (`admission.py:502`, `:530`; `provider_adapter.py:643`); fake recovery separately records unknown input/output and fences late responses (`executor.py:1011`). Timeout does not prove remote cancellation. |
| Monetary and campaign ceilings | v14 packet policy sets 14 new jobs, 44 messages, 44 counts, $12 campaign ceiling, concurrency 1, $0.65/workflow, $0.25/probe, $1 headroom, $7.50 new; cumulative programme ceiling 49 new jobs, 112 messages, 137 counts, $12 (`d5_campaign_v14_policy.py:23`). Complete-stage reservation uses route input/output and prices for two drafts plus two checks, or one check for a probe (`d5_operations.py:70`; `d5_scope.py:275`). Admission preserves unknown and checks remaining reservation (`admission.py:231`, `:412`, `:502`). Values are sealed for v14 and cannot authorize a successor. |
| Probe and report path | Probes are not automatically the compact v14 checker: their bound wire checks `transform_schema(Checks)` (`d5_adapter.py:715`), with route and raw text/transport gates still relevant. Reports bind the current checked response and validate the selected model, review and prose locations (`d5_report_binding.py:136`, `d5_campaign_report.py:135`). Results preserve job and reservation amounts (`d5_results.py:38`, `:122`). The output cap change must be checked against probe wire construction and report revalidation, not assumed inherited. |
| Persistence and Reader | Provider contact responses are journaled; bounded complete HTTP bodies are preserved with redaction (`d5_adapter.py:428`). No separate persistent text truncation was established by this source pass. The qualification Reader maps stored claims and handles without an explicit six-row slice (`web/components/workspace/QualificationResult.tsx:89`; `ScoredSections.tsx:23`); this source observation is not browser acceptance. Other Reader selection/preview truncations are separate: `ReaderContent.tsx:370` takes 400 selected characters, `:1024` previews 100 entry-body characters, and `SyntheticWorkbench.tsx:366` previews 180 span characters. |

Before choosing successor limits, enumerate every repeated numeric literal and ID vocabulary above, trace worst-case JSON escaping and normalization expansion, rederive envelope and reservation arithmetic, and exercise complete production-path synthetic boundary cases including probes, report binding and Reader. Tests and local arithmetic cannot prove provider acceptance, quality, billing settlement, or live behavior. Preserve stopped inputs, raw results and holds; no provider or token-count contact, live ledger write, replay, or grant is authorized by this inventory.

## Prospective v15 qualification policy

The centralized prospective policy (`src/workspace/d5_capacity_policy.py`) seals 8 Learn / 12 Research claims; 12 selected units, 3 materials, 128 KiB selected-evidence JSON, 3 Learn / 6 Research citations per claim, 8 requested parts, 16 prose findings; 500-character claim and 240-character reason observations only, never content rejection. Separate byte protections are 131,072 draft, 262,144 compact checker, 1,048,576 normalized checker, 8,388,608 internal/sealed input and 4,194,304 HTTP bytes. These do not imply model token fit. It proposes 40,000 reserved input tokens, 32,000 paired fit, Sonnet 8,000 output, Opus 12,000 output; 60/120/240-second count/draft-or-repair/check-or-recheck limits and 1,200 seconds overall. These are prospective values, not retroactive changes or execution permission.

The baseline audit omitted another inherited bound: `GenerationInput.snapshot` checks at most 10 sources, private question ≤4,000 Unicode characters, and serialized JSON ≤32,000 characters (`src/workspace/admission.py:98–130`); those are distinct from 8 MiB UTF-8 bytes. The frozen baseline route validation only accepted legacy/v14 (`src/workspace/d5_operations.py:46`), and the frozen D5 settings check pinned old input and HTTP limits (`src/workspace/d5_adapter.py:535`). A policy object alone does not alter these gates. For budget calculations, rate assumptions, fresh census, expiry and approval boundaries see `PROVIDER-BUDGET-v15.md`.


## Before and prospective after in one table

The v14 BEFORE column is frozen source behavior. The v15 column describes the integrated prospective policy, subject to the exact verification receipt and never execution approval. Everyday assistance and historical qualification revisions retain their own legacy contracts; the v15 column applies only to a newly sealed v15 qualification path. Source locations for the BEFORE values and enforcement dependencies are in the detailed table above; prospective values are in `src/workspace/d5_capacity_policy.py` at the integration head.

| Surface | v14 before | Prospective v15 qualification policy | Boundary / dependency |
|---|---|---|---|
| Claims and identities | ≤6, c1–c6 | Learn ≤8; Research ≤12 | Update IDs, references, schema, checker and reports together. Everyday legacy remains ≤6. |
| Selected evidence and citations | ≤8 selected units, ≤1,600 characters/unit, ≤3 handles/claim | ≤12 selected units, 3 materials, 128 KiB selected-evidence JSON, ≤3 Learn / ≤6 Research citations/claim | Source unit text and extraction limits remain separate; no unsupported evidence is invented. |
| Requested parts / findings | ≤8 parts, ≤10 prose findings | ≤8 parts, ≤16 findings | Preserve exact mapping and finding location validation. |
| Claim text / checker reasons | Claim ≤360 Unicode characters; reason ≤96 characters, ≤120 UTF-8 bytes and ≤120 escaped JSON bytes | 500-character claim and 240-character reason observations; explicit generous 10,000-character factual-claim safety guard; aggregate protection still applies | Observations do not reject, truncate or confer support. Historical schemas remain unchanged. |
| Draft, raw and normalized | 8,000 UTF-8 bytes at distinct raw, serialized and normalized draft gates | 131,072 UTF-8 bytes draft | Check all representations and explicitly distinguish raw whitespace from canonical JSON. |
| Checker compact / normalized | Each ≤8,000 serialized bytes; raw text separately ≤8,000 | Compact ≤262,144; normalized ≤1,048,576 bytes | Fourfold allowance for duplicated reasons and metadata; it is headroom, not a proof every compact payload fits after expansion. |
| Internal and sealed input | 64,000 internal-output, 128,000 per-stage, 512,000 aggregate capacity; serialized sealed input 32,000 characters | 8,388,608 bytes internal and sealed JSON | Eight MiB offers space for repair JSON escaping and normalized checker payloads; actual serialized stage checks and paired token count remain decisive. The 32,000-character legacy gate is separate. |
| HTTP body | 131,072 bytes | 4,194,304 bytes | Entire streamed HTTP body, including reasoning, differs from model-output text. |
| Per-call token admission | 20,000 reserved input, 16,000 paired fit; Sonnet output 4,000, Opus 8,000 | 40,000 reserved input, 32,000 paired fit; Sonnet output 8,000, Opus 12,000 | Outputs include thinking; byte capacity does not establish token fit. Exact provider count remains required. |
| Deadlines | Count/draft/repair 30s; check/recheck 120s; workflow 480s | Count 60s; draft/repair 120s; check/recheck 240s; workflow 1,200s | Overall deadline starts at durable reservation and limits each contact; timeout is not remote cancellation. |
| Workflow and probes | Up to four messages, one repair; four separately bound probe batches | Same workflow and separately bound probe shape | Update probe schemas, count linkage, route selection and report reconstruction independently. |
| Cost and programme | v14 sealed ceilings, immutable actuals and holds | Proposed $1.20/workflow, $0.50/probe; $14 new cap total; programme $20 | Exact arithmetic, $2 buffer and 1.014337-dollar remaining margin in `PROVIDER-BUDGET-v15.md`; no extra execution authority. |
| Reader / persistence | Stored raw contact and step JSON; claims shown without six-item display slice | Synthetic twelve-claim Reader test and inspectable complete stored checker reasons | UI tests prove local rendering only; they do not prove live browser acceptance, support or human review. |
| Fake/offline lane, leases and recovery | Local fake executor has separate bytes-as-units budgets and 120-second lease; durable provider unknown holds retained | Legacy fake controls remain separate unless explicitly versioned; preserve uncertainty and late-response fences | No inference that provider deadline extends an unrelated fake lease or that a timeout settles liability. |

### Explicit semantic and procedural guards

The prospective factual statement safety guard is 10,000 Unicode characters per
claim, centralized alongside its soft 500-character target. This is enough for
ordinary attributed scientific prose; the checker must still reject bundled facts.
The unchanged grounding guard provides the same upper protection for claim digests
and review. It is not a concision or factual-support threshold. Checker explanations
have no individual character cap, and all full text remains accessible.

There are at most three procedural gaps and three follow-up intents, and twelve
selected coherent units from at most three materials. A unit is at most 1,600
characters; exact source/Unicode offsets are retained. Selected-evidence JSON has
an independent 131,072-byte cap. Oversize sentences are unavailable rather than
clipped into a misleading quotation. These are sealed scope/cardinality protections,
not evidence of source completeness or measured provider token fit.

### Remaining retained input, extraction and storage limits

| Limit and purpose | Effective enforcement in the successor | Decision |
|---|---|---|
| Work/version identifiers300characters; input sources10; question4000 | `assistance.AssistanceInput`, `admission.GenerationInput.snapshot`, `context_schemas.ProjectData`, `assistance_coverage.RequestedPart`, qualification-only `d5_capacity_selection.QualificationSelection` | Keep finite identity/request bounds. The public legacy follow-up remains1000; qualification follow-up matches the4000-character sealed question. Research whitespace normalizes once before both persistence and sealing. |
| Safety context four fields, each1000characters | `assistance_policy.ApplicationContext` and sealed task policy | Keep explicit finite application inputs; absent required context forces full abstention. No model-authored workaround. |
| Retained acquisition8MiB,12pages,120000characters; source spans2000characters | `material.MAX_PDF_BYTES`, `MAX_PAGES`, `MAX_CHARS`, `MAX_SPAN_CHARS`, bounded extraction worker | Unchanged acquisition guards, independent from selected coherent units≤1600characters. No acquisition, page expansion or full-paper claim is authorized here. |
| Source/material/version hashes and exact Unicode offsets | `material`, `assistance_contract.coherent_units`, `grounding._resolve`, `claim_input_digest`; selected-unit equality in `d5_capacity_selection.build` | Keep exact mechanical provenance and selected-span enforcement. Separate citations never join nonadjacent text. |
| Notes10000Unicodecharacters; thread goal4000/title240/prerequisite2000 | `context_schemas`, `QualificationResult.fullNote/referenceNote` and existing server mutations | Preserve existing durable API limits. A large result saves an explicit exact-version result link rather than truncating its claims; complete retained output stays available. Short note requests are unchanged. |
| Navigation return4000; ordinary query values500/cursor2048/fragment500 | `context_schemas.ResumeContext.safe_return`, existing Reader/context helpers | Keep local navigation and anti-redirect guards. Evidence anchors are compact page/offset IDs, never copied narrative text. |
| Provider content blocks16, final text exactlyone | `d5_operations.verdict_text` | Keep bounded reasoning/envelope validation; thinking counts toward output allowance. No tool calls or malformed/missing final verdict may pass. |
| Python CI aggregate45minutes before; proposed60minutes | `.github/workflows/ci.yml`, `jobs.tests.timeout-minutes` only | Prior exact-head CI35m57s plus new replay273s and protected controls208s leaves insufficient variation margin. Keep every selection/floor/step network bound/per-test timeout unchanged. Verify remote CI independently. |

The actual prospective enforcement entrypoints are `assistance_capacity_contract`
for wire/local cardinality, raw/normalized protection and references;
`d5_capacity_wire` for prompts/model/settings/schema; `d5_adapter` for request,
provenance, normalized internal views, usage and complete/partial receipts;
`admission.GenerationInput.snapshot` for sealed JSON; `d5_deadlines` and inherited
`provider_adapter._post/advance` for contacts/recovery; `d5_scope` plus append-only
`d5_campaign_v15_extension` for reservation and programme admission;
`d5_report_binding/current_check` and `d5_campaign_report` for current assessments;
and `QualificationResult` for complete Reader display and durable link saving.
The separate public fake executor retains its historical byte-based budgets and
lease. Qualification preparation no longer inherits that fake preview's8-unit or
16000-byte selection cap.

Qualification result listing is owner- and exact-work/version scoped and limited
to20jobs in `d5_results.QualificationResults.jobs`; the proposed campaign has at
most14 identities under its distinct principal. The runner's full census does not
use that UI list. Complete selected-job data and reasons remain inspectable; this
batch's Reader tests establish local rendering and exact saved links, while remote
browser acceptance remains separately identified in CI.

## Profile-backed runtime correction and successor binding

Candidate243 and its cancelled CI43556087526 remain retained. The successor
applicationa0ad5c2c changes onlyranking.py among78producer files: a missing required
literal skips an impossible regex match, while every possible positive still uses
the unchanged Unicode boundary/plural regex.34controls preserve frozen-corpus
rankings and filters. The same profiled checkpoint call38.65→12.24s, regexsearches
1492597→66645;50affected CI-shaped coverage controls pass,max11.48s. No timeout,
selection, coverage input/floor, schema, evidence, threshold or model changes.
Packet25eec8f541dbe7f70bf2fadee59f51c0d8b456980856cd4f38fce20b139e8bde is separately
frozen and unapproved; old candidate243 never grants its authority.
