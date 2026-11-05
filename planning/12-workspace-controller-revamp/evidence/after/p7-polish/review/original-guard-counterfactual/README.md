# Original-source regression demonstration

ROOT created a disposable detached checkout of exact application commit
`83b196eb14b33cd3033453701e93482266366e5f`. It used the existing installed Node
dependencies through a symlink, the disabled provider sentinel, fake fetch and
browser storage. No provider, source, database or owner-data operation occurred.
Only selected new behavioral tests were copied into that checkout; application
source remained original. The checkout was removed after these receipts were
retained.

The two selected test files contain three selected cases: pending Interests
save with working draft recovery, composing Escape at 390 px, and composing
Escape at 900 px. Other tests were intentionally not selected for this narrow
counterfactual. This does not skip or replace the repaired application's full
coverage gate.

1. [First log](vitest-original-first.log) / [receipt](receipt-first.json):
   three expected failures, 35 unselected. The Interests test first encounters
   the old slash-query clearing, before its later zero-navigation assertion.
2. [Direct assertion log](vitest-original-direct.log) /
   [receipt](receipt-direct.json): three expected failures, 35 unselected. The
   copied Interests test adds the same zero-navigation assertion inside each
   loop iteration, before checking query text. It now fails first on the actual
   ordinary-search `location.assign` call while the profile save is pending.
   Both drawer cases fail because composing Escape is prevented.

Exact copied test bytes and the original-source file hashes accompany the
receipts. The second derivation changes assertion ordering only in this
disposable counterfactual; it does not modify active-worktree tests or weaken
an assertion. A later passing source-owner run and actual browser regression
must be recorded separately.
