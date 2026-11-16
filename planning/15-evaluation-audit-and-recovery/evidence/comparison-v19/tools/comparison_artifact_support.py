# ruff: noqa: E402
"""Read-only packet and privacy helpers for prospective artifact tooling."""

import gzip
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()
if not (ROOT / "src/workspace/d5_campaign_v19_packet.py").is_file():
    raise RuntimeError("Run from the intended worktree root")
sys.path.insert(0, str(ROOT))
import src

assert Path(src.__file__).resolve().parent == ROOT / "src"
from src.workspace.admission import _digest
from src.workspace.d5_benchmark import read
from src.workspace.d5_benchmark import write as write
from src.workspace.d5_freeze import verify

PROGRAMME_FIELDS = {
    "authorization_digest",
    "expires_at",
    "extension_id",
    "programme_expires_at",
    "row_digest",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locate_packet(directory):
    directory = Path(directory).resolve()
    candidates = [
        directory / name
        for name in (
            "packet.json.gz",
            "REPLAYED-PACKET.json.gz",
            "FROZEN-PACKET.json.gz",
            "DRAFT-MOCK-PACKET.json.gz",
        )
        if (directory / name).is_file()
    ]
    if not candidates or len({_digest(read(p)) for p in candidates}) != 1:
        raise RuntimeError("Exactly one unambiguous frozen packet identity is required")
    return candidates[0]


def load_packet(directory, application_commit):
    if not re.fullmatch("[a-f0-9]{40}", application_commit):
        raise RuntimeError("Exact application commit required")
    subprocess.run(["git", "cat-file", "-e", application_commit + "^{commit}"], check=True)
    path = locate_packet(directory)
    packet = read(path)
    assert packet["application_commit"] == application_commit
    assert packet["approved"] is False
    assert set(packet["programme"]) == PROGRAMME_FIELDS
    assert packet["revision"] == "d5-comparison-machine-campaign-v19"
    errors = privacy_violations(packet, "packet.json.gz")
    if errors:
        raise RuntimeError("Private owner/ledger data in supplied packet: " + "; ".join(errors))
    verify(packet)  # Current producer bytes, frozen discovery and closed policies.
    return path, packet


def privacy_violations(value, filename, location="$"):
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = location + "." + key
            if key in {
                "record",
                "authorization_record",
                "authorization_chain",
                "api_key",
                "ANTHROPIC_API_KEY",
                "workspace_generation_jobs",
                "workspace_spend_reservations",
            }:
                errors.append(here)
            if key in {"approved_by", "approval_source", "approved_at"} and not (
                filename == "AUTHORIZATION-TEMPLATE.json" and child is None
            ):
                errors.append(here)
            if key == "approved" and child is not False:
                errors.append(here)
            if key == "authorization_kind" and child == "offline_fixture":
                errors.append(here)
            if key == "transport_mode" and child == "mock":
                errors.append(here)
            errors.extend(privacy_violations(child, filename, here))
        messages = value.get("messages")
        if isinstance(messages, list):
            for i, message in enumerate(messages):
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    errors.extend(
                        privacy_violations(
                            json.loads(message["content"]),
                            filename,
                            location + f".messages[{i}].decoded_context",
                        )
                    )
    elif isinstance(value, list):
        for i, child in enumerate(value):
            errors.extend(privacy_violations(child, filename, location + "[" + str(i) + "]"))
    elif isinstance(value, str) and (
        "arxiv-private-notes" in value or "READONLY-POST-RUN" in value
    ):
        errors.append(location)
    return errors


def scan_package(directory):
    directory = Path(directory)
    checked, errors = [], []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".gz"}:
            continue
        raw = path.read_bytes()
        value = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
        name = path.relative_to(directory).as_posix()
        checked.append(name)
        errors.extend(name + ":" + error for error in privacy_violations(value, name))
    if errors:
        raise RuntimeError("Structural privacy violation: " + "; ".join(errors))
    return checked


def private_output(path):
    path = Path(path).resolve()
    evidence = Path.home() / "Machine-Learning-Projects/arxiv-evidence"
    if not path.is_relative_to(evidence.resolve()):
        raise RuntimeError(
            "Replay output must remain under permanent private arxiv-evidence storage"
        )
    if path.exists() and any(path.iterdir()):
        raise RuntimeError("New empty evidence directory required; never overwrite evidence")
    path.mkdir(parents=True, exist_ok=True)
    return path
