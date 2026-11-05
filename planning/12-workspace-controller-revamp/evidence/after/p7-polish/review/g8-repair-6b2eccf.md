# Independent bounded repair review

Independent `benchmark_design` review, 2026-11-05 UTC.

**No remaining confirmed P1/P2 findings in
`83b196eb14b33cd3033453701e93482266366e5f..6b2eccf069537d90423359fc74c033f27e665cd6`.**
Both original P2 findings are resolved in the repaired source. The original
[full-review HOLD](g8-full-diff-83b.md) and its counterfactual evidence remain
preserved. This follow-up assesses the repair delta, not a second full review.

- **Pending-save navigation:** `navigation.ts:28–32` consults the shared
  cancelable veto before changing intent, recording history or calling
  `location.assign`. Composer's managed form skips generic early-submit capture
  at lines 63–66. Ordinary search and route/slash commands reach the guard before
  navigation side effects; refusal retains the entered query.
- **Blocking states and cleanup:** Reader, Interests and Review register the
  veto during their existing pending/unsafe/dirty states and remove it on
  cleanup. Native-link guards, download/new-tab exceptions, exact source/version
  identifiers, draft storage and server-write payloads are preserved.
- **Routing and privacy:** native controls and fallback routing preserve their
  destinations and Radar filter contract. Accepted intent stores the destination
  path and cosmetic restoration metadata, without query text. No provider or
  source-acquisition path is added.
- **Drawer keyboard behavior:** `Shell.tsx:67` returns before trap handling for
  composition and Ctrl/Meta/Alt-modified Tab. Plain Escape and ordinary Tab retain
  close/wrap behavior.

The reviewer inspected the added tests for actual pending Reader/Interests saves
with working recovery, dirty Review judgments, unsafe drafts, vetoed history and
intent, subsequent accepted navigation and composition/modifier events at mobile
and tablet widths. The reviewer **did not execute tests or rerun browser checks**.
The reported 4,079-test full gate, 150 focused tests and actual browser evidence
remain attributed to the source owner, ROOT and browser owner respectively.

```text
repaired HEAD: 6b2eccf069537d90423359fc74c033f27e665cd6
root tree: 3a5f4ac92db86c519dcfffbd371ade7872c7c811
web tree: e4f4f72d1b49f1647fb116e52105c90b03c0335c
nine changed production files: byte-identical to the repaired commit
```

Existing browser-history draft limitations are not newly claimed fixed. This
review made no edits and performed no test, browser, service, database,
credential or provider operation.
