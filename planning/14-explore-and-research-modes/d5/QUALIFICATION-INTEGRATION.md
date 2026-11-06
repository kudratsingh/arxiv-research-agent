# D5 protected qualification integration

D5 now subclasses the existing production `QualificationAdapter`, with its actual
Postgres admission, cumulative programme guard, paired count/Message journal,
pricing reconciliation, cancellation and uncertain-completion recovery. There is
no separate simplified paid implementation. `httpx.MockTransport` is injectable at
that boundary; offline replay uses exactly these controls with the disabled key.

The everyday Reader still has no paid dispatch endpoint. Its local simulation is
explicitly separate. `/workspace/qualification/results` and its owned result route
are **GET only**: they read quarantined workflow results without constructing a
provider. Saving a result uses existing revision-guarded notes/project/thread APIs.

## Permission and financial boundary

`src.workspace.d5_operator` is the separate permission recorder. Its template is
`approved=false`; it cannot infer permission from a key, old budget or packet.
The executing runner never calls that writer in provider mode. An independently
supplied owner authorization binds the packet, all case inputs, allowed stages,
principals, expiry and limits. A different input, case, schema, producer, source, project revision or transport refuses before a contact. An A-only measurement approval may later receive a separately owner-approved append-only stage grant. It binds the parent authorization, case inputs, current ledger digest and unchanged ceilings/expiry. It does not replace or renew the base receipt; each job retains its authorization chain. The runner has no stage-grant writer. Revocation is checked at
reservation, contact journalling, dispatch and again after financial accounting.

The original programme and its historical ledger remain authoritative. New D5
scope locks cover both execution and measurement principals. Complete four-stage
money/contact capacity is reserved before a draft. A named case can have only one
stable job identity. Failed/unknown work cannot be replayed under a new request ID.
Known completed invalid content is financially reconciled as failed; incomplete or
unpriced external completion retains its hold. Neither is made ready to free money.

Offline fixture databases have a persistent marker. Provider mode is categorically
refused there, even with a credential. Only that disposable mode may synthesize an
explicit fixture authorization. Repeating an offline command reuses the original
receipt without renewing expiry or reviving a stopped/revoked scope. The separate
unapproved validation database has no fixture marker and no new approved policy.

## Contract and complete workflow

The full packet preserves exact local/transformed schemas and candidate wires.
The execution record keeps one copy of selected text, handle-bound probe claims,
and hashes of redundant schemas/wires/full previews. This preserves the existing
32 KB sealed-input limit; no storage or provider token cap was raised to hide the
old duplicated-context defect. Rebuilt stage wires must match their bindings.

A workflow is draft → mandatory check → at most one repair → mandatory recheck.
Optional background/comparison/assumption/proposal prose is included in factual
review. A checker marking substantive prose unscored stops acceptance. Claims use
1–3 separate selected handles; exact quotations/offsets are server-derived. Scope,
version, parser, material hash and page-local Unicode offsets remain strict.

Actual checker/repair/recheck wires are created only from preceding durable
responses under frozen templates. Their exact digests and paired count receipts
are journalled at creation. No fictional future response-dependent request is
precomputed. Offline byte bounds and synthetic counts are not real token-fit or
remote schema-acceptance measurements.

The readonly result model retains the original question and producer. Retained
source drift hides content rather than substituting a newer source. Reader links
open exact passages, and explicit saved notes can resume the quarantined result
through Library or a learning thread. Every output remains experimental; human
support, factual acceptance and checker qualification are not inferred from a
successful pipeline or a positive machine opinion.

## Review analysis is separate from execution

`python -m src.workspace.d5_reviews` exports/validates/imports review sidecars and recomputes reports. It has no database/provider/approval writer. Reviews bind original observed packet/run/output/evidence; corrections require explicit versioned adjudication. The current producer/scorer is sealed in v3. Old v2 results remain v2 and receive an explicit new-scorer analysis receipt. No label can override failed mechanical provenance or enable generation. Actual Reader job records retain their original quarantined status; imported labels live only in analysis reports.
