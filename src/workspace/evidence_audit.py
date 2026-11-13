"""Append-only verification of existing evidence copies; never deletes originals."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REVISION = "evidence-custody-verification-v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
    if not isinstance(value, dict) or not isinstance(value.get("files"), list):
        raise ValueError("evidence_manifest_files_required")
    return value


def verify(manifests: list[Path], out: Path, *, durable_root: Path) -> dict[str, Any]:
    """Rehash both sides, reusing verified copies and copying only absent bytes.

    Missing originals and evolved originals remain distinct from corrupt/missing
    copies. Captured versions are never replaced with newer source bytes.
    """
    if out.exists():
        raise ValueError("evidence_audit_choose_new_output_revision")
    root = durable_root.resolve()
    if not out.resolve().is_relative_to(root):
        raise ValueError("evidence_audit_output_must_be_in_durable_root")
    out.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    known: dict[str, str] = {}
    bindings = {}
    for manifest in manifests:
        value = read(manifest)
        bindings[str(manifest)] = sha256(manifest)
        for entry in value["files"]:
            original = Path(entry["original"])
            target = Path(
                entry.get("canonical_durable_copy")
                or entry.get("permanent_copy")
                or entry.get("durable_copy", "")
            )
            expected = entry["sha256"]
            if (
                not target.is_absolute()
                or not target.resolve().is_relative_to(root)
                or not isinstance(expected, str)
                or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)
            ):
                raise ValueError("evidence_manifest_invalid_copy_or_hash")
            current_hash = sha256(original) if original.is_file() else None
            copy_hash = sha256(target) if target.is_file() else None
            if copy_hash:
                known.setdefault(copy_hash, str(target))
            rows.append(
                {
                    "manifest": str(manifest),
                    "original": str(original),
                    "captured_sha256": expected,
                    "original_current_sha256": current_hash,
                    "original_state": "missing"
                    if current_hash is None
                    else "unchanged"
                    if current_hash == expected
                    else "different_from_capture",
                    "recorded_copy": str(target),
                    "recorded_copy_sha256": copy_hash,
                    "recorded_copy_state": "missing"
                    if copy_hash is None
                    else "verified"
                    if copy_hash == expected
                    else "mismatch",
                }
            )

    copies = []
    attempted: set[str] = set()

    def retain(source: Path, expected: str) -> str | None:
        if expected in known:
            return known[expected]
        if expected in attempted:
            return None
        attempted.add(expected)
        destination = out / "missing-evidence" / expected / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        # This is a new content revision, never an overwrite of an old copy.
        shutil.copy2(source, destination)
        actual = sha256(destination)
        copies.append({"source": str(source), "copy": str(destination), "sha256": actual})
        if actual == expected:
            known[expected] = str(destination)
            return str(destination)
        return None  # Preserve an unstable copy too; never relabel it verified.

    for row in rows:
        expected = row["captured_sha256"]
        if expected not in known and row["original_current_sha256"] == expected:
            retain(Path(row["original"]), expected)
        row["verified_captured_copy"] = known.get(expected)
        current = row["original_current_sha256"]
        if current is not None and current not in known:
            retain(Path(row["original"]), current)
        row["verified_current_copy"] = known.get(current) if current else None
    # A later duplicate source can recover an earlier missing original.
    for row in rows:
        row["verified_captured_copy"] = known.get(row["captured_sha256"])
        current = row["original_current_sha256"]
        row["verified_current_copy"] = known.get(current) if current else None

    unavailable = sum(row["verified_captured_copy"] is None for row in rows)
    missing_current = sum(
        row["original_current_sha256"] is not None and row["verified_current_copy"] is None
        for row in rows
    )
    summary = {
        "revision": REVISION,
        "verified_at": datetime.now(UTC).isoformat(),
        "manifest_bindings": bindings,
        "independent_rehash_ran": True,
        "entries_rehashed": len(rows),
        "captured_versions_available": len(rows) - unavailable,
        "captured_versions_unavailable": unavailable,
        "current_source_versions_unavailable": missing_current,
        "original_states": dict(Counter(row["original_state"] for row in rows)),
        "recorded_copy_states": dict(Counter(row["recorded_copy_state"] for row in rows)),
        "new_copies": copies,
        "new_copy_count": len(copies),
        "required_known_evidence_preserved": not unavailable and not missing_current,
        "originals_deleted": False,
        "predecessors_overwritten": False,
        "historical_284_path_list": "not supplied; manifest counters are not that original list",
        "entries": rows,
    }
    raw = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode()
    (out / "INVENTORY.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    (out / "SUMMARY.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "entries"}, indent=2) + "\n"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--durable-root", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.manifest, args.out, durable_root=args.durable_root)
    print(json.dumps({k: v for k, v in result.items() if k not in {"entries", "new_copies"}}))
    if not result["required_known_evidence_preserved"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
