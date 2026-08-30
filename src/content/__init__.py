"""Repo-shipped learning content: manifests, briefings, and their gates.

Phase W (WO-W15) ships learning content as **files in the repository**,
not rows in a database. `planning/07-learning-platform/02-CONTENT.md`
§1.2 designs a Postgres content graph; that arrives in Phase L1. What
Phase W needs is narrower and cheaper: one flagship reading path whose
every entry is auditable in a diff.

The package is four small modules with one job each:

- `schema` — the manifest contract. Every licensing and status rule the
  owner ratified lives here as a validator, not as prose, so a manifest
  that breaks the posture cannot load at all.
- `loader` — reads manifests off disk and answers the only question the
  API asks: *what may be served?* Nothing below `approved` ever leaves
  this module.
- `linkcheck` — the mechanical half of `02` §3.3: does every link-out
  still resolve?
- `review_queue` — the human half. Renders the owner's review queue
  from the manifest so the review hours can start without anyone
  hand-maintaining a checklist.

Note on the name: `src/content/` is the *code*, `content/` at the repo
root is the *data*. Imports are always `src.content.*`, so the two
never collide.
"""

from __future__ import annotations

__all__ = [
    "linkcheck",
    "loader",
    "review_queue",
    "schema",
]
