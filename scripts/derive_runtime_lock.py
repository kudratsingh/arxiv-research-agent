"""Derive the container's runtime lock from the fully tested lock.

Run this inside the development environment after regenerating
``requirements-lock.txt``. The installed distributions provide dependency
metadata; this script walks only the project's non-dev dependency graph and
copies the matching exact pins from the full lock. It never resolves or
downloads a package.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import pathlib
import sys
from collections import deque

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL_LOCK = ROOT / "requirements-lock.txt"
RUNTIME_LOCK = ROOT / "requirements-runtime-lock.txt"
PROJECT_DISTRIBUTION = "arxiv-research-agent"

HEADER = """# requirements-runtime-lock.txt — generated runtime-only subset
# of requirements-lock.txt for the production container (ADR 0054).
#
# Do not hand-edit. Regenerate inside the fully locked development venv:
#   python scripts/derive_runtime_lock.py --output requirements-runtime-lock.txt
# Then verify with:
#   python scripts/derive_runtime_lock.py --check
#
# The full lock remains the CI/test authority. This subset removes packages
# reachable only from the project's `dev` extra. Linux gates preinstall the
# official locked +cpu Torch artifact before the public-version lock so this
# metadata walk sees the same dependency graph the container ships.
"""


def _locked_lines(path: pathlib.Path) -> dict[str, str]:
    """Read exact requirement lines keyed by canonical distribution name.

    Args:
        path: Full lockfile containing one ``name==version`` pin per line.

    Returns:
        Mapping from canonical package name to its original lockfile line.

    Raises:
        ValueError: If a non-comment requirement is not an exact pin or a
            canonical package name occurs more than once.
    """
    locked: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        specs = list(requirement.specifier)
        if len(specs) != 1 or specs[0].operator != "==":
            raise ValueError(f"full lock entry is not an exact pin: {line}")
        name = canonicalize_name(requirement.name)
        if name in locked:
            raise ValueError(f"duplicate full lock entry: {name}")
        locked[name] = line
    return locked


def _requirement_applies(requirement: Requirement, extras: set[str]) -> bool:
    """Return whether a dependency marker applies for active parent extras.

    Args:
        requirement: Dependency metadata entry to evaluate.
        extras: Extras active on the parent distribution. The base dependency
            context is always evaluated as well.

    Returns:
        True when the unmarked requirement applies or at least one marker
        evaluation succeeds in the current environment.
    """
    if requirement.marker is None:
        return True
    environment = default_environment()
    for extra in extras | {""}:
        environment["extra"] = extra
        if requirement.marker.evaluate(environment):
            return True
    return False


def runtime_distribution_names() -> set[str]:
    """Walk the installed project's non-dev dependency closure.

    Returns:
        Canonical names of every installed runtime distribution.

    Raises:
        importlib.metadata.PackageNotFoundError: If the project or one of its
            runtime dependencies is not installed in the active environment.
    """
    active_extras: dict[str, set[str]] = {}
    queue: deque[str] = deque()

    def activate(requirement: Requirement) -> None:
        name = canonicalize_name(requirement.name)
        extras = {canonicalize_name(extra) for extra in requirement.extras}
        is_new = name not in active_extras
        current = active_extras.setdefault(name, set())
        if is_new or not extras.issubset(current):
            current.update(extras)
            queue.append(name)

    project = importlib.metadata.distribution(PROJECT_DISTRIBUTION)
    for raw_requirement in project.requires or []:
        requirement = Requirement(raw_requirement)
        if _requirement_applies(requirement, set()):
            activate(requirement)

    visited_extras: dict[str, frozenset[str]] = {}
    while queue:
        name = queue.popleft()
        extras = active_extras[name]
        signature = frozenset(extras)
        if visited_extras.get(name) == signature:
            continue
        visited_extras[name] = signature

        distribution = importlib.metadata.distribution(name)
        for raw_requirement in distribution.requires or []:
            requirement = Requirement(raw_requirement)
            if _requirement_applies(requirement, extras):
                activate(requirement)

    return set(active_extras)


def render_runtime_lock() -> str:
    """Render the exact runtime subset using pins from the full lock.

    Returns:
        Complete generated lockfile text, including its provenance header.

    Raises:
        RuntimeError: If runtime metadata names a package absent from the full
            lock, which means the active environment and lock have drifted.
    """
    locked = _locked_lines(FULL_LOCK)
    runtime_names = runtime_distribution_names()
    missing = sorted(runtime_names - locked.keys())
    if missing:
        raise RuntimeError(
            "runtime dependencies missing from requirements-lock.txt: "
            + ", ".join(missing)
        )
    lines = [locked[name] for name in sorted(runtime_names)]
    return HEADER + "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Generate, write, or verify the runtime lock.

    Args:
        argv: Optional command-line arguments for tests/callers.

    Returns:
        Process exit code: zero on success, one when ``--check`` detects
        drift.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)

    rendered = render_runtime_lock()
    if args.check:
        if not RUNTIME_LOCK.exists() or RUNTIME_LOCK.read_text() != rendered:
            print(
                "requirements-runtime-lock.txt is stale; regenerate it with "
                "scripts/derive_runtime_lock.py --output",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.output is not None:
        args.output.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
