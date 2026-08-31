"""Learning-platform domain modules (Phase W).

The first package in the repo that holds data *about a person* rather
than about a paper: the learner profile (`profile_store`, WO-W02) and
the append-only progress ledger (`progress_store`, WO-W07). Everything
here is gated behind `settings.enable_learner_profile`, which itself
refuses to run without `settings.enable_api_auth` — both stores are
keyed by the authenticated principal and have no meaning for an
anonymous caller.

Modules are imported lazily by their callers (the route layer, the
session graph) so nothing here loads on an ordinary `import src.api`.
Nothing in this package imports the research graph, and nothing in
`src/graph/` imports this package: the learning surfaces are additive
to the existing product and must be removable without touching the
pipeline. See ADR 0058.
"""

from __future__ import annotations
