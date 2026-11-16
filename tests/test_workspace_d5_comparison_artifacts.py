"""Public prospective artifacts retain exact frozen identities and no approval."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "planning/15-evaluation-audit-and-recovery/evidence/comparison-v19"


def test_frozen_comparison_package_matches_production_and_same_packet_proof():
    identity = json.loads((PACKAGE / "IDENTITY.json").read_text())
    for manifest_path in sorted(PACKAGE.glob("MANIFEST*.json")):
        manifest = json.loads(manifest_path.read_text())
        assert isinstance(manifest["files"], dict)
        for relative, expected_sha in manifest["files"].items():
            target = (PACKAGE / relative).resolve()
            assert target.is_relative_to(PACKAGE.resolve())
            assert hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha, relative
    script = PACKAGE / "tools/verify-artifacts.py"
    environment = dict(os.environ)
    environment.update(
        ANTHROPIC_API_KEY="local-preview-disabled",
        WORKSPACE_D5_OFFLINE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(script.parent) + os.pathsep + environment.get("PYTHONPATH", ""),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-",
            "--packet-dir",
            str(PACKAGE),
            "--application-commit",
            identity["application_commit"],
            "--require-replay",
        ],
        input=script.read_text(),
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["passed"] is True
    assert observed["same_packet_replay_required_and_verified"] is True
    assert observed["packet_digest"] == identity["packet_digest"]
    assert observed["real_provider_contacts"] == 0 and observed["approved"] is False
