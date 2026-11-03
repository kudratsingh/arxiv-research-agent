"""Owner-visible retained material and explicit public qualification registration.

This repository never fetches sources, overwrites an abstract/version or upgrades
an extraction into verified factual support. Material payload and acquisition/
quality provenance are separate immutable records. Registration is restricted to
the two pinned public samples; private canonical-identity collisions are refused.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.fulltext import PdfSpec, sample_spec
from src.workspace.material import MAX_PDF_BYTES, MaterialError, SourceMaterial, _build
from src.workspace.store import ConflictError, WorkspaceStore, digest


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def _validated_payload(
    spec: PdfSpec,
    material: SourceMaterial,
    acquisition: dict[str, Any],
    qualification: dict[str, Any],
) -> dict[str, Any]:
    if spec != sample_spec(spec.arxiv_version):
        raise MaterialError("qualification_sample_spec_drift")
    if material.work_id != spec.work_id or material.version_id != spec.version_id:
        raise MaterialError("qualification_source_version_drift")
    if (
        material.scope not in {"excerpt", "full_text"}
        or material.page_count is None
        or material.page_count < 1
    ):
        raise MaterialError("qualification_requires_pdf_material")
    rebuilt = _build(
        work_id=material.work_id,
        version_id=material.version_id,
        source_hash=material.source_hash,
        scope=material.scope,
        parser_revision=material.parser_revision,
        pages=list(material.pages),
        page_count=material.page_count,
        quality=material.quality,
        warnings=list(material.warnings),
        complete=material.complete,
        page_numbers=list(material.page_numbers) if material.page_numbers is not None else None,
    )
    if material != rebuilt:
        raise MaterialError("qualification_material_identity_drift")
    for record in (acquisition, qualification):
        if _json(record.get("sample")) != _json(asdict(spec)):
            raise MaterialError("qualification_provenance_sample_drift")
        if (
            record.get("source_hash") != material.source_hash
            or record.get("sample", {}).get("arxiv_version") != spec.arxiv_version
        ):
            raise MaterialError("qualification_provenance_source_drift")
    if acquisition.get("status") != "extracted" or acquisition.get("http_status") != 200:
        raise MaterialError("qualification_acquisition_not_successful")
    if (
        acquisition.get("requested_url") != spec.pdf_url
        or acquisition.get("resolved_url") != spec.pdf_url
        or acquisition.get("request_count") != 1
    ):
        raise MaterialError("qualification_acquisition_scope_drift")
    size = acquisition.get("bytes")
    if type(size) is not int or not 1 <= size <= MAX_PDF_BYTES:
        raise MaterialError("qualification_acquisition_bounds_invalid")
    if qualification.get("material_id") != material.material_id:
        raise MaterialError("qualification_material_reference_drift")
    expected_pages = (
        list(material.page_numbers)
        if material.page_numbers is not None
        else list(range(1, len(material.pages) + 1))
    )
    if (
        qualification.get("retained_pages") != expected_pages
        or qualification.get("page_count") != material.page_count
    ):
        raise MaterialError("qualification_page_mapping_drift")
    if (
        qualification.get("source_scope") != material.scope
        or qualification.get("complete") != material.complete
    ):
        raise MaterialError("qualification_scope_drift")
    observed = datetime.fromisoformat(str(acquisition.get("fetched_at") or ""))
    if observed.tzinfo is None:
        raise MaterialError("qualification_acquisition_time_required")
    return dict(_json(asdict(material)))


class WorkspaceMaterials:
    def __init__(self, store: WorkspaceStore):
        self.store = store

    def list(self, owner: str, work_id: str, version_id: str) -> list[dict[str, Any]]:
        """List metadata only, always through the work/version visibility boundary."""
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            rows = conn.execute(
                "SELECT m.data,p.data FROM workspace_material m JOIN workspace_versions v ON v.version_id=m.version_id JOIN workspace_works w ON w.work_id=v.work_id LEFT JOIN workspace_material_provenance p ON p.material_id=m.material_id WHERE v.work_id=%s AND v.version_id=%s AND (w.visibility_owner IS NULL OR w.visibility_owner=%s) ORDER BY m.material_id",
                (work_id, version_id, owner),
            ).fetchall()
        result = [
            {
                **{key: value for key, value in row[0].items() if key not in {"pages", "spans"}},
                "provenance": row[1] or {},
            }
            for row in rows
        ]
        priority = {"full_text": 0, "excerpt": 1, "abstract": 2, "metadata": 3}
        result.sort(
            key=lambda item: (
                4 if item.get("quality") == "empty" else priority.get(str(item.get("scope")), 3),
                item["material_id"],
            )
        )
        return result

    def get(self, owner: str, material_id: str) -> dict[str, Any] | None:
        """Return retained text plus separate provenance, or no existence signal."""
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            row = conn.execute(
                "SELECT m.data,p.data FROM workspace_material m JOIN workspace_versions v ON v.version_id=m.version_id JOIN workspace_works w ON w.work_id=v.work_id LEFT JOIN workspace_material_provenance p ON p.material_id=m.material_id WHERE m.material_id=%s AND (w.visibility_owner IS NULL OR w.visibility_owner=%s)",
                (material_id, owner),
            ).fetchone()
        return {**row[0], "provenance": row[1] or {}} if row else None

    def register_sample(
        self,
        spec: PdfSpec,
        material: SourceMaterial,
        acquisition: dict[str, Any],
        qualification: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically register one known public sample without network or note writes.

        Existing public work/version metadata is never replaced. A metadata-only
        source record is created only when absent; dates remain unknown because
        a qualification fetch timestamp is not a publication timestamp.
        """
        payload = _validated_payload(spec, material, acquisition, qualification)
        provenance = _json(
            {"schema_version": "1.0.0", "acquisition": acquisition, "qualification": qualification}
        )
        self.store.migrate()
        with self.store.pool.connection() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("scientific-sample:" + spec.work_id,),
            )
            work = conn.execute(
                "SELECT visibility_owner FROM workspace_works WHERE work_id=%s FOR UPDATE",
                (spec.work_id,),
            ).fetchone()
            if work and work[0] is not None:
                raise ConflictError("qualification public identity collides with private work")
            now = datetime.fromisoformat(acquisition["fetched_at"]).astimezone(UTC).isoformat()
            conn.execute(
                "INSERT INTO workspace_works(work_id,first_seen_at,visibility_owner) VALUES (%s,%s,NULL) ON CONFLICT DO NOTHING",
                (spec.work_id, now),
            )
            version = conn.execute(
                "SELECT work_id FROM workspace_versions WHERE version_id=%s", (spec.version_id,)
            ).fetchone()
            if version and version[0] != spec.work_id:
                raise ConflictError("qualification version belongs to a different work")
            if not version:
                item: dict[str, Any] = {
                    "work_id": spec.work_id,
                    "version_id": spec.version_id,
                    "source_id": "scientific-sample",
                    "source_record_id": spec.arxiv_version,
                    "title": spec.title,
                    "authors": list(spec.authors),
                    "url": spec.abs_url,
                    "abstract": "",
                    "source_scope": "metadata",
                    "access_state": "metadata",
                    "kind": "paper",
                    "version_label": spec.arxiv_version.rsplit("v", 1)[-1],
                    "published_at": None,
                    "updated_at": None,
                    "published_precision": "unknown",
                    "updated_precision": "unknown",
                    "first_seen_at": now,
                    "fetched_at": now,
                    "content_hash": digest(asdict(spec)),
                    "limitations": [
                        "Public scientific qualification sample; original publication/update dates not inferred from acquisition time."
                    ],
                }
                item["version_label"] = "v" + item["version_label"]
                conn.execute(
                    "INSERT INTO workspace_versions(version_id,work_id,source_id,data,observed_at) VALUES (%s,%s,'scientific-sample',%s,clock_timestamp())",
                    (spec.version_id, spec.work_id, Jsonb(item)),
                )
            previous = conn.execute(
                "SELECT data FROM workspace_material WHERE material_id=%s", (material.material_id,)
            ).fetchone()
            if previous and previous[0] != payload:
                raise ConflictError("immutable qualification material differs")
            prior_provenance = conn.execute(
                "SELECT data FROM workspace_material_provenance WHERE material_id=%s",
                (material.material_id,),
            ).fetchone()
            if prior_provenance and prior_provenance[0] != provenance:
                raise ConflictError("immutable qualification provenance differs")
            conn.execute(
                "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    material.material_id,
                    spec.version_id,
                    material.content_hash,
                    material.scope,
                    Jsonb(payload),
                ),
            )
            conn.execute(
                "INSERT INTO workspace_material_provenance VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (material.material_id, Jsonb(provenance)),
            )
            conn.execute(
                "INSERT INTO workspace_observations VALUES ('scientific-sample',%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (spec.arxiv_version, material.source_hash, spec.version_id, now),
            )
        return {
            "work_id": spec.work_id,
            "version_id": spec.version_id,
            "material_id": material.material_id,
            "source_id": "scientific-sample",
            "registered": True,
            "created": previous is None,
        }
