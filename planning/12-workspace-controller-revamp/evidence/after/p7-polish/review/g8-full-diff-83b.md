# Independent G8 review — original finding preserved

Reviewed on 2026-11-05 UTC by the independent `benchmark_design` agent.
Scope: full controller revamp `916f038..83b196eb14b33cd3033453701e93482266366e5f`.
This is the review of the original frozen source, **not a clean signoff on a later
repair**. No source edits, test runs, browser operation, services, database,
credential access or provider contacts were performed by the reviewer.

## Confirmed P2 — composer search bypasses pending-save navigation protection

`web/components/workspace/Composer.tsx:49–57` calls `location.assign` for an
ordinary search. The existing Reader and Interests blocked-state effects
intercept anchor clicks, while their `beforeunload` handlers warn only for a
draft without browser recovery (`ReaderContent.tsx:140–160` and
`Interests.tsx:53–64`). Consequently, with working browser recovery and an
in-flight save, normal route links are blocked but composer search can unload
the pending request. G8 remains HOLD until repaired and verified. A recoverable
draft does not make an in-flight save safe to abandon.

The reviewer also referred a drawer IME/modifier-key edge to the source owner
for focused confirmation: Shell's drawer trap handles Escape/Tab without the
guards used by the command/dialog handlers. Its status at this review checkpoint
is **awaiting focused source-owner confirmation**; it is not claimed as a
browser-reproduced finding here.

## Five assessed lenses

- **Product truth:** inspected copy, route/mutation boundaries, exact versions,
  materials and retained-source hashes. Save request bodies and
  server-acknowledged success semantics are preserved apart from the navigation
  bypass above. No quality, source acquisition or paid-generation qualification
  is inferred from software checks.
- **Accessibility:** inspected native form associations, modal ownership,
  command availability/focus behavior, keyboard dispatch and the drawer edge.
  Actual axe and browser results belong to the separate browser receipts.
- **React correctness:** inspected stale command identity, module-load
  active/key guards, retry, editor identity and hash synchronization. The
  confirmed navigation finding remains blocking.
- **Visual fidelity:** directly inspected 14 final PNGs: all seven routes in
  desktop/light and mobile/dark. No confirmed visual defect in those saved
  states. This does not replace recordings, live geometry or interaction checks.
- **Budgets and CSP:** verified `ceil(23940 * 1.06 / 512) * 512 = 25600`, below
  the unchanged hard cap. All seven live-route JavaScript ceilings remain
  169,984 bytes. CSP, budget checker, fictional preview styling, learning and
  backend source paths remain unchanged from the original base. No improvement
  in settled transfer is inferred from first-load budgets.

## Exact-source verification

The reviewer verified all 609 web-file hashes and both gate-log hashes in
`final/source-binding.json` against the frozen source and evidence:

```text
application commit: 83b196eb14b33cd3033453701e93482266366e5f
web tree: b7b21f1d9fbb0daa25fa3f9792a01f74ead26eef
canonical 609-file manifest SHA-256:
b218733d2f7f12dfb53a8218aad2e23e2950f7cc379375a5c78e9d1ccc161cec
```

Later repair verification must be attributed separately. Preserve this finding
and the earlier passing/failed attempts rather than rewriting this review as
clean or attributing old browser results to changed source.

## Final original-source disposition: HOLD — two confirmed P2 findings

The source owner subsequently confirmed the drawer edge in mounted tests with
an actual focused input at 390 and 900 px. Original `Shell.tsx:67–72` consumes
composing Escape; lines 84–87 wrap Tab without modifier exemptions. The repair
reportedly passes 133 focused tests, which this independent reviewer did not
execute. Thus **both the search bypass and drawer key handling are confirmed
P2 findings at 83b**. A later repaired commit requires its own review and runtime
attribution. All five lenses above are assessed; there is no other confirmed
finding from this full review.

ROOT independently ran the selected regression tests against a disposable
detached checkout of the original source. The final counterfactual has three
expected failures: a real pending-profile search calls
`location.assign('/workspace/radar?q=pending+profile+query&days=7')`, and composing
Escape is prevented at both widths. The first attempt also exposed slash-text
clearing before reaching its navigation assertion; both logs and the explicit
test-assertion derivation are preserved in
[original-guard-counterfactual](original-guard-counterfactual/README.md).
These intentional failures are regression evidence, not a passing gate. ROOT
removed only that disposable checkout after retaining the evidence; no active
application source, owner data, services or credentials were changed.
