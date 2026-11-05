"""Offline manifest-selected PDF preparation and retained-text integrity audit.

No acquisition, database, provider, dotenv, directory discovery or OCR. Provenance
is an operator declaration, not a rights verification. Extraction/span identity
comes from material.extract_pdf; locating text never qualifies scientific claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.workspace import material as retained

MANIFEST_REVISION = "workspace-source-samples-v1"
BUNDLE_REVISION = "workspace-source-sample-bundle-v1"
MAX_SAMPLES = 8
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_BATCH_PAGES = 48
MAX_BATCH_CHARS = 480_000
MAX_MANIFEST_BYTES = 256 * 1024
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
REGION_KINDS = {"prose", "equation", "table", "figure", "appendix", "algorithm"}
EXCLUSIONS = (
    "equation_semantics",
    "table_cell_structure",
    "diagram_content",
    "appendix_structure",
    "algorithm_semantics",
    "reading_order",
    "unretained_pages",
    "ocr",
)


class SampleError(ValueError):
    """An explicit refusal; never a successful empty scientific sample."""


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value)).hexdigest()


def _text(value: Any, limit: int = 2000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _integer(value: Any, maximum: int) -> bool:
    return type(value) is int and 1 <= value <= maximum


def _url(value: Any) -> bool:
    if not _text(value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def validate_manifest(value: Any) -> dict[str, Any]:
    """Validate the entire declared batch before opening any selected PDF."""
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "samples"}
        or value["schema_version"] != MANIFEST_REVISION
        or not isinstance(value["samples"], list)
        or not 1 <= len(value["samples"]) <= MAX_SAMPLES
    ):
        raise SampleError("invalid_manifest")
    ids, versions = set(), set()
    for sample in value["samples"]:
        required = {
            "sample_id",
            "path",
            "work_id",
            "version_id",
            "source_hash",
            "bytes",
            "pages",
            "max_chars",
            "provenance",
            "regions",
        }
        if not isinstance(sample, dict) or set(sample) != required:
            raise SampleError("invalid_sample_fields")
        sample_id = sample["sample_id"]
        if not isinstance(sample_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,63}", sample_id
        ):
            raise SampleError("invalid_sample_id")
        if not _text(sample["work_id"], 300) or not _text(sample["version_id"], 300):
            raise SampleError("source_version_required")
        if sample_id in ids or sample["version_id"] in versions:
            raise SampleError("duplicate_sample_or_version")
        ids.add(sample_id)
        versions.add(sample["version_id"])
        path = sample["path"]
        if not _text(path, 4096) or "\x00" in path or "://" in path or path.startswith("~"):
            raise SampleError("explicit_local_path_required")
        if not isinstance(sample["source_hash"], str) or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", sample["source_hash"]
        ):
            raise SampleError("source_hash_required")
        pages = sample["pages"]
        if (
            not _integer(sample["bytes"], retained.MAX_PDF_BYTES)
            or not _integer(sample["max_chars"], retained.MAX_CHARS)
            or not isinstance(pages, list)
            or not 1 <= len(pages) <= retained.MAX_PAGES
            or any(not _integer(page, 999_999) for page in pages)
            or pages != sorted(set(pages))
        ):
            raise SampleError("invalid_sample_bounds")
        provenance = sample["provenance"]
        if (
            not isinstance(provenance, dict)
            or set(provenance)
            != {
                "access",
                "title",
                "authors",
                "source_url",
                "license_url",
                "rights_basis",
                "version_basis",
            }
            or not isinstance(provenance["access"], str)
            or provenance["access"] not in {"public", "synthetic"}
            or not all(_text(provenance[key]) for key in ("title", "rights_basis", "version_basis"))
            or not all(_url(provenance[key]) for key in ("source_url", "license_url"))
            or not isinstance(provenance["authors"], list)
            or not 1 <= len(provenance["authors"]) <= 100
            or any(not _text(author, 300) for author in provenance["authors"])
        ):
            raise SampleError("public_or_synthetic_provenance_required")
        regions = sample["regions"]
        if not isinstance(regions, list) or len(regions) > 24:
            raise SampleError("invalid_regions")
        names = set()
        for region in regions:
            if (
                not isinstance(region, dict)
                or set(region) != {"name", "kind", "page", "quote"}
                or not _text(region["name"], 100)
                or region["name"] in names
                or not isinstance(region["kind"], str)
                or region["kind"] not in REGION_KINDS
                or not _integer(region["page"], 999_999)
                or not _text(region["quote"], 2000)
            ):
                raise SampleError("invalid_regions")
            names.add(region["name"])
    if (
        sum(s["bytes"] for s in value["samples"]) > MAX_BATCH_BYTES
        or sum(len(s["pages"]) for s in value["samples"]) > MAX_BATCH_PAGES
        or sum(s["max_chars"] for s in value["samples"]) > MAX_BATCH_CHARS
    ):
        raise SampleError("batch_bounds_exceeded")
    return value


def _read_bounded(path: Path, maximum: int) -> bytes:
    """Read one expressly selected regular file; refuse symlinks and FIFOs."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SampleError("regular_local_file_required")
            if info.st_size > maximum:
                raise SampleError("local_file_too_large")
            content = stream.read(maximum + 1)
            if len(content) > maximum:
                raise SampleError("local_file_too_large")
            return content
    except OSError as exc:
        raise SampleError("local_file_unavailable") from exc


