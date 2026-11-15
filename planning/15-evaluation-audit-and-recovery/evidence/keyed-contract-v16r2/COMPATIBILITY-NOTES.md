# Prospective v16r2 structured-output compatibility correction

Offline only. The original v16 packet05debe21 and all historical results, schemas,
receipts and scores remain unchanged. Its draft schemas are not ready for live
activation: two of the reported cases exceed the documented union-parameter
ceiling. This successor needs a separate exact approval and creates none itself.

## Documented limits and measurement units

The [official structured-output documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
checked2026-11-15, sets aggregate request ceilings of16union-typed parameters,
24optional parameters and20strict tools. Output schemas and strict tool schemas
share those ceilings. A required nullable property consumes a union, not an
optional parameter. The provider also has unpublished grammar-size constraints
and a180-second compiler timeout; passing the explicit ceilings does not prove
remote acceptance.

The analyzer reports these distinct measurements:

- `direct_union_properties`: object properties directly using anyOf or a type array,
  counted at their physical schema declaration. Definitions are visited once.
- `anyof_nodes`: all literal anyOf nodes, including array-item unions that are not
  object properties. This is not the documented parameter unit.
- `resolved_union_properties`: also follows an alias at a property's value.
- `expanded_union_properties` and `expanded_union_nodes`: conservatively traverse
  every reachable reference use, including mutually exclusive alternatives.
  Shared definitions therefore cannot hide repeated uses. This is a safe planning
  upper bound, not a claim about the unpublished compiler's reuse algorithm.
- Optional properties are counted separately, both physically and per expanded use.
  The request guard aggregates each measure over output plus all strict tools.

| Exact predecessor case | Direct union properties | Literal anyOf nodes | Expanded union nodes | Successor direct / literal / expanded |
|---|---:|---:|---:|---:|
|campaign-dev-learn|14|15|15|4 /5 /5|
|campaign-dev-compare|21|23|34|4 /5 /5|
|campaign-eval-research-memory|18|19|19|4 /5 /5|

All these schemas have0optional properties. The supported maximum configurations
(Learn8or Research12claims,8requested parts, including Research comparison) have
9union-valued object properties and10expanded union nodes. That leaves7parameters
below the published16parameter ceiling. The additional local planning budget is
12expanded union nodes and16optional parameters; those are our conservative
headroom policies, not provider limits. Current checker, recheck and probe wire
schemas have0unions and0optional properties even at their maximum identities.
Schema byte sizes are recorded independently and never stand in for these counts.

## Versioned encoding and preserved checks

`wire_encoding_revision=workspace-assistance-keyed-encoding-v16r2` explicitly
selects the new wire representation. Omitting this marker preserves the original
v16 schemas; all10archived draft schema pairs remain byte-equivalent. The new
encoding is only selected by `freeze-v16r2`; it does not enable Reader generation.

Claims retain required named c1..c8/c12keys. c1is emitted. An unused remaining
slot is exactly `{"text":"","handles":[],"required_scope":"unused"}` rather
than a nullable object. An unused slot cannot contain prose, evidence or receive
references. Missing/extra/duplicate identities and a second model-authored ID
remain forbidden. Local validation enforces canonical emptiness and then runs
the original v16 validation on a lossless internal conversion. It never converts
or reaccepts archived failed provider output.

Answer and comparison-abstention bodies share their field definitions. Each
requested part still has one required named object and a status-specific shape:
answered references, evidence-gap reasons or omission reasons. Multiple gaps stay
in one part. Comparison-only context cannot answer a comparison. The cross-field
rule connecting global disposition, comparison bases and part-level answer roles
is checked locally before checker dispatch; it is not asserted to be fully
expressible by the shared wire body. Full abstention remains structurally separate,
has no claims/references, and declares every part lacks evidence. Application
assessment without required context remains full-abstention-only. Omission is not
silently relabelled into evidence absence.

Selected handles, exact source/version/hash/scope/Unicode spans, reciprocal
references, no orphan claims, atomicity, retained qualifications, request coverage,
prose review and whole-claim support remain mandatory. Multiple independent
findings per exact current location and complete current-response checker binding
are unchanged. Only one quality repair and mandatory recheck are available;
invalid-first-draft repair remains deferred and invalid drafts remain terminal.
Normalized persistence, reports, exports and Reader fields remain the v16 shape.

## Actual request guard and remaining uncertainty

`provider_schema_compat.guard` inspects the final SDK-transformed schema in the
actual request body before a paired count or Messages dispatch. Production adapter
checking is independent of whether a compact prompt projection retained the marker.
The policy and marker are sealed in inputs and packet metadata; missing, unknown
or changed bindings fail closed. Dynamic check/repair/recheck schemas are guarded
when derived from their actual preceding output; future responses are not invented.

The guard rejects documented ceiling violations, planning-headroom violations,
recursive/external/unresolved references and unsupported composition shapes. The
protected mocked campaign records every transmitted Messages body and its guard
receipt. It tests all44stages across14jobs, including one repair/recheck per workflow
and four checker batches. These are synthetic counts/usage/judgments, not actual
provider token measurements or scientific/human evidence.

The inherited Sonnet5.5medium/Opus5.5High routes,8k/12koutput budgets,32kmeasured
input fit,40kmonetary input reservation,60/120/240-second operation deadlines and
1200-second workflow deadline remain unchanged. The120-second draft deadline is
shorter than the documented compiler stop-gap; remote compilation latency remains
an experimental risk, never an excuse to retry or infer cancellation/zero usage.
Both development paths must establish remote schema acceptance and complete bound
checker contracts before unrelated exposed evaluation controls/probes advance.

## Unchanged financial and evaluation scope

The read-only baseline remains37jobs/71Messages/96counts/USD2.138481known estimate
plusUSD0.875066overlapping historical holds counted once. No live grant, migration,
cap/expiry change, settlement or provider/count contact occurred. The successor
retains14jobs/44Messages/44exact automatic paired counts/USD14maximum, within the
existing64/160/200/USD20programme and2026-11-21T11:03:57Zexpiry. No standalone count
pass, split paid workflow, additional identity or implicit financial change is added.
All retrieval/cohort/reference/scoring/answerability semantics and old failures
remain unchanged. Human qualification stays outside scope; owner workspaces,
everyday generation, recurrence and notifications remain untouched/disabled.

Verification logs, failed development attempts, source/history and final exact-head
CI evidence belong permanently under arxiv-evidence/d5-union-compatibility-20261115.
The final successor package carries exact bindings and one inactive approval request.

All rights reserved. No license or reuse permission is granted.
