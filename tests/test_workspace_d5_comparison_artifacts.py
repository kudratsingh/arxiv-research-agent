"""Public prospective artifacts retain exact frozen identities and no approval."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.d5_archived_producer import (
    APPLICATION,
    PACKAGE_PATH,
    PUBLICATION,
    archived_producer,
    verify_archived,
)

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / PACKAGE_PATH


@pytest.fixture(scope="module")
def archival_source(tmp_path_factory):
    root, common = archived_producer(ROOT, tmp_path_factory.mktemp("v19") / "publication")
    archive_package = root / PACKAGE_PATH
    current = {p.relative_to(PACKAGE) for p in PACKAGE.rglob("*") if p.is_file()}
    archived = {p.relative_to(archive_package) for p in archive_package.rglob("*") if p.is_file()}
    assert current == archived
    for relative in current:
        assert (PACKAGE / relative).read_bytes() == (archive_package / relative).read_bytes(), (
            relative
        )
    return root, common, archive_package


def test_frozen_comparison_package_matches_production_and_same_packet_proof(archival_source):
    root, common, package = archival_source
    identity = json.loads((PACKAGE / "IDENTITY.json").read_text())
    assert identity["application_commit"] == APPLICATION
    assert PUBLICATION == "a7b624b9e972a5a77dd0c3f5eb439fbbe54fb63a"
    for manifest_path in sorted(PACKAGE.glob("MANIFEST*.json")):
        manifest = json.loads(manifest_path.read_text())
        assert isinstance(manifest["files"], dict)
        for relative, expected_sha in manifest["files"].items():
            target = (PACKAGE / relative).resolve()
            assert target.is_relative_to(PACKAGE.resolve())
            assert hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha, relative
    result = verify_archived(root, common, package, identity["application_commit"])
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["passed"] is True
    assert observed["same_packet_replay_required_and_verified"] is True
    assert observed["packet_digest"] == identity["packet_digest"]
    assert observed["real_provider_contacts"] == 0 and observed["approved"] is False


def test_altered_copy_is_rejected_by_archived_verifier(archival_source, tmp_path):
    root, common, package = archival_source
    altered = tmp_path / "altered-package"
    shutil.copytree(package, altered)
    target = altered / "ANSWERABILITY.json"
    target.write_bytes(target.read_bytes() + b" ")
    result = verify_archived(root, common, altered, APPLICATION)
    assert result.returncode != 0
    assert "ANSWERABILITY.json" in result.stderr


def test_archived_source_is_exact_publication_and_application_is_pinned(archival_source):
    root, common, package = archival_source
    import subprocess

    for relative in (
        "src/__init__.py",
        "src/workspace/d5_freeze.py",
        "src/workspace/d5_adapter.py",
    ):
        expected = subprocess.check_output(["git", "show", f"{PUBLICATION}:{relative}"], cwd=ROOT)
        assert (root / relative).read_bytes() == expected
    wrong = verify_archived(root, common, package, PUBLICATION)
    assert wrong.returncode != 0
    assert "AssertionError" in wrong.stderr