def _load(path: Path, maximum: int) -> Any:
    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise SampleError("duplicate_json_field")
        return result

    try:
        return json.loads(_read_bounded(path, maximum), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, SampleError):
            raise
        raise SampleError("invalid_json") from exc


def _inspection(material: retained.SourceMaterial, sample: dict[str, Any]) -> dict[str, Any]:
    mapping = material.page_numbers or tuple(range(1, len(material.pages) + 1))
    pages = dict(zip(mapping, material.pages, strict=True))
    regions = []
    for region in sample["regions"]:
        text, quote = pages.get(region["page"]), region["quote"]
        item = {
            **region,
            "status": "page_not_retained",
            "start": None,
            "end": None,
            "span_ids": [],
            "reader_fragment": None,
        }
        if text is not None:
            first = text.find(quote)
            item["status"] = "quote_not_found" if first < 0 else "ambiguous_quote"
            if first >= 0 and text.find(quote, first + 1) < 0:
                last = first + len(quote)
                item.update(
                    status="located_text_only",
                    start=first,
                    end=last,
                    span_ids=[
                        s.span_id
                        for s in material.spans
                        if s.page == region["page"] and s.start < last and s.end > first
                    ],
                    reader_fragment=f"material:{material.material_id}:page:{region['page']}:{first}:{last}",
                )
        regions.append(item)
    return {
        "usable_text_present": any(text.strip() for text in material.pages),
        "page_metrics": [
            {
                "page": page,
                "characters": len(text),
                "replacement_glyphs": text.count("\ufffd"),
                "blank": not text.strip(),
            }
            for page, text in pages.items()
        ],
        "span_index": [
            {
                "span_id": s.span_id,
                "page": s.page,
                "start": s.start,
                "end": s.end,
                "reader_fragment": f"material:{material.material_id}:page:{s.page}:{s.start}:{s.end}",
            }
            for s in material.spans
        ],
        "regions": regions,
        "unresolved_regions": sum(r["status"] != "located_text_only" for r in regions),
        "quality_exclusions": list(EXCLUSIONS),
        "visual_review": "not_performed",
        "scientific_qualified": False,
        "human_judgment": None,
        "warnings": [
            *material.warnings,
            "Text offsets address extracted Unicode, not PDF byte or visual coordinates.",
            "Equation/table/figure/algorithm/appendix structure remains unsupported even when a quote is located.",
            "Provenance is declared by the manifest; public status, rights and version correspondence are not independently verified.",
            "Source instructions are untrusted text, never executed. No scientific claim or checker quality is qualified.",
        ],
    }


def prepare_manifest(manifest: Any, *, directory: Path) -> dict[str, Any]:
    """Read only manifest-selected bytes and retain explicit failures per sample."""
    manifest = validate_manifest(manifest)
    records = []
    for sample in manifest["samples"]:
        record: dict[str, Any] = {
            "sample_id": sample["sample_id"],
            "status": "failed",
            "error": None,
            "material": None,
            "inspection": None,
        }
        try:
            raw = _read_bounded(directory / sample["path"], sample["bytes"])
            if len(raw) != sample["bytes"]:
                raise SampleError("source_size_mismatch")
            if "sha256:" + hashlib.sha256(raw).hexdigest() != sample["source_hash"]:
                raise SampleError("source_hash_mismatch")
            material = retained.extract_pdf(
                raw,
                work_id=sample["work_id"],
                version_id=sample["version_id"],
                max_bytes=sample["bytes"],
                max_pages=len(sample["pages"]),
                max_chars=sample["max_chars"],
                page_numbers=sample["pages"],
            )
            record.update(
                status="extracted",
                material=json.loads(_json(asdict(material))),
                inspection=_inspection(material, sample),
            )
        except (SampleError, retained.MaterialError) as exc:
            record["error"] = str(exc)
        record["record_hash"] = _digest(record)
        records.append(record)
    return {
        "schema_version": BUNDLE_REVISION,
        "manifest": manifest,
        "manifest_hash": _digest(manifest),
        "records": records,
    }


