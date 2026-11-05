"""Manifest-only local PDFs: real extraction, drift detection and no external work."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

import pytest
from reportlab.pdfgen import canvas

from src.workspace import material
from src.workspace import source_samples as samples

pytestmark = pytest.mark.integration


def pdf_bytes(*, blank: bool = False) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, invariant=True)
    for page in range(1, 4):
        if not blank:
            pdf.drawString(72, 720, f"Synthetic methods on original page {page}.")
            pdf.drawString(72, 700, "Repeated text. Repeated text.")
            pdf.drawString(72, 680, "Table and equation x = y = z = 1 are unqualified.")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def manifest(tmp_path: Path, *, count: int = 1, blank: bool = False) -> dict:
    raw = pdf_bytes(blank=blank)
    path = tmp_path / "selected.pdf"
    path.write_bytes(raw)
    return {
        "schema_version": samples.MANIFEST_REVISION,
        "samples": [
            {
                "sample_id": f"synthetic-{i}",
                "path": path.name,
                "work_id": f"test:paper-{i}",
                "version_id": f"test:paper-{i}:v1",
                "source_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "pages": [1, 3],
                "max_chars": 120_000,
                "provenance": {
                    "access": "synthetic",
                    "title": "Synthetic, not a scientific qualification",
                    "authors": ["Test fixture"],
                    "source_url": "https://example.invalid/synthetic-v1",
                    "license_url": "https://example.invalid/synthetic-license",
                    "rights_basis": "Generated for this local test",
                    "version_basis": "Deterministic reportlab fixture v1; no publication date inferred",
                },
                "regions": [
                    {
                        "name": "methods",
                        "kind": "prose",
                        "page": 3,
                        "quote": "Synthetic methods on original page 3.",
                    }
                ],
            }
            for i in range(count)
        ],
    }


def resign(record: dict) -> None:
    record["record_hash"] = samples._digest(
        {key: value for key, value in record.items() if key != "record_hash"}
    )


def test_arbitrary_three_samples_reuse_existing_exact_material_identity(tmp_path, monkeypatch):
    declared = manifest(tmp_path, count=3)
    # No discovery: an adjacent unselected invalid/private-named file is never opened.
    (tmp_path / "unselected-private.pdf").write_bytes(b"not selected")
    actual_read = samples._read_bounded
    reads = []

    def selected_only(path, maximum):
        reads.append(path)
        assert path.name == "selected.pdf"
        return actual_read(path, maximum)

    monkeypatch.setattr(samples, "_read_bounded", selected_only)
    result = samples.prepare_manifest(declared, directory=tmp_path)
    assert len(reads) == 3
    report = samples.audit_bundle(result, declared)
    assert report == {
        "integrity": "verified",
        "samples": 3,
        "extracted": 3,
        "failed": [],
        "unavailable_text": 0,
        "unresolved_regions": 0,
        "preparation_complete": True,
        "source_pdf_rechecked_by_audit": False,
        "scientific_qualified": False,
        "network_requests": 0,
        "provider_contacts": 0,
        "database_writes": 0,
    }
    for sample, record in zip(declared["samples"], result["records"], strict=True):
        expected = material.extract_pdf(
            (tmp_path / sample["path"]).read_bytes(),
            work_id=sample["work_id"],
            version_id=sample["version_id"],
            page_numbers=[1, 3],
            max_pages=2,
        )
        assert record["material"] == json.loads(json.dumps(asdict(expected)))
        assert expected.page_count == 3 and expected.page_numbers == (1, 3)
        assert expected.scope == "excerpt" and not expected.complete
        region = record["inspection"]["regions"][0]
        assert region["status"] == "located_text_only"
        assert region["quote"] == expected.pages[1][region["start"] : region["end"]]
        assert region["span_ids"] == [expected.spans[1].span_id]
        assert region["reader_fragment"] == f"material:{expected.material_id}:page:3:0:37"
        assert record["inspection"]["scientific_qualified"] is False
        assert "appendix_structure" in record["inspection"]["quality_exclusions"]
        assert all(
            span.text == expected.pages[[1, 3].index(span.page)][span.start : span.end]
            for span in expected.spans
        )
    assert samples.prepare_manifest(declared, directory=tmp_path) == result


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda m: m.update(schema_version="other"), "invalid_manifest"),
        (lambda m: m["samples"][0].update(unexpected=True), "invalid_sample_fields"),
        (lambda m: m["samples"][0].update(sample_id="../secret"), "invalid_sample_id"),
        (lambda m: m["samples"][0].update(work_id=""), "source_version_required"),
        (
            lambda m: m["samples"].append(copy.deepcopy(m["samples"][0])),
            "duplicate_sample_or_version",
        ),
        (
            lambda m: m["samples"][0].update(path="https://example.invalid/file.pdf"),
            "explicit_local_path_required",
        ),
        (lambda m: m["samples"][0].update(path="~/.private.pdf"), "explicit_local_path_required"),
        (lambda m: m["samples"][0].update(source_hash="unsealed"), "source_hash_required"),
        (lambda m: m["samples"][0].update(pages=[True]), "invalid_sample_bounds"),
        (lambda m: m["samples"][0].update(pages=[3, 1]), "invalid_sample_bounds"),
        (lambda m: m["samples"][0].update(pages=[1, 1]), "invalid_sample_bounds"),
        (lambda m: m["samples"][0].update(max_chars=120001), "invalid_sample_bounds"),
        (
            lambda m: m["samples"][0]["provenance"].update(access="private"),
            "public_or_synthetic_provenance_required",
        ),
        (
            lambda m: m["samples"][0]["provenance"].update(access=[]),
            "public_or_synthetic_provenance_required",
        ),
        (
            lambda m: m["samples"][0]["provenance"].update(
                source_url="https://user:password@example.invalid/a"
            ),
            "public_or_synthetic_provenance_required",
        ),
        (
            lambda m: m["samples"][0]["provenance"].update(rights_basis=""),
            "public_or_synthetic_provenance_required",
        ),
        (lambda m: m["samples"][0]["regions"][0].update(kind=[]), "invalid_regions"),
    ],
)
def test_invalid_manifest_refused_before_any_pdf_or_parser(tmp_path, monkeypatch, change, reason):
    declared = manifest(tmp_path)
    change(declared)
    read, extract = Mock(), Mock()
    monkeypatch.setattr(samples, "_read_bounded", read)
    monkeypatch.setattr(material, "extract_pdf", extract)
    with pytest.raises(samples.SampleError, match=reason):
        samples.prepare_manifest(declared, directory=tmp_path)
    read.assert_not_called()
    extract.assert_not_called()


@pytest.mark.parametrize("bound", ["samples", "bytes", "pages", "chars"])
def test_whole_batch_caps_checked_before_selected_reads(tmp_path, monkeypatch, bound):
    declared = manifest(tmp_path, count=8)
    for sample in declared["samples"]:
        sample["max_chars"] = 1
    if bound == "samples":
        declared["samples"].append(copy.deepcopy(declared["samples"][0]))
    elif bound == "bytes":
        for sample in declared["samples"]:
            sample["bytes"] = material.MAX_PDF_BYTES
    elif bound == "pages":
        for sample in declared["samples"]:
            sample["pages"] = list(range(1, 13))
    else:
        for sample in declared["samples"]:
            sample["max_chars"] = material.MAX_CHARS
    read = Mock()
    monkeypatch.setattr(samples, "_read_bounded", read)
    with pytest.raises(samples.SampleError, match="invalid_manifest|batch_bounds_exceeded"):
        samples.prepare_manifest(declared, directory=tmp_path)
    read.assert_not_called()


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("hash", "source_hash_mismatch"),
        ("short", "source_size_mismatch"),
        ("long", "local_file_too_large"),
        ("missing", "local_file_unavailable"),
        ("symlink", "local_file_unavailable"),
        ("fifo", "regular_local_file_required"),
    ],
)
def test_bad_selected_input_keeps_failure_without_inventing_material(
    tmp_path, monkeypatch, mode, reason
):
    declared = manifest(tmp_path)
    target = tmp_path / "selected.pdf"
    if mode == "hash":
        declared["samples"][0]["source_hash"] = "sha256:" + "0" * 64
    elif mode == "short":
        declared["samples"][0]["bytes"] += 1
    elif mode == "long":
        declared["samples"][0]["bytes"] -= 1
    elif mode == "missing":
        target.unlink()
    elif mode == "symlink":
        target.rename(tmp_path / "public-original.pdf")
        target.symlink_to(tmp_path / "public-original.pdf")
    else:
        target.unlink()
        os.mkfifo(target)
    extract = Mock()
    monkeypatch.setattr(material, "extract_pdf", extract)
    bundle = samples.prepare_manifest(declared, directory=tmp_path)
    record = bundle["records"][0]
    assert record["status"] == "failed" and record["error"] == reason
    assert record["material"] is record["inspection"] is None
    report = samples.audit_bundle(bundle, declared)
    assert report["integrity"] == "verified" and not report["preparation_complete"]
    assert report["extracted"] == 0 and report["failed"] == [
        {"sample_id": "synthetic-0", "error": reason}
    ]
    extract.assert_not_called()


def test_parser_failure_is_recorded_and_unsupported_regions_never_qualify(tmp_path, monkeypatch):
    declared = manifest(tmp_path)
    monkeypatch.setattr(
        material, "extract_pdf", Mock(side_effect=material.MaterialError("extraction_timed_out"))
    )
    bundle = samples.prepare_manifest(declared, directory=tmp_path)
    assert samples.audit_bundle(bundle, declared)["failed"][0]["error"] == "extraction_timed_out"


def test_regions_require_unique_exact_page_quote_without_invented_boundaries(tmp_path):
    declared = manifest(tmp_path)
    declared["samples"][0]["regions"] = [
        {"name": "equation", "kind": "equation", "page": 3, "quote": "x = y = z = 1"},
        {"name": "ambiguous", "kind": "prose", "page": 1, "quote": "Repeated text."},
        {"name": "omitted appendix", "kind": "appendix", "page": 2, "quote": "Synthetic"},
        {"name": "missing", "kind": "table", "page": 3, "quote": "not present"},
    ]
    bundle = samples.prepare_manifest(declared, directory=tmp_path)
    inspection = bundle["records"][0]["inspection"]
    assert [region["status"] for region in inspection["regions"]] == [
        "located_text_only",
        "ambiguous_quote",
        "page_not_retained",
        "quote_not_found",
    ]
    assert inspection["regions"][0]["span_ids"]
    assert all(
        region["start"] is region["end"] is region["reader_fragment"] is None
        for region in inspection["regions"][1:]
    )
    assert inspection["human_judgment"] is None and not inspection["scientific_qualified"]
    assert samples.audit_bundle(bundle, declared)["unresolved_regions"] == 3


def test_empty_pdf_and_char_cap_remain_unavailable_or_excerpt(tmp_path):
    declared = manifest(tmp_path, blank=True)
    blank = samples.prepare_manifest(declared, directory=tmp_path)
    report = samples.audit_bundle(blank, declared)
    assert report["unavailable_text"] == 1 and not report["preparation_complete"]
    assert blank["records"][0]["material"]["quality"] == "empty"
    declared = manifest(tmp_path)
    declared["samples"][0]["max_chars"] = 10
    partial = samples.prepare_manifest(declared, directory=tmp_path)
    retained = partial["records"][0]["material"]
    assert retained["scope"] == "excerpt" and not retained["complete"]
    assert retained["page_numbers"] == [1] and sum(map(len, retained["pages"])) == 10
    assert samples.audit_bundle(partial, declared)["unresolved_regions"] == 1


def test_region_uses_unicode_codepoints_and_all_intersecting_spans(tmp_path):
    declared = manifest(tmp_path)
    sample = declared["samples"][0]
    sample["regions"] = [
        {"name": "cross-span", "kind": "appendix", "page": 3, "quote": "🙂UNIQUE α🙂"}
    ]
    text = "α🙂" * 999 + "UNIQUE α🙂 tail"
    retained = material._build(
        work_id=sample["work_id"],
        version_id=sample["version_id"],
        source_hash=sample["source_hash"],
        scope="excerpt",
        parser_revision="fixture-only",
        pages=[text],
        page_count=4,
        page_numbers=[3],
        quality="partial",
        warnings=[],
        complete=False,
    )
    region = samples._inspection(retained, sample)["regions"][0]
    assert (region["start"], region["end"]) == (1997, 2007)
    assert region["quote"] == text[1997:2007]
    assert region["span_ids"] == [span.span_id for span in retained.spans]
    assert region["reader_fragment"].endswith(":page:3:1997:2007")


def test_full_retained_pdf_still_does_not_qualify_semantics_and_mixed_batch_reports_failure(
    tmp_path,
):
    declared = manifest(tmp_path, count=2)
    declared["samples"][0]["pages"] = [1, 2, 3]
    declared["samples"][1]["path"] = "not-selected-anywhere-else.pdf"
    bundle = samples.prepare_manifest(declared, directory=tmp_path)
    retained = bundle["records"][0]["material"]
    assert retained["scope"] == "full_text" and retained["complete"]
    report = samples.audit_bundle(bundle, declared)
    assert report["extracted"] == 1 and len(report["failed"]) == 1
    assert not report["preparation_complete"] and not report["scientific_qualified"]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda b: b.update(records=[]), "bundle_manifest_drift"),
        (lambda b: b["records"][0].update(sample_id="other"), "sample_record_drift"),
        (lambda b: b["records"][0].update(status="qualified"), "invalid_sample_status"),
        (
            lambda b: b["records"][0].update(status="failed", error="error"),
            "invalid_failure_record",
        ),
    ],
)
def test_audit_rejects_missing_reordered_or_relabelled_records(tmp_path, mutation, reason):
    declared = manifest(tmp_path)
    bundle = samples.prepare_manifest(declared, directory=tmp_path)
    mutation(bundle)
    if bundle["records"]:
        resign(bundle["records"][0])
    with pytest.raises(samples.SampleError, match=reason):
        samples.audit_bundle(bundle, declared)


@pytest.mark.parametrize(
    "field,value",
    [
        ("span", "invented"),
        ("material_id", "mat-" + "0" * 32),
        ("page_numbers", [1, 2]),
        ("version_id", "another-version"),
        ("complete", True),
        ("scope", "full_text"),
        ("page_count", True),
        ("parser_revision", "unqualified-parser"),
    ],
)
def test_recomputed_record_hash_cannot_hide_material_identity_or_offset_drift(
    tmp_path, field, value
):
    declared = manifest(tmp_path)
    bundle = samples.prepare_manifest(declared, directory=tmp_path)
    record = bundle["records"][0]
    if field == "span":
        record["material"]["spans"][0]["text"] = value
    else:
        record["material"][field] = value
    resign(record)
    with pytest.raises(samples.SampleError, match="retained_material_drift"):
        samples.audit_bundle(bundle, declared)


def test_audit_rebuilds_inspection_and_compares_external_manifest_without_pdf_reads(
    tmp_path, monkeypatch
):
    declared = manifest(tmp_path)
    original = samples.prepare_manifest(declared, directory=tmp_path)
    (tmp_path / "selected.pdf").unlink()
    monkeypatch.setattr(
        samples, "_read_bounded", Mock(side_effect=AssertionError("audit must not reopen files"))
    )
    assert samples.audit_bundle(original, declared)["integrity"] == "verified"
    for field in ["source_hash", "provenance"]:
        changed = copy.deepcopy(declared)
        if field == "source_hash":
            changed["samples"][0][field] = "sha256:" + "0" * 64
        else:
            changed["samples"][0][field]["title"] = "Replaced source attribution"
        with pytest.raises(samples.SampleError, match="bundle_manifest_drift"):
            samples.audit_bundle(original, changed)
    changed = copy.deepcopy(original)
    changed["records"][0]["inspection"]["scientific_qualified"] = True
    with pytest.raises(samples.SampleError, match="sample_record_drift"):
        samples.audit_bundle(changed, declared)
    resign(changed["records"][0])
    with pytest.raises(samples.SampleError, match="inspection_drift"):
        samples.audit_bundle(changed, declared)


def test_cli_exclusive_output_separate_audit_and_failure_exit_codes(tmp_path, capsys):
    declared = manifest(tmp_path)
    source, output = tmp_path / "manifest.json", tmp_path / "bundle.json"
    source.write_text(json.dumps(declared))
    prepare = ["prepare", "--manifest", str(source), "--output", str(output)]
    assert samples.main(prepare) == 0
    original = output.read_bytes()
    assert samples.main(prepare) == 2 and output.read_bytes() == original
    assert "output_already_exists" in capsys.readouterr().err
    (tmp_path / "selected.pdf").unlink()
    assert samples.main(["audit", "--manifest", str(source), "--bundle", str(output)]) == 0
    assert (
        samples.main(
            ["prepare", "--manifest", str(source), "--output", str(tmp_path / "failed.json")]
        )
        == 3
    )
    source.write_text("not JSON")
    assert samples.main(prepare) == 2
    assert "invalid_json" in capsys.readouterr().err
    assert (
        samples.main(
            ["audit", "--manifest", str(tmp_path / "missing.json"), "--bundle", str(output)]
        )
        == 2
    )
    assert "local_file_unavailable" in capsys.readouterr().err


def test_real_cli_stays_offline_without_provider_database_acquisition_or_dotenv_imports(tmp_path):
    declared = manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(declared))
    script = """
