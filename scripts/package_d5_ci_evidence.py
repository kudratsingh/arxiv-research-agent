#!/usr/bin/env python3
"""Losslessly package raw CI journals without exposing their names to artifact upload.

GitHub artifact paths reject quotes, CR/LF and other valid POSIX filename
characters. Safe opaque tar members plus an exact-name manifest preserve those
files, including failed and incomplete bytes. This never extracts or rewrites
the original evidence, and refuses to replace an earlier package.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
from pathlib import Path

REVISION = "d5-ci-evidence-archive-v1"
MANIFEST_MEMBER = "manifest.json"


def _digest(stream: object) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _files(source: Path) -> list[Path]:
    if source.is_symlink():
        raise ValueError("evidence source must not be a symlink")
    if not source.exists():
        return []
    if not source.is_dir():
        raise ValueError("evidence source must be a directory")
    paths = []
    for path in sorted(source.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("non-regular evidence entry")
        if stat.S_ISREG(mode):
            paths.append(path)
    return paths


def verify(archive: Path, external_manifest: Path | None = None) -> dict:
    """Verify every opaque member against the internal and optional external manifest."""
    with tarfile.open(archive, "r:gz") as reader:
        members = reader.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(not member.isfile() for member in members):
            raise ValueError("duplicate or non-regular archive member")
        internal = reader.extractfile(MANIFEST_MEMBER)
        if internal is None:
            raise ValueError("missing manifest")
        raw = internal.read()
        manifest = json.loads(raw)
        if manifest["revision"] != REVISION:
            raise ValueError("unknown evidence archive revision")
        if external_manifest is not None and external_manifest.read_bytes() != raw:
            raise ValueError("external manifest mismatch")
        records = manifest["files"]
        expected = {MANIFEST_MEMBER}
        originals = set()
        for index, record in enumerate(records):
            name = record["member"]
            if name != f"objects/{index:08d}-{record['sha256']}.blob":
                raise ValueError("invalid opaque member")
            if record["original_path"] in originals:
                raise ValueError("duplicate original path")
            originals.add(record["original_path"])
            expected.add(name)
            member = reader.getmember(name)
            stream = reader.extractfile(member)
            if stream is None or member.size != record["bytes"] or _digest(stream) != record["sha256"]:
                raise ValueError("evidence size or checksum mismatch")
        if set(names) != expected:
            raise ValueError("missing or unlisted archive member")
        if manifest["file_count"] != len(records):
            raise ValueError("evidence count mismatch")
        if manifest["total_bytes"] != sum(record["bytes"] for record in records):
            raise ValueError("evidence byte count mismatch")
        return manifest


def package(source: Path, archive: Path, manifest_path: Path) -> dict:
    """Create an append-only package; a partial failure is retained for inspection."""
    source = source.absolute()
    paths = _files(source)
    if archive.resolve() == manifest_path.resolve():
        raise ValueError("archive and manifest must be distinct")
    for target in (archive, manifest_path):
        if target.resolve().is_relative_to(source.resolve()):
            raise ValueError("package output must be outside evidence source")
        if target.exists() or target.is_symlink():
            raise FileExistsError("refusing to overwrite evidence package")
        target.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for index, path in enumerate(paths):
        before = path.stat()
        with path.open("rb") as stream:
            checksum = _digest(stream)
        records.append({
            "original_path": path.relative_to(source).as_posix(),
            "member": f"objects/{index:08d}-{checksum}.blob",
            "sha256": checksum, "bytes": before.st_size,
            "mode": stat.S_IMODE(before.st_mode), "mtime_ns": before.st_mtime_ns,
        })
    manifest = {
        "revision": REVISION, "source_exists": source.exists(),
        "file_count": len(records), "total_bytes": sum(record["bytes"] for record in records),
        "files": records,
    }
    raw = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()
    with (
        archive.open("xb") as output,
        gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as writer,
    ):
        for path, record in zip(paths, records, strict=True):
            with path.open("rb") as stream:
                current = os.fstat(stream.fileno())
                if (current.st_size, current.st_mtime_ns) != (record["bytes"], record["mtime_ns"]):
                    raise ValueError("evidence changed while packaging")
                info = tarfile.TarInfo(record["member"])
                info.size = record["bytes"]
                info.mode = record["mode"]
                writer.addfile(info, stream)
        info = tarfile.TarInfo(MANIFEST_MEMBER)
        info.size = len(raw)
        writer.addfile(info, io.BytesIO(raw))
    verify(archive)
    if _files(source) != paths:
        raise ValueError("evidence file set changed while packaging")
    with manifest_path.open("xb") as output:
        output.write(raw)
    verify(archive, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("build/d5-v15-test-evidence"))
    parser.add_argument("--archive", type=Path, default=Path("build/d5-regression-journals.tar.gz"))
    parser.add_argument("--manifest", type=Path, default=Path("build/d5-regression-journals-manifest.json"))
    args = parser.parse_args()
    receipt = package(args.source, args.archive, args.manifest)
    print(json.dumps({key: value for key, value in receipt.items() if key != "files"}, sort_keys=True))


if __name__ == "__main__":
    main()