def _restore(data: Any, sample: dict[str, Any]) -> retained.SourceMaterial:
    """Rebuild existing material/span IDs and exact offsets, without PDF reads."""
    try:
        pages, numbers = data["pages"], data["page_numbers"]
        if (
            not isinstance(pages, list)
            or not 1 <= len(pages) <= len(sample["pages"])
            or any(not isinstance(text, str) for text in pages)
            or sum(len(text) for text in pages) > sample["max_chars"]
            or not isinstance(numbers, list)
            or any(type(number) is not int for number in numbers)
            or numbers != sample["pages"][: len(pages)]
            or not _integer(data["page_count"], 999_999)
            or max(numbers) > data["page_count"]
            or type(data["complete"]) is not bool
            or not _text(data["parser_revision"], 200)
            or not data["parser_revision"].startswith("workspace-pymupdf-")
            or not data["parser_revision"].endswith("-selected-pages-v1")
            or data["quality"] not in {"empty", "partial", "text_extracted"}
            or data["scope"] != ("full_text" if data["complete"] else "excerpt")
            or (data["complete"] and numbers != list(range(1, data["page_count"] + 1)))
            or (data["quality"] == "empty") != (not any(text.strip() for text in pages))
            or (data["quality"] == "partial" and data["complete"])
            or (data["quality"] == "text_extracted" and not data["complete"])
            or not isinstance(data["warnings"], list)
            or len(data["warnings"]) > 32
            or any(not _text(warning) for warning in data["warnings"])
        ):
            raise SampleError("retained_material_drift")
        material = retained._build(
            work_id=sample["work_id"],
            version_id=sample["version_id"],
            source_hash=sample["source_hash"],
            scope=data["scope"],
            parser_revision=data["parser_revision"],
            pages=pages,
            page_count=data["page_count"],
            quality=data["quality"],
            warnings=data["warnings"],
            complete=data["complete"],
            page_numbers=numbers,
        )
        if _json(asdict(material)) != _json(data):
            raise SampleError("retained_material_drift")
        return material
    except (KeyError, TypeError, ValueError) as exc:
        raise SampleError("retained_material_drift") from exc


def audit_bundle(bundle: Any, manifest: Any) -> dict[str, Any]:
    """Integrity only: compare the external manifest and rebuild every text span.

    This does not reopen PDFs, authenticate an untrusted manifest, or upgrade
    pending visual/semantic review to qualification. Empty/failed samples remain
    unavailable even when their diagnostic records have valid integrity.
    """
    manifest = validate_manifest(manifest)
    if (
        not isinstance(bundle, dict)
        or set(bundle) != {"schema_version", "manifest", "manifest_hash", "records"}
        or bundle["schema_version"] != BUNDLE_REVISION
        or bundle["manifest_hash"] != _digest(manifest)
        or _json(bundle["manifest"]) != _json(manifest)
        or not isinstance(bundle["records"], list)
        or len(bundle["records"]) != len(manifest["samples"])
    ):
        raise SampleError("bundle_manifest_drift")
    extracted, unavailable, unresolved, failures = 0, 0, 0, []
    for record, sample in zip(bundle["records"], manifest["samples"], strict=True):
        if (
            not isinstance(record, dict)
            or set(record)
            != {"sample_id", "status", "error", "material", "inspection", "record_hash"}
            or record["sample_id"] != sample["sample_id"]
            or record["record_hash"]
            != _digest({k: v for k, v in record.items() if k != "record_hash"})
        ):
            raise SampleError("sample_record_drift")
        if record["status"] == "failed":
            if (
                not _text(record["error"], 200)
                or record["material"] is not None
                or record["inspection"] is not None
            ):
                raise SampleError("invalid_failure_record")
            failures.append({"sample_id": sample["sample_id"], "error": record["error"]})
            continue
        if record["status"] != "extracted" or record["error"] is not None:
            raise SampleError("invalid_sample_status")
        material = _restore(record["material"], sample)
        inspection = _inspection(material, sample)
        if _json(record["inspection"]) != _json(inspection):
            raise SampleError("inspection_drift")
        extracted += 1
        unavailable += not inspection["usable_text_present"]
        unresolved += inspection["unresolved_regions"]
    return {
        "integrity": "verified",
        "samples": len(manifest["samples"]),
        "extracted": extracted,
        "failed": failures,
        "unavailable_text": unavailable,
        "unresolved_regions": unresolved,
        "preparation_complete": not failures and not unavailable and not unresolved,
        "source_pdf_rechecked_by_audit": False,
        "scientific_qualified": False,
        "network_requests": 0,
        "provider_contacts": 0,
        "database_writes": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser(
        "prepare", help="Prepare only explicitly manifest-selected local PDF bytes"
    )
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New JSON file; existing files are never overwritten",
    )
    audit = sub.add_parser(
        "audit", help="Audit retained text against an external manifest; never reopen PDFs"
    )
    audit.add_argument("--manifest", type=Path, required=True)
    audit.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = _load(args.manifest, MAX_MANIFEST_BYTES)
        if args.command == "prepare":
            if args.output.exists() or args.output.is_symlink():
                raise SampleError("output_already_exists")
            bundle = prepare_manifest(manifest, directory=args.manifest.absolute().parent)
            report = audit_bundle(bundle, manifest)
            encoded = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
            if len(encoded.encode()) > MAX_BUNDLE_BYTES:
                raise SampleError("bundle_too_large")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        else:
            report = audit_bundle(_load(args.bundle, MAX_BUNDLE_BYTES), manifest)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["preparation_complete"] else 3
    except (SampleError, OSError) as exc:
        print(f"source-samples refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
