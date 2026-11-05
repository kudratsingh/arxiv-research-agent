# Inherited P6 same-document Reader fragment gap

This is a confirmed failure on the unchanged P6 production preview at port3148,
not a P7 regression. The baseline binding is commit
`dff860e16e89c22382bce88d98f64645dfdcbfc8`, tree
`43c5f34c0f238909a8b1fe65684de3a917cb0a5e`, build
`FqOkJwvSTsd5JfZCNhztE`; see [binding](../../baseline/source-binding.json).
All data is explicitly synthetic offline preview data. No scientific or source
freshness conclusion follows from this test.

The [four-context sequence report](../../baseline/geometry/report.json) reaches
the initial title/two-line clearance, queue selection from scroll870, rapidJ/J/K,
Radar page2, native Read click, Back restoring870, and Forward. In all four
desktop/mobile and light/dark contexts, assigning the new same-document
`#abstract:2500:2520` then fails to create `mark#source-anchor`.

The independent [diagnostic report](report.json) waits for network idle and the
actual enabled Reader control after Forward, then verifies:

- Work `arxiv:2611.99800`, exact version `arxiv:2611.99800:v1`.
- Rendered source text exactly equals all4059 Unicode characters of the retained
  abstract.
- Offsets2500:2520 select the valid20-character text `is intentionally lon`.
- The requested URL has the same origin/path/query and the correct new hash.
- One actual browser `hashchange` event fires with that target URL.
- After a bounded5-second assertion, no mark exists; the source remains intact.
- Zero attempted mutations/external requests/page errors; persisted workspace
  state stays identical, excluding only the per-response `as_of` clock.

The [screenshot](after-forward-far-hash-no-mark.png) preserves the failed state.
No cold reload, forced scroll, new version substitution, or source edit was used.
Static inspection corroborates the behavior: Reader stores its fragment and
source anchor only at initialization; the navigation runtime's hash listener
scrolls an existing target without updating Reader's selected passage.

The earlier Radar-query mismatch is separately archived under
`../../pre-fix/geometry-radar-query`; it is a harness setup failure and is not the
failure described here.

Diagnostic report SHA256:
`eeed3e4ef464ed31948abed4fd038b1abaa4b06dd23ba71226ebfd3674eb1ba4`.
Screenshot SHA256:
`cac75a55e3d72fbdf5340aa4e129c1ef4c055594a8abe0c690607cd2d5db9188`.

Reproduce from the P7 worktree root with the existing dependency installation:

```sh
NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-controller/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p7-polish/hash-diagnostic.cjs
```

This command reads only port3148 and blocks browser mutations and external
traffic. Its recorded actual run is [command.log](command.log).
