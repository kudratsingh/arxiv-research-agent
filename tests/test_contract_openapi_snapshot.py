"""Drift check 1 of 4: the committed OpenAPI snapshot is the live document.

`web/contract/openapi.json` is what generates the frontend's types
(`web/lib/api/generated/schema.d.ts`, via `npm run generate:types`), so a
change to `src/api/schemas.py` that never reaches the snapshot leaves the web
client compiling happily against a schema the server no longer serves.

This is the producer end of that check, and it runs in the existing `tests`
job: pure in-process, no network, no Redis, no Postgres. `create_app()` builds
the router and nothing else — dependencies are opened by the lifespan, which
this never starts.

The consumer end is `npm run contract:check` (04-ARCHITECTURE.md §3.5 check 2),
which regenerates the TypeScript from this same file and diffs it.

When this fails, the snapshot is stale. Regenerate it with the command the
file's own `x-provenance` header carries, then re-add that header.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.api import create_app

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "web" / "contract" / "openapi.json"

# JSON has no comment syntax, so the snapshot carries its provenance in an
# OpenAPI 3.1 extension key. A freshly generated document has no such key, so
# it has to come off before the comparison — the header says so itself.
PROVENANCE_KEY = "x-provenance"


def _snapshot() -> dict[str, Any]:
    with SNAPSHOT_PATH.open(encoding="utf-8") as handle:
        document: dict[str, Any] = json.load(handle)
    return document


def test_snapshot_matches_the_live_openapi_document() -> None:
    document = _snapshot()
    document.pop(PROVENANCE_KEY, None)

    assert document == create_app().openapi()


def test_provenance_header_is_first_and_says_how_to_regenerate() -> None:
    document = _snapshot()

    # First key, so it reads as the header comment it stands in for.
    assert next(iter(document)) == PROVENANCE_KEY

    provenance = document[PROVENANCE_KEY]
    assert len(provenance["commit"]) == 40
    assert "create_app().openapi()" in provenance["source"]
    assert "web/contract/openapi.json" in provenance["command"]
    # The instruction this test obeys, stated in the file itself.
    assert "strip" in provenance["note"].lower()
    assert PROVENANCE_KEY in provenance["note"]


def test_snapshot_covers_every_route_the_frontend_calls() -> None:
    """The paths 04-ARCHITECTURE.md §3.1 lists as the frozen HTTP surface.

    A route dropped from the document would still pass the equality check
    above — both sides would simply lose it — so the surface itself is pinned
    separately.

    `/learn/paths*` joined the set in WO-W15: the read-only learning-content
    surface (`src/api/learn.py`), gated by `enable_learn_content`. The routes
    exist in the document whatever the flag says, because the document
    describes the server's shape, not one deployment's configuration.
    """
    document = _snapshot()
    paths = document["paths"]

    assert set(paths) == {
        # WO-W07: the learner progress ledger. Present in the document
        # whatever `enable_learner_profile` says — the flag is runtime
        # behaviour (404 when off), not schema shape, so the contract
        # describes one surface rather than two.
        "/learn/progress",
        "/research",
        "/research/{job_id}",
        "/research/{job_id}/review",
        "/research/{job_id}/export",
        "/research/{job_id}/stream",
        "/conversations",
        "/conversations/{conversation_id}",
        "/learn/profile",
        "/healthz",
        "/learn/paths",
        "/learn/paths/{path_id}",
        "/learn/sessions",
        "/learn/sessions/{session_id}",
        "/learn/sessions/{session_id}/turn",
    }
    assert set(paths["/conversations"]) == {"get", "post"}
    assert set(paths["/conversations/{conversation_id}"]) == {"get", "delete"}
    # WO-W02 / ADR 0058. The profile routes are mounted unconditionally
    # — SR-07 keeps feature gating backend-only, so the document is the
    # same in both positions of `enable_learner_profile` and the
    # generated types never depend on a flag. Behaviour is what the
    # flag changes: 404 `learner_profile_disabled` while it is off.
    assert set(paths["/learn/profile"]) == {"get", "put", "delete"}
    # WO-W15, same rule, and read-only by construction: no writer ever
    # appears on the content routes.
    assert set(paths["/learn/paths"]) == {"get"}
    assert set(paths["/learn/paths/{path_id}"]) == {"get"}


def test_the_learn_schemas_carry_no_field_that_could_rehost_a_paper() -> None:
    """WO-W15 c2, asserted on the contract the frontend generates from.

    The manifest schema is checked in `tests/test_content_manifest.py`; this
    is the other end — a response model that grew a `full_text` field would
    put one in `schema.d.ts` and, from there, on a page.

    The `Learn` prefix catches WO-W02's `LearnerProfile*` models too, which
    is deliberate: the rule is about the learning surface as a whole, not
    about one card's models.
    """
    schemas = _snapshot()["components"]["schemas"]
    forbidden = {"body", "full_text", "fulltext", "pdf", "pdf_url", "transcript"}
    checked = 0
    for name, schema in schemas.items():
        if not name.startswith("Learn"):
            continue
        checked += 1
        for field, spec in schema.get("properties", {}).items():
            if field not in forbidden:
                continue
            # A closed value is not a container. `LearnLicensing.full_text`
            # is `const: "link-out-only"` — it states the posture and can
            # hold nothing else, which is the clearest way to write it.
            assert "const" in spec or "enum" in spec, f"{name}.{field}"
    assert checked >= 5, "the Learn* schemas vanished from the snapshot"


def test_stream_and_export_are_undescribed_which_is_why_the_overlay_exists() -> (
    None
):
    """The gap that makes `web/lib/api/events.ts` hand-written.

    Generation without an overlay would produce exactly the false confidence
    R-06 names: `GET /research/{job_id}/stream` is typed as a 200 whose schema
    is the empty object — `application/json` with nothing in it, for an
    endpoint that actually returns `text/event-stream` — and none of the error
    envelopes appear at all. If the backend ever describes them, this test
    fails and the overlay should shrink to match: a good failure, not a
    regression.
    """
    paths = _snapshot()["paths"]

    stream_ok = paths["/research/{job_id}/stream"]["get"]["responses"]["200"]
    assert stream_ok["content"] == {"application/json": {"schema": {}}}
    assert "text/event-stream" not in stream_ok["content"]

    # No route documents 401 / 404 / 409 / 429 / 502 / 503; only FastAPI's
    # automatic 422 is present.
    documented: set[str] = set()
    for operations in paths.values():
        for operation in operations.values():
            documented.update(operation.get("responses", {}))
    assert documented & {"401", "404", "409", "429", "502", "503"} == set()
    assert "422" in documented
