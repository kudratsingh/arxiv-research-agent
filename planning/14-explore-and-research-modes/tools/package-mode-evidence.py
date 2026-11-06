"""Curate source-bound evidence; preserve raw local records and omit personal payloads."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "planning/14-explore-and-research-modes/evidence/d1-d4-browser"
RUN = BASE / "runs/2026-11-06T00-48-43-041Z-9c42c3d7"
redactions = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def redact(value):
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"profile", "preferences"} and isinstance(item, dict):
                result[key] = {
                    "redacted": "Copied preferences stay local",
                    "revision": item.get("revision"),
                    "original_sha256": hashlib.sha256(
                        json.dumps(item, sort_keys=True).encode()
                    ).hexdigest(),
                }
            elif key == "abstract" and isinstance(item, str):
                result[key] = {
                    "omitted_bulk_payload": True,
                    "characters": len(item),
                    "sha256": hashlib.sha256(item.encode()).hexdigest(),
                }
            else:
                result[key] = redact(item)
        return result
    return value


def json_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(source.read_text())
    target.write_text(json.dumps(redact(data), indent=2) + "\n")
    redactions.append(
        {
            "original_local_path": str(source.relative_to(ROOT)),
            "original_sha256": sha(source),
            "committed_copy": str(target.relative_to(ROOT)),
            "copy_sha256": sha(target),
            "policy": "Preference values and unneeded bulk abstracts omitted; exact selected quotes/IDs/bindings and case outcomes preserved",
        }
    )


report = json.loads((RUN / "report.json").read_text())
assert report["applicationCommit"].startswith("cea881e")
assert len(report["cases"]) == 96 and all(c["status"] == "pass" for c in report["cases"])
assert json.loads((RUN / "post-restart/report.json").read_text())["status"] == "pass"
accepted = BASE / "accepted/cea881e"
for name in [
    "report.json",
    "source-and-build-binding.json",
    "baseline-identity.json",
    "restart-checkpoint.json",
    "root-restart-receipt.json",
]:
    json_copy(RUN / name, accepted / name)
for p in (RUN / "post-restart").rglob("*"):
    if p.is_file():
        target = accepted / "post-restart" / p.relative_to(RUN / "post-restart")
        target.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".json":
            json_copy(p, target)
        else:
            shutil.copyfile(p, target)
for context in ["desktop-light", "desktop-dark", "mobile-light", "mobile-dark"]:
    (accepted / context).mkdir(parents=True, exist_ok=True)
    for p in (RUN / context).glob("*.png"):
        if p.name != "interests.png":
            shutil.copyfile(p, accepted / context / p.name)
for name in ["service-receipt.json", "corpus-manifest.json"]:
    json_copy(BASE / name, accepted / name)
# An earlier accepted cohort remains independently source-attributed.
old_run = BASE / "runs/2026-11-05T23-53-49-246Z-18433d73"
for name in ["report.json", "restart-checkpoint.json"]:
    json_copy(old_run / name, BASE / "accepted/8e34670" / name)
json_copy(old_run / "post-restart/report.json", BASE / "accepted/8e34670/post-restart/report.json")
privacy = BASE / "diagnostics/personal-profile-views"
for p in list((BASE / "accepted").glob("*/**/interests.png")) + list(
    (BASE / "final-layout").glob("*/*-interests.png")
):
    destination = privacy / p.relative_to(BASE)
    destination.parent.mkdir(parents=True, exist_ok=True)
    redactions.append(
        {
            "original_local_path": str(destination.relative_to(ROOT)),
            "original_sha256": sha(p),
            "scope": "Personal-interest screenshot preserved locally, omitted from remote evidence",
        }
    )
    shutil.move(str(p), str(destination))
# Full readable recordings include the copied organizing question. They remain local.
(BASE / "owner-walkthrough/.gitignore").write_text(
    "diagnostics/\n**/*.webm\n**/explore.png\n**/video-inspection/*.png\n"
)
# Provisional observations are not final acceptance and may show the copied profile.
(BASE.parent / "provisional-visual/.gitignore").write_text("*.webm\n**/*.png\n")
index = []
for p in sorted((BASE / "runs").glob("*/report.json")):
    data = json.loads(p.read_text())
    index.append(
        {
            "local_original": str(p.relative_to(ROOT)),
            "sha256": sha(p),
            "application_commit": data.get("applicationCommit"),
            "recorded_status": data.get("status"),
            "cases": len(data.get("cases", [])),
            "failed": sum(c.get("status") == "fail" for c in data.get("cases", [])),
            "interpretation": "Original chronological state retained; interrupted/zero-case/failed runs are not passes",
        }
    )
(BASE / "prior-runs-index.json").write_text(json.dumps(index, indent=2) + "\n")
(BASE / "redaction-and-local-originals.json").write_text(json.dumps(redactions, indent=2) + "\n")
print("Packaged96-case functional cohort; personal payloads/raw originals remain local")
