"""Learning-platform domain modules (Phase W).

The first package in the repo that holds data *about a person* rather
than about a paper. Everything here is gated behind
`settings.enable_learner_profile`, which itself refuses to run without
`settings.enable_api_auth` — the profile is keyed by the authenticated
principal and has no meaning for an anonymous caller.

Modules are imported lazily by their callers (the route layer, the
session graph) so nothing here loads on an ordinary `import src.api`.
See ADR 0058.
"""

from __future__ import annotations