import importlib.abc, socket, sys
class OfflineImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'anthropic', 'httpx', 'urllib3', 'psycopg', 'dotenv'} or fullname in {'src.workspace.store', 'src.workspace.fulltext', 'src.workspace.provider_adapter'}:
            raise AssertionError('forbidden offline import: ' + fullname)
sys.meta_path.insert(0, OfflineImports())
def denied(*args, **kwargs):
    raise AssertionError('offline command attempted networking')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.getaddrinfo = denied
from src.workspace.source_samples import main
raise SystemExit(main(['prepare', '--manifest', sys.argv[1], '--output', sys.argv[2]]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(tmp_path / "tripwire-bundle.json")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "ANTHROPIC_API_KEY": "local-preview-disabled",
            "USE_MOCK_DATA": "true",
            "WORKSPACE_SCHEDULE_APPROVED": "false",
        },
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["preparation_complete"]


def test_json_cannot_hide_a_second_selected_path_and_manifest_input_is_bounded(tmp_path, capsys):
    source = tmp_path / "manifest.json"
    source.write_text('{"path":"public.pdf","path":"another.pdf"}')
    args = ["prepare", "--manifest", str(source), "--output", str(tmp_path / "out.json")]
    assert samples.main(args) == 2
    assert "duplicate_json_field" in capsys.readouterr().err
    source.write_bytes(b" " * (samples.MAX_MANIFEST_BYTES + 1))
    assert samples.main(args) == 2
    assert "local_file_too_large" in capsys.readouterr().err
    depth = sys.getrecursionlimit() + 100
    source.write_text("[" * depth + "]" * (depth - 1))
    assert samples.main(args) == 2
    assert "invalid_json" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()
