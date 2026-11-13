"""Synthetic custody controls: missing, evolved and corrupt bytes stay distinct."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from src.workspace.evidence_audit import main, read, sha256, verify

pytestmark = pytest.mark.unit


def manifest(tmp_path, rows):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"files": rows}))
    return p


def entry(source, copy, content=b"original"):
    return {
        "original": str(source),
        "permanent_copy": str(copy),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_existing_copies_are_rehashed_without_duplicate_copying(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    copy = tmp_path / "copy"
    copy.write_bytes(b"original")
    result = verify(
        [manifest(tmp_path, [entry(source, copy)])], tmp_path / "audit", durable_root=tmp_path
    )
    assert result["independent_rehash_ran"] and result["required_known_evidence_preserved"]
    assert result["new_copy_count"] == 0 and sha256(source) == sha256(copy)
    assert (
        json.loads(gzip.decompress((tmp_path / "audit/INVENTORY.json.gz").read_bytes()))["entries"]
        == result["entries"]
    )
    with pytest.raises(ValueError, match="new_output_revision"):
        verify([], tmp_path / "audit", durable_root=tmp_path)


def test_missing_copy_is_recovered_without_changing_original(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    result = verify(
        [manifest(tmp_path, [entry(source, tmp_path / "absent")])],
        tmp_path / "audit",
        durable_root=tmp_path,
    )
    assert result["new_copy_count"] == 1 and result["required_known_evidence_preserved"]
    assert source.read_bytes() == b"original"


def test_missing_original_uses_verified_copy_and_marks_limit(tmp_path):
    copy = tmp_path / "copy"
    copy.write_bytes(b"original")
    result = verify(
        [manifest(tmp_path, [entry(tmp_path / "missing", copy)])],
        tmp_path / "audit",
        durable_root=tmp_path,
    )
    assert result["original_states"] == {"missing": 1}
    assert result["new_copy_count"] == 0 and result["required_known_evidence_preserved"]


def test_evolved_original_retains_both_versions_and_corruption_is_not_overwritten(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"new")
    old = tmp_path / "old"
    old.write_bytes(b"original")
    corrupt = tmp_path / "corrupt"
    corrupt.write_bytes(b"bad")
    rows = [entry(source, corrupt), entry(tmp_path / "missing", old)]
    result = verify([manifest(tmp_path, rows)], tmp_path / "audit", durable_root=tmp_path)
    assert result["new_copy_count"] == 1 and result["required_known_evidence_preserved"]
    assert old.read_bytes() == b"original" and corrupt.read_bytes() == b"bad"
    assert result["entries"][0]["verified_captured_copy"] == str(old)
    assert Path(result["entries"][0]["verified_current_copy"]).read_bytes() == b"new"


def test_unrecoverable_capture_remains_explicit_not_replaced_with_new_bytes(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"new")
    result = verify(
        [manifest(tmp_path, [entry(source, tmp_path / "absent")])],
        tmp_path / "audit",
        durable_root=tmp_path,
    )
    assert result["captured_versions_unavailable"] == 1
    assert result["new_copy_count"] == 1 and not result["required_known_evidence_preserved"]
    assert result["entries"][0]["verified_captured_copy"] is None


def test_rejects_unsafe_manifest_and_report_shapes(tmp_path):
    with pytest.raises(ValueError, match="durable_root"):
        verify([], tmp_path.parent / "elsewhere", durable_root=tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    with pytest.raises(ValueError, match="manifest_files"):
        read(bad)
    source = tmp_path / "source"
    source.write_bytes(b"original")
    rows = [entry(source, Path("relative"))]
    with pytest.raises(ValueError, match="invalid_copy"):
        verify([manifest(tmp_path, rows)], tmp_path / "audit", durable_root=tmp_path)


def test_cli_exports_only_a_new_version(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    p = manifest(tmp_path, [entry(source, tmp_path / "missing")])
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "--manifest",
            str(p),
            "--out",
            str(tmp_path / "audit"),
            "--durable-root",
            str(tmp_path),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["new_copy_count"] == 1


def test_unstable_copy_is_retained_unverified_without_retry_or_overwrite(tmp_path, monkeypatch):
    import src.workspace.evidence_audit as audit

    source = tmp_path / "source"
    source.write_bytes(b"original")
    calls = []

    def unstable(src, target):
        calls.append(str(target))
        target.write_bytes(b"changed during copy")

    monkeypatch.setattr(audit.shutil, "copy2", unstable)
    result = verify(
        [manifest(tmp_path, [entry(source, tmp_path / "missing")])],
        tmp_path / "audit",
        durable_root=tmp_path,
    )
    assert len(calls) == result["new_copy_count"] == 1
    assert not result["required_known_evidence_preserved"]
    assert Path(calls[0]).read_bytes() == b"changed during copy"


def test_cli_returns_failure_for_unavailable_required_bytes(tmp_path, monkeypatch, capsys):
    p = manifest(tmp_path, [entry(tmp_path / "absent", tmp_path / "missing")])
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "--manifest",
            str(p),
            "--out",
            str(tmp_path / "audit"),
            "--durable-root",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert not json.loads(capsys.readouterr().out)["required_known_evidence_preserved"]
