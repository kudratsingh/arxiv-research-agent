"""CI evidence must survive artifact filename restrictions without changing originals."""
from __future__ import annotations

import hashlib
import io
import json
import runpy
import tarfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_archive = runpy.run_path(str(Path(__file__).parents[1] / "scripts/package_d5_ci_evidence.py"))
package = _archive["package"]
verify = _archive["verify"]


def test_raw_names_and_bytes_survive_safe_archive(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    names = [
        'response[ {"preserved":"caf\\u00e9","order":[2,1]}\r\n].json.gz',
        'nested/quotes":<>|*?\r\n.json',
        "unicode-café-λ.json", ".hidden-raw", "long-" + "x" * 190,
    ]
    originals = {}
    for index, name in enumerate(names):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes([index, 0, 255]) + 'truncated {"é":'.encode())
        originals[name] = (path.read_bytes(), path.stat().st_mtime_ns)
    archive, manifest = tmp_path / "journals.tar.gz", tmp_path / "manifest.json"
    result = package(source, archive, manifest)
    assert result["file_count"] == len(names)
    assert result == verify(archive, manifest)
    assert {row["original_path"] for row in result["files"]} == set(names)
    with tarfile.open(archive) as reader:
        for row in result["files"]:
            payload, timestamp = originals[row["original_path"]]
            assert reader.extractfile(row["member"]).read() == payload
            assert row["sha256"] == hashlib.sha256(payload).hexdigest()
            assert row["mtime_ns"] == timestamp
            assert not any(character in row["member"] for character in '\":<>|*?\r\n')
    for name, (payload, timestamp) in originals.items():
        assert (source / name).read_bytes() == payload
        assert (source / name).stat().st_mtime_ns == timestamp
    with pytest.raises(FileExistsError):
        package(source, archive, manifest)


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_empty_source_is_explicit(tmp_path: Path, exists: bool) -> None:
    source = tmp_path / "source"
    if exists:
        source.mkdir()
    result = package(source, tmp_path / "raw.tar.gz", tmp_path / "manifest.json")
    assert result["source_exists"] is exists
    assert result["file_count"] == result["total_bytes"] == 0


def test_no_following_symlinks_or_writing_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    (source / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="non-regular"):
        package(source, tmp_path / "raw.tar.gz", tmp_path / "manifest.json")
    linked = tmp_path / "linked"
    linked.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        package(linked, tmp_path / "other.tar.gz", tmp_path / "other.json")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="outside"):
        package(empty, empty / "raw.tar.gz", tmp_path / "manifest.json")
    with pytest.raises(ValueError, match="distinct"):
        package(empty, tmp_path / "same", tmp_path / "same")


def test_external_manifest_and_archive_corruption_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "raw").write_bytes(b"original")
    archive, manifest = tmp_path / "raw.tar.gz", tmp_path / "manifest.json"
    package(source, archive, manifest)
    mismatched = tmp_path / "mismatched.json"
    mismatched.write_bytes(b"{}")
    with pytest.raises(ValueError, match="manifest mismatch"):
        verify(archive, mismatched)
    damaged = tmp_path / "damaged.tar.gz"
    with tarfile.open(archive) as original, tarfile.open(damaged, "w:gz") as output:
        for member in original.getmembers():
            data = original.extractfile(member).read()
            if member.name != "manifest.json":
                data = b"modified"
                member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="checksum"):
        verify(damaged)


@pytest.mark.parametrize("kind", ["duplicate", "unlisted", "bad_count"])
def test_archive_members_and_counts_verified(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "raw").write_bytes(b"original")
    archive, manifest = tmp_path / "raw.tar.gz", tmp_path / "manifest.json"
    package(source, archive, manifest)
    damaged = tmp_path / f"{kind}.tar.gz"
    with tarfile.open(archive) as original, tarfile.open(damaged, "w:gz") as output:
        for member in original.getmembers():
            data = original.extractfile(member).read()
            if kind == "bad_count" and member.name == "manifest.json":
                parsed = json.loads(data)
                parsed["file_count"] += 1
                data = json.dumps(parsed).encode()
                member.size = len(data)
            output.addfile(member, io.BytesIO(data))
            if kind == "duplicate" and member.name != "manifest.json":
                output.addfile(member, io.BytesIO(data))
        if kind == "unlisted":
            extra = tarfile.TarInfo("objects/unknown.blob")
            extra.size = 1
            output.addfile(extra, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="duplicate|unlisted|count"):
        verify(damaged)


def test_workflow_uploads_only_portable_archive_names() -> None:
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["tests"]["steps"]
    names = [step.get("name") for step in steps]
    packaging = names.index("Package raw D5 regression journals losslessly")
    upload = names.index("Upload Python coverage")
    assert packaging < upload
    assert steps[packaging]["if"] == steps[upload]["if"] == "always()"
    assert steps[packaging]["run"] == "python scripts/package_d5_ci_evidence.py"
    paths = steps[upload]["with"]["path"].splitlines()
    assert "build/d5-v15-test-evidence/" not in paths
    assert "build/d5-regression-journals.tar.gz" in paths
    assert "build/d5-regression-journals-manifest.json" in paths
    assert "build/.coverage" in paths
