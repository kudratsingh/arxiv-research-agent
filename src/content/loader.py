"""Read path manifests off disk and decide what may be served.

Phase W has no content database (`02` §1.2's Postgres graph is Phase L1),
so "the store" is a directory of JSON and markdown that ships inside the
image. That makes this module the only place where the question *may this
reach a client?* is answered, and it answers it once:
`PathManifest.servable_entries` — `approved` and above, never `proposed`,
never `stale`.

Loading is strict on purpose. A manifest that breaks a posture rule does
not load in a degraded shape; it raises, the endpoint reports the failure
honestly, and nothing half-validated is served. The alternative — skip the
bad entry and serve the rest — is how a licensing rule quietly stops being
enforced.

Caching: manifests are immutable inside a running container, so the parsed
result is cached per root. `clear_cache()` exists for tests, which build
manifests in `tmp_path`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from src.config import settings
from src.content.schema import (
    RULE_BRIEFING_REQUIRED,
    RULE_FIXTURE_BANNER,
    RULE_REVIEW_REQUIRED,
    Briefing,
    ContentValidationError,
    Entry,
    PathManifest,
    check_briefing_urls,
    check_display_label,
    check_quotes,
    parse_briefing,
    parse_manifest,
)

#: The manifest file inside each path directory.
MANIFEST_FILENAME: Final = "path.json"

#: The directory under the content root that holds path directories.
PATHS_DIRNAME: Final = "paths"

#: The string that makes fixture content unmistakable. It appears in the
#: fixture path's `banner` (which the API returns and every surface
#: renders) and in each fixture briefing's own label line, so neither the
#: API response nor the raw file can be mistaken for reviewed content.
FIXTURE_MARKER: Final = "FIXTURE CONTENT"


@dataclass(frozen=True)
class LoadedPath:
    """A validated manifest plus every briefing companion it names."""

    directory: Path
    manifest: PathManifest
    briefings: dict[str, Briefing]

    @property
    def path_id(self) -> str:
        return self.manifest.path_id

    def servable_briefing(self, entry: Entry) -> Briefing | None:
        """The briefing for `entry`, or `None` when it has none yet."""
        return self.briefings.get(entry.resource_id)


def default_content_root() -> Path:
    """The repo-shipped `content/` directory.

    Resolved from this file first, because that is the same path under
    `pytest`, `uvicorn` and the container — the Dockerfile copies
    `content/` beside `src/`, so `<parent of src>/content` holds in the
    repo and in the image alike.

    The working-directory fallback exists for the one case where the
    first answer is wrong: the package is also `pip install`ed into the
    venv, so an interpreter that resolved `src.content` from
    site-packages instead of the source tree would look for `content/`
    beside site-packages and find nothing. Returning the source-relative
    path anyway when neither exists keeps the eventual error message
    pointing somewhere a human can act on.
    """
    beside_src = Path(__file__).resolve().parents[2] / "content"
    if beside_src.is_dir():
        return beside_src
    from_cwd = Path.cwd() / "content"
    if from_cwd.is_dir():
        return from_cwd
    return beside_src


def content_root() -> Path:
    """The configured content root, falling back to the repo-shipped one."""
    configured = settings.learn_content_root.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return default_content_root()


def _check_briefing_against_entry(
    briefing: Briefing, entry: Entry, manifest: PathManifest, filename: str
) -> None:
    """Cross-check a briefing's provenance header against its manifest row.

    Two files can disagree, and the disagreement is exactly the failure
    mode WO-W15 c1 is about: a manifest that says `approved` beside a
    briefing header with an empty `reviewed-by`, or a briefing that
    claims a reviewer the manifest never recorded. Both directions are
    refused.
    """
    if briefing.header.resource_id != entry.resource_id:
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED,
            f"{filename} carries resource_id "
            f"{briefing.header.resource_id!r} but is referenced by entry "
            f"{entry.resource_id!r}",
        )
    if briefing.header.path_id != manifest.path_id:
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED,
            f"{filename} claims path_id {briefing.header.path_id!r}; it "
            f"lives in {manifest.path_id!r}",
        )
    if bool(briefing.header.reviewed_by) != bool(entry.reviewed_by):
        raise ContentValidationError(
            RULE_REVIEW_REQUIRED,
            f"{filename} and the manifest disagree about whether "
            f"{entry.resource_id!r} was reviewed: header reviewed_by="
            f"{briefing.header.reviewed_by!r}, manifest reviewed_by="
            f"{entry.reviewed_by!r}. The review state lives in both files "
            "and they have to agree.",
        )
    if entry.reviewed_by and briefing.header.reviewed_by != entry.reviewed_by:
        raise ContentValidationError(
            RULE_REVIEW_REQUIRED,
            f"{filename} names reviewer {briefing.header.reviewed_by!r}; "
            f"the manifest names {entry.reviewed_by!r}",
        )
    if entry.briefing_provenance != briefing.header.provenance:
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED,
            f"{filename} claims provenance "
            f"{briefing.header.provenance!r}; the manifest entry says its "
            f"briefing is {entry.briefing_provenance!r}",
        )
    if manifest.fixture and FIXTURE_MARKER not in briefing.body:
        raise ContentValidationError(
            RULE_FIXTURE_BANNER,
            f"{filename} belongs to a fixture path, so its body must say "
            f"so — the marker {FIXTURE_MARKER!r} was not found. The banner "
            "on the manifest labels the path; this labels the file.",
        )


def load_path_dir(directory: Path) -> LoadedPath:
    """Load and fully validate one path directory.

    Args:
        directory: A directory containing `path.json` and, optionally, a
            `briefings/` subtree.

    Returns:
        The validated path.

    Raises:
        ContentValidationError: The manifest or any briefing it names
            breaks a rule. The message carries the rule id.
    """
    manifest_file = directory / MANIFEST_FILENAME
    if not manifest_file.is_file():
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED,
            f"no {MANIFEST_FILENAME} in {directory}",
        )
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED, f"{manifest_file} is not valid JSON: {exc}"
        ) from exc

    manifest = parse_manifest(payload)
    if manifest.path_id != directory.name:
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED,
            f"manifest path_id {manifest.path_id!r} must match its "
            f"directory name {directory.name!r} — the directory is the id "
            "every briefing path is resolved against.",
        )

    briefings: dict[str, Briefing] = {}
    for entry in manifest.entries:
        if entry.briefing_file is None:
            continue
        briefing_path = directory / entry.briefing_file
        if not briefing_path.is_file():
            if entry.servable:
                raise ContentValidationError(
                    RULE_BRIEFING_REQUIRED,
                    f"entry {entry.resource_id!r} is {entry.status!r} but "
                    f"its briefing {entry.briefing_file!r} does not exist. "
                    "Nothing publishes without the companion that was "
                    "reviewed.",
                )
            # Not yet drafted. The manifest names where it will land so
            # the generation campaign has a target; absence is the
            # normal pre-campaign state.
            continue
        briefing = parse_briefing(briefing_path.read_text(encoding="utf-8"))
        _check_briefing_against_entry(
            briefing, entry, manifest, entry.briefing_file
        )
        check_display_label(briefing)
        check_quotes(briefing)
        check_briefing_urls(briefing)
        briefings[entry.resource_id] = briefing

    return LoadedPath(directory=directory, manifest=manifest, briefings=briefings)


def load_content_root(root: Path) -> dict[str, LoadedPath]:
    """Load every path under `root/paths/`, keyed by `path_id`.

    Args:
        root: The content root (the directory holding `paths/`).

    Returns:
        Every validated path, in `path_id` order. An absent or empty
        root yields an empty mapping — a deployment that ships no
        content is a valid deployment, not an error.

    Raises:
        ContentValidationError: Any path directory fails validation.
    """
    paths_dir = root / PATHS_DIRNAME
    if not paths_dir.is_dir():
        return {}
    loaded: dict[str, LoadedPath] = {}
    for directory in sorted(p for p in paths_dir.iterdir() if p.is_dir()):
        if not (directory / MANIFEST_FILENAME).is_file():
            continue
        path = load_path_dir(directory)
        loaded[path.path_id] = path
    return loaded


@lru_cache(maxsize=8)
def _cached(root_str: str) -> dict[str, LoadedPath]:
    return load_content_root(Path(root_str))


def loaded_paths(root: Path | None = None) -> dict[str, LoadedPath]:
    """Every validated path under `root`, cached per root.

    Args:
        root: Content root. Defaults to `content_root()`.

    Returns:
        Mapping of `path_id` to `LoadedPath`. Treat it as read-only; it
        is shared with every other caller.
    """
    return _cached(str(root if root is not None else content_root()))


def clear_cache() -> None:
    """Drop the parsed-manifest cache. For tests that write manifests."""
    _cached.cache_clear()


def published_paths(root: Path | None = None) -> list[LoadedPath]:
    """The paths a client may see: `published` only, in `path_id` order.

    A path below `published` is invisible rather than listed-and-locked.
    Phase W's flagship path sits at `proposed` until its briefings are
    generated and reviewed, and an empty list is the honest answer to
    "what can I read?" while that is true.
    """
    return [p for p in loaded_paths(root).values() if p.manifest.status == "published"]


def published_path(path_id: str, root: Path | None = None) -> LoadedPath | None:
    """One published path by id, or `None` if it is absent or unpublished."""
    path = loaded_paths(root).get(path_id)
    if path is None or path.manifest.status != "published":
        return None
    return path
