"""Run the v19 verifier against the exact Git publication, not today's producer."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PUBLICATION = "a7b624b9e972a5a77dd0c3f5eb439fbbe54fb63a"
APPLICATION = "b1bad909b112c246b678c0194325ae974e4284bf"
PACKAGE_PATH = Path("planning/15-evaluation-audit-and-recovery/evidence/comparison-v19")


def archived_producer(root: Path, destination: Path) -> tuple[Path, Path]:
    """Materialize tracked bytes in a pytest-owned disposable directory."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", PUBLICATION + "^{commit}"], cwd=root, text=True
    ).strip()
    if commit != PUBLICATION:
        raise AssertionError("v19_publication_commit_mismatch")
    common = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], cwd=root, text=True
        ).strip()
    )
    if not common.is_absolute():
        common = (root / common).resolve()
    destination.mkdir()
    archive = subprocess.Popen(
        ["git", "archive", "--format=tar", PUBLICATION], cwd=root, stdout=subprocess.PIPE
    )
    assert archive.stdout is not None
    unpack = subprocess.run(
        ["tar", "-x", "-C", str(destination)], stdin=archive.stdout, check=False
    )
    archive.stdout.close()
    if archive.wait() != 0 or unpack.returncode != 0:
        raise RuntimeError("v19_publication_archive_failed")
    return destination, common


def verify_archived(
    root: Path, common: Path, package: Path, application: str
) -> subprocess.CompletedProcess[str]:
    """Run the unchanged verifier from stdin with its original CLI arguments."""
    script = package / "tools/verify-artifacts.py"
    environment = dict(os.environ)
    environment.update(
        ANTHROPIC_API_KEY="local-preview-disabled",
        WORKSPACE_D5_OFFLINE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(script.parent) + os.pathsep + environment.get("PYTHONPATH", ""),
        GIT_DIR=str(common),
        GIT_WORK_TREE=str(root),
    )
    return subprocess.run(
        [
            sys.executable,
            "-",
            "--packet-dir",
            str(package),
            "--application-commit",
            application,
            "--require-replay",
        ],
        input=script.read_text(),
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
